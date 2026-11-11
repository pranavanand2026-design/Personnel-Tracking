"""Download the demo camera feeds from NVIDIA PhysicalAI-SmartSpaces.

For each demo camera: download its video.mp4 and calibration.json from scene 081
(MTMC_Tracking_2024/test) into footage/smartspaces/scene_081/camera_<id>/, plus the
scene's ground truth and calibration. Videos are used as published (1920x1080,
30 fps, all the same length). Existing files are skipped. About 740 MB in total.

Usage: .venv/bin/python scripts/prepare_demo_feeds.py [--only CAM-REC-01 ...]
"""
import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from counter.sources.demo_registry import DATASET, DEMO_DIR, DEMO_FEEDS, feed_path  # noqa: E402

BASE = f"{DATASET['url']}/resolve/main/{DATASET['scene']}"


def fetch(rel: str, dest: Path) -> None:
    if dest.exists():
        print(f"  have {dest.relative_to(ROOT)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    print(f"  downloading {rel}")
    urllib.request.urlretrieve(f"{BASE}/{rel}", part)
    part.rename(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="demo camera ids, e.g. CAM-REC-01")
    args = ap.parse_args()
    fetch("ground_truth.txt", DEMO_DIR / "ground_truth.txt")
    fetch("calibration_2025_format.json", DEMO_DIR / "calibration_2025_format.json")
    for feed in DEMO_FEEDS:
        if args.only and feed["id"] not in args.only:
            continue
        cam = f"camera_{feed['camera']}"
        print(f"{feed['id']} ({feed['name']}, {cam}):")
        fetch(f"{cam}/video.mp4", feed_path(feed["id"]))
        fetch(f"{cam}/calibration.json", DEMO_DIR / cam / "calibration.json")


if __name__ == "__main__":
    main()
