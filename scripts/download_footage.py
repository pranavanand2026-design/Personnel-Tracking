"""Download CAVIAR corridor-view clips and their ground-truth XML.

Videos  -> footage/caviar/<ClipName>.mpg
GT XML  -> footage/caviar/gt/<gt>.xml

Usage: .venv/bin/python scripts/download_footage.py
"""
import sys
import time
import urllib.request
from pathlib import Path

import cv2

BASE = "https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA2"
CLIPS = {
    "EnterExitCrossingPaths1cor": "ceecp1gt.xml",
    "ThreePastShop1cor": "c3ps1gt.xml",
    "OneShopOneWait2cor": "cosow2gt.xml",
    "OneStopMoveEnter1cor": "cosme1gt.xml",
    "WalkByShop1cor": "cwbs1gt.xml",
    "ShopAssistant2cor": "csa2gt.xml",
}

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "footage" / "caviar"
GT = OUT / "gt"
CHUNK = 64 * 1024


def _fetch(url: str, dest: Path) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=30) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(CHUNK):
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done / total
                bar = "#" * int(pct * 30)
                print(f"\r  {dest.name:<34} [{bar:<30}] {pct:6.1%} "
                      f"{done / 1e6:6.1f}/{total / 1e6:.1f} MB", end="", flush=True)
            else:
                print(f"\r  {dest.name:<34} {done / 1e6:6.1f} MB", end="", flush=True)
    print()
    if total and done != total:
        raise IOError(f"incomplete download ({done}/{total} bytes)")
    part.rename(dest)


def download(url: str, dest: Path) -> bool:
    if dest.exists():
        print(f"  {dest.name:<34} exists, skipping")
        return True
    for attempt in (1, 2):
        try:
            _fetch(url, dest)
            return True
        except Exception as e:  # network errors, HTTP errors, short reads
            print(f"\n  {dest.name}: attempt {attempt} failed: {e}")
            dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            if attempt == 1:
                time.sleep(2)
    return False


def check_video(path: Path) -> tuple[bool, str]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return False, "could not open"
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    ok, _ = cap.read()
    if not ok:
        cap.release()
        return False, "first frame unreadable"
    frames = 1
    while cap.grab():  # MPEG-1 header frame counts are unreliable, so count
        frames += 1
    cap.release()
    return True, f"{w}x{h}  {fps:5.2f} fps  {frames:5d} frames"


def main() -> int:
    GT.mkdir(parents=True, exist_ok=True)
    failed = []

    for clip, gt in CLIPS.items():
        print(clip)
        if not download(f"{BASE}/{clip}/{clip}.mpg", OUT / f"{clip}.mpg"):
            failed.append(f"{clip}.mpg (download)")
        if not download(f"{BASE}/{clip}/{gt}", GT / gt):
            failed.append(f"{gt} (download)")

    print("\nDecode check")
    for clip in CLIPS:
        path = OUT / f"{clip}.mpg"
        if not path.exists():
            continue
        ok, info = check_video(path)
        print(f"  {'✓' if ok else '✗'} {clip:<28} {info}")
        if not ok:
            failed.append(f"{clip}.mpg (decode: {info})")

    if failed:
        print("\nFAILED:")
        for f in failed:
            print(f"  - {f}")
        return 1
    print("\nAll clips downloaded and decoded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
