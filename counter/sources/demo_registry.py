"""Demo camera registry: recordings that stand in for live cameras.

Four cameras from NVIDIA PhysicalAI-SmartSpaces (2024 edition, scene 081, a
synthetic hospital floor), downloaded by scripts/prepare_demo_feeds.py. The
videos are time-synchronised and the same length, so playing them against one
shared clock keeps the cameras in sync. No person is ever in two of these
cameras at once, so each one behaves like a separate zone.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATASET = {
    "name": "NVIDIA PhysicalAI-SmartSpaces",
    "short": "SmartSpaces",
    "scene": "MTMC_Tracking_2024/test/scene_081",
    "url": "https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces",
}
DEMO_DIR = ROOT / "footage" / "smartspaces" / "scene_081"

# mask: rectangles to black out (fractions of width/height). Empty: no burned-in text.
# detect_size: detector input size; the long corridor needs 1280 for its distant people
# (scripts/eval_tracking.py: within ±1 person 38% of the time at 640, 73% at 1280).
DEMO_FEEDS = [
    {"id": "CAM-REC-01", "name": "Reception", "camera": "0803", "mask": []},
    {"id": "CAM-COR-01", "name": "Main Corridor", "camera": "0800", "mask": [], "detect_size": 1280},
    {"id": "CAM-WAI-01", "name": "Waiting Alcove", "camera": "0804", "mask": []},
    {"id": "CAM-EAS-01", "name": "East Wing Corridor", "camera": "0796", "mask": []},
]
FEEDS = {f["id"]: f for f in DEMO_FEEDS}


def feed_path(feed_id: str) -> Path:
    return DEMO_DIR / f"camera_{FEEDS[feed_id]['camera']}" / "video.mp4"


def feed_info(feed_id: str) -> dict | None:
    f = FEEDS.get(feed_id)
    if not f:
        return None
    return {**f, "path": str(feed_path(feed_id)), "ready": feed_path(feed_id).exists(),
            "credit": f"{DATASET['short']} scene 081, camera {f['camera']}"}
