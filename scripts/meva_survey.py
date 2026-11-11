"""Survey MEVA cameras for one hour and build a contact sheet.

1. List s3://mevadata-public-01/drops-123-r13/ (cached in footage/meva/listing.txt)
2. Pick the date/hour folder with the most distinct cameras (tie-break: most clips)
3. For each camera, fetch its first 5-minute clip, grab the frame at 30 s,
   delete the clip. Only the first part of each clip is downloaded (HTTP range
   request, enough to reach 30 s); the full clip is fetched only if that fails.

Outputs: footage/meva/cameras.csv, footage/meva/contact_sheet.jpg

Usage: .venv/bin/python scripts/meva_survey.py [--hour 2018-03-07/17] [--refresh]
"""
import argparse
import collections
import csv
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

BUCKET = "mevadata-public-01"
PREFIX = "drops-123-r13/"
HTTPS = f"https://{BUCKET}.s3.amazonaws.com/"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "footage" / "meva"
LISTING = OUT / "listing.txt"
FRAME_AT_S = 30
MIN_CLIP_S = 270  # "5-minute" clips; shorter ones are partial segments
NAME = re.compile(r".*/(\d{4}-\d\d-\d\d)/(\d\d)/\d{4}-\d\d-\d\d\.([\d-]+)\.([\d-]+)"
                  r"\.([\w-]+)\.(\w+)\.r13\.avi$")
TILE_W, TILE_H, COLS = 384, 216, 6


def list_bucket(refresh: bool) -> list[dict]:
    if refresh or not LISTING.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        print("Listing bucket...")
        out = subprocess.run(
            [sys.executable, "-m", "awscli", "s3", "ls", f"s3://{BUCKET}/{PREFIX}",
             "--recursive", "--no-sign-request"],
            capture_output=True, text=True, check=True).stdout
        LISTING.write_text(out)
    rows = []
    for line in LISTING.read_text().splitlines():
        _d, _t, size, key = line.split(None, 3)
        m = NAME.match(key)
        if not m:
            continue
        start = datetime.strptime(m[3], "%H-%M-%S")
        end = datetime.strptime(m[4], "%H-%M-%S")
        rows.append({"key": key, "size": int(size), "folder": f"{m[1]}/{m[2]}",
                     "start": m[3], "end": m[4], "location": m[5], "camera": m[6],
                     "duration_s": (end - start).seconds})
    return rows


def pick_hour(rows: list[dict]) -> str:
    cams = collections.defaultdict(set)
    clips = collections.Counter()
    for r in rows:
        cams[r["folder"]].add(r["camera"])
        clips[r["folder"]] += 1
    return max(cams, key=lambda f: (len(cams[f]), clips[f]))


def fetch(key: str, dest: Path, nbytes: int | None) -> None:
    req = urllib.request.Request(HTTPS + key)
    if nbytes:
        req.add_header("Range", f"bytes=0-{nbytes - 1}")
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)


