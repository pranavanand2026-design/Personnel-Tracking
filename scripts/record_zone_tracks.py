"""Record per-zone tracks and appearance profiles for the demo cameras (offline).

For each demo camera: YOLO11n + BoT-SORT (fixed-camera settings) on every
STEP-th frame at 1280x720, plus appearance vectors for each track: every 0.5 s
during its first EARLY_S seconds, then every 1 s. Writes, per camera:
  output/eval/tracking/<CAM>.tracks.jsonl.gz  {"f": frame, "t": [[id, x1, y1, x2, y2, conf], ...]}
  output/eval/tracking/<CAM>.vectors.npz      id, f, v (float16)
Frames and boxes are in feed coordinates scaled to 1280x720; frame numbers are
the feed's own (30 fps).

Usage: .venv/bin/python scripts/record_zone_tracks.py [--only CAM-REC-01 ...]
       [--tracker counter/trackers/botsort_reid.yaml] [--out output/eval/tracking-reid]
"""
import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from counter.appearance import AppearanceEncoder, usable  # noqa: E402
from counter.detector import MODEL_PATH, PERSON, pick_device  # noqa: E402
from counter.sources.demo_registry import DEMO_FEEDS, feed_path  # noqa: E402

OUT = ROOT / "output" / "eval" / "tracking"
TRACKER = ROOT / "counter" / "trackers" / "botsort_static.yaml"
SIZE = (1280, 720)
STEP = 2          # 15 fps from 30 fps feeds
EARLY_S = 2.0


def record(feed: dict, device: str, tracker: Path, out_dir: Path) -> None:
    from ultralytics import YOLO
    model = YOLO(str(MODEL_PATH))
    enc = AppearanceEncoder()
    cap = cv2.VideoCapture(str(feed_path(feed["id"])))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    first, last_vec = {}, {}
    vec_id, vec_f, vecs = [], [], []
    t0 = time.time()
    with gzip.open(out_dir / f"{feed['id']}.tracks.jsonl.gz", "wt") as out:
        out.write(json.dumps({"feed": feed["id"], "camera": feed["camera"], "size": SIZE, "tracker": tracker.name,
                              "step": STEP, "fps": fps, "frames": total}) + "\n")
        for f in range(total):
            if f % STEP:
                if not cap.grab():
                    break
                continue
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, SIZE)
            r = model.track(frame, persist=True, tracker=str(tracker), classes=[PERSON],
                            device=device, verbose=False)[0]
            rows = []
            if r.boxes is not None and r.boxes.id is not None:
                for i, xyxy, c in zip(r.boxes.id.int().tolist(), r.boxes.xyxy.cpu().tolist(),
                                      r.boxes.conf.cpu().tolist()):
                    rows.append([i, *(round(v, 1) for v in xyxy), round(c, 3)])
            out.write(json.dumps({"f": f, "t": rows}) + "\n")
            # appearance: denser while a track is new, then once a second
            want = []
            for i, *box, _ in rows:
                first.setdefault(i, f)
                every = 0.5 if (f - first[i]) / fps < EARLY_S else 1.0
                if (f - last_vec.get(i, -1e9)) / fps >= every and usable(box, *SIZE):
                    want.append((i, box))
                    last_vec[i] = f
            if want:
                for (i, _), v in zip(want, enc.encode(frame, [b for _, b in want])):
                    vec_id.append(i); vec_f.append(f); vecs.append(v.astype(np.float16))
            if f % 1500 == 0:
                print(f"  {feed['id']}: {f / total:.0%} ({time.time() - t0:.0f} s)", flush=True)
    np.savez_compressed(out_dir / f"{feed['id']}.vectors.npz", id=np.array(vec_id), f=np.array(vec_f),
                        v=np.array(vecs).reshape(-1, 512))
    print(f"  {feed['id']}: done, {len(first)} track IDs, {len(vecs)} vectors, "
          f"{time.time() - t0:.0f} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tracker", type=Path, default=TRACKER)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = pick_device()
    for feed in DEMO_FEEDS:
        if not args.only or feed["id"] in args.only:
            print(f"{feed['id']} ({feed['name']}):", flush=True)
            record(feed, device, args.tracker, args.out)


if __name__ == "__main__":
    main()
