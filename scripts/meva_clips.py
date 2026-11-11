"""Fetch one 5-minute window of the five chosen MEVA cameras and standardise it.

Each clip is downloaded, resized to 1280x720 at its native frame rate
(30 fps), written as footage/meva/clips/<zone>_<camera>_<HHMM>.mp4, and the
original 1080p download is deleted.

Usage: .venv/bin/python scripts/meva_clips.py --window 10:20 [--hour 2018-03-12/10]
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meva_activity import CAMERAS, window_of  # noqa: E402
from meva_survey import OUT, fetch, list_bucket  # noqa: E402

CLIPS = OUT / "clips"
SIZE = (1280, 720)


def transcode(src: Path, dest: Path) -> dict:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    tmp = dest.with_suffix(".part.mp4")
    out = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, SIZE)
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        out.write(cv2.resize(frame, SIZE, interpolation=cv2.INTER_AREA))
        n += 1
    cap.release()
    out.release()
    if n == 0:
        tmp.unlink(missing_ok=True)
        raise IOError("no frames decoded")
    tmp.rename(dest)
    return {"frames": n, "fps": fps, "source_size": list(src_size), "size": list(SIZE)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", required=True, help="5-minute window, e.g. 10:20")
    parser.add_argument("--hour", default="2018-03-12/10")
    args = parser.parse_args()

    CLIPS.mkdir(parents=True, exist_ok=True)
    rows = [r for r in list_bucket(False) if r["folder"] == args.hour]
    manifest = {"hour": args.hour, "window": args.window, "zones": {}}
    for zone, cam in CAMERAS.items():
        match = [r for r in rows if r["camera"] == cam and window_of(r["start"]) == args.window]
        if not match:
            print(f"{zone:<9} {cam}: no clip in window {args.window}")
            continue
        clip = match[0]
        dest = CLIPS / f"{zone}_{cam}_{args.window.replace(':', '')}.mp4"
        if dest.exists():
            print(f"{zone:<9} {cam}: {dest.name} exists, skipping")
        else:
            print(f"{zone:<9} {cam}: {clip['size'] / 1e6:.0f} MB ...", end=" ", flush=True)
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / Path(clip["key"]).name
                fetch(clip["key"], src, None)
                info = transcode(src, dest)
            print(f"{info['frames']} frames -> {dest.name} "
                  f"({dest.stat().st_size / 1e6:.0f} MB)")
        manifest["zones"][zone] = {"camera": cam, "file": f"footage/meva/clips/{dest.name}",
                                   "source_clip": Path(clip["key"]).name}
    (CLIPS / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {CLIPS / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