def frame_at(path: Path, t: float) -> tuple[np.ndarray | None, int, int, float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None, 0, 0, 0.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    target, n = int(t * fps), 0
    while n < target and cap.grab():
        n += 1
    ok, frame = cap.read()
    cap.release()
    return (frame if ok and n == target else None), w, h, fps


def grab_camera(clip: dict, tmp: Path) -> tuple[np.ndarray | None, int, int, float, str]:
    dest = tmp / Path(clip["key"]).name
    # Bytes for ~38 s of video plus headroom (bitrate varies scene to scene)
    partial = max(int(clip["size"] * 38 / clip["duration_s"] * 1.3), 2_000_000)
    attempts = [(partial, "partial")] if partial < clip["size"] else []
    attempts.append((None, "full"))
    try:
        for nbytes, how in attempts:
            fetch(clip["key"], dest, nbytes)
            frame, w, h, fps = frame_at(dest, FRAME_AT_S)
            if frame is not None:
                return frame, w, h, fps, how
        return None, w, h, fps, "decode failed"
    finally:
        dest.unlink(missing_ok=True)


def tile(frame: np.ndarray | None, top: str, bottom: str) -> np.ndarray:
    if frame is None:
        img = np.full((TILE_H, TILE_W, 3), 40, np.uint8)
        cv2.putText(img, "no frame", (TILE_W // 2 - 50, TILE_H // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    else:
        h, w = frame.shape[:2]
        s = min(TILE_W / w, TILE_H / h)
        small = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        img = np.zeros((TILE_H, TILE_W, 3), np.uint8)
        y, x = (TILE_H - small.shape[0]) // 2, (TILE_W - small.shape[1]) // 2
        img[y:y + small.shape[0], x:x + small.shape[1]] = small
    for text, y, scale in ((top, 24, 0.65), (bottom, TILE_H - 10, 0.45)):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        cv2.rectangle(img, (4, y - th - 6), (12 + tw, y + 5), (0, 0, 0), -1)
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (255, 255, 255), 1 if scale < 0.5 else 2, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (TILE_W - 1, TILE_H - 1), (80, 80, 80), 1)
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hour", help="date/hour folder, e.g. 2018-03-07/17")
    parser.add_argument("--refresh", action="store_true", help="re-list the bucket")
    args = parser.parse_args()

    rows = list_bucket(args.refresh)
    hour = args.hour or pick_hour(rows)
    in_hour = [r for r in rows if r["folder"] == hour]
    cams = sorted({(r["location"], r["camera"]) for r in in_hour})
    print(f"Hour {hour}: {len(cams)} cameras, {len(in_hour)} clips")

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (loc, cam) in enumerate(cams, 1):
            clips = sorted((r for r in in_hour if r["camera"] == cam),
                           key=lambda r: r["start"])
            full = [r for r in clips if r["duration_s"] >= MIN_CLIP_S]
            clip = (full or clips)[0]
            print(f"  [{i:2d}/{len(cams)}] {loc:<9} {cam}  {clip['start']}  "
                  f"{clip['size'] / 1e6:6.1f} MB ...", end=" ", flush=True)
            try:
                frame, w, h, fps, how = grab_camera(clip, Path(tmpdir))
            except Exception as e:  # network errors: record and keep going
                frame, w, h, fps, how = None, 0, 0, 0.0, f"error: {e}"
            print(f"{w}x{h} {fps:.1f} fps ({how})")
            results.append({"location": loc, "camera": cam, "clips_in_hour": len(clips),
                            "clip": Path(clip["key"]).name, "clip_mb": round(clip["size"] / 1e6, 1),
                            "duration_s": clip["duration_s"], "width": w, "height": h,
                            "fps": round(fps, 2), "frame_ok": frame is not None,
                            "fetch": how, "_frame": frame})

    with open(OUT / "cameras.csv", "w", newline="") as f:
        fields = [k for k in results[0] if not k.startswith("_")]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    tiles = [tile(r["_frame"], f"{r['location']}  {r['camera']}",
                  f"{r['width']}x{r['height']}  {r['fps']:.0f} fps") for r in results]
    while len(tiles) % COLS:
        tiles.append(np.zeros((TILE_H, TILE_W, 3), np.uint8))
    grid = np.vstack([np.hstack(tiles[i:i + COLS]) for i in range(0, len(tiles), COLS)])
    header = np.zeros((40, grid.shape[1], 3), np.uint8)
    cv2.putText(header, f"MEVA  {hour}:00  frame at {FRAME_AT_S}s of each camera's first "
                f"5-min clip  ({len(results)} cameras)", (10, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "contact_sheet.jpg"), np.vstack([header, grid]),
                [cv2.IMWRITE_JPEG_QUALITY, 88])

    failed = [r for r in results if not r["frame_ok"]]
    print(f"\nWrote {OUT / 'cameras.csv'} and {OUT / 'contact_sheet.jpg'}")
    if failed:
        print("No frame for: " + ", ".join(f"{r['location']} {r['camera']}" for r in failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
