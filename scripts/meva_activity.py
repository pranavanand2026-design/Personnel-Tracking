"""Activity check: how many people does each chosen MEVA camera see over one hour?

For each camera's 5-minute clips in the hour: download the clip, sample one
frame every 5 s, count people with YOLO11n, delete the clip. Downloads run one
at a time. Results are appended per clip, so an interrupted run resumes.

Outputs (footage/meva/):
  activity.csv          one row per sampled frame
  activity_windows.csv  mean/max people per camera per 5-minute window, ranked

Usage: .venv/bin/python scripts/meva_activity.py [--hour 2018-03-12/10]
"""
import argparse
import collections
import csv
import sys
import tempfile
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from counter.detector import PersonDetector  # noqa: E402
from meva_survey import OUT, fetch, list_bucket  # noqa: E402

CAMERAS = {  # zone -> camera
    "entrance": "G420",
    "corridor": "G423",
    "lobby": "G421",
    "hall": "G299",
    "muster": "G336",
}
SAMPLE_EVERY_S = 5
ACTIVITY = OUT / "activity.csv"
WINDOWS = OUT / "activity_windows.csv"
FIELDS = ["zone", "camera", "clip", "window", "t_s", "people", "mean_conf"]


def window_of(start: str) -> str:
    """'10-05-01' -> '10:05' (clips start within a few seconds of the mark)."""
    h, m, _s = (int(x) for x in start.split("-"))
    return f"{h:02d}:{m - m % 5:02d}"


def sample_clip(path: Path, detector: PersonDetector):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = int(SAMPLE_EVERY_S * fps)
    for idx in range(0, max(total, 1), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        dets = detector.detect(frame)
        conf = sum(d.conf for d in dets) / len(dets) if dets else None
        yield idx / fps, len(dets), conf
    cap.release()


def summarise() -> None:
    rows = list(csv.DictReader(open(ACTIVITY)))
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["window"], r["zone"])].append(int(r["people"]))
    windows = sorted({w for w, _ in by})
    out = []
    for w in windows:
        row = {"window": w}
        busy = 0
        total = 0.0
        for zone in CAMERAS:
            vals = by.get((w, zone))
            if vals:
                mean = sum(vals) / len(vals)
                row[f"{zone}_mean"] = round(mean, 2)
                row[f"{zone}_max"] = max(vals)
                busy += mean >= 1
                total += mean
            else:
                row[f"{zone}_mean"] = row[f"{zone}_max"] = ""
        row["zones_with_people"] = busy
        row["complete"] = all(by.get((w, z)) for z in CAMERAS)
        row["total_mean"] = round(total, 2)
        out.append(row)
    out.sort(key=lambda r: (r["complete"], r["zones_with_people"], r["total_mean"]),
             reverse=True)
    with open(WINDOWS, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    print(f"\n{'window':<7}" + "".join(f"{z:>10}" for z in CAMERAS) + "  busy  total")
    for r in out:
        print(f"{r['window']:<7}" + "".join(
            f"{(str(r[z + '_mean']) + '/' + str(r[z + '_max'])) if r[z + '_mean'] != '' else '-':>10}"
            for z in CAMERAS) + f"  {r['zones_with_people']:>4}  {r['total_mean']:>5}"
            + ("" if r["complete"] else "  (incomplete)"))
    print("(mean/max people per sampled frame)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hour", default="2018-03-12/10")
    args = parser.parse_args()

    cam_zone = {c: z for z, c in CAMERAS.items()}
    clips = sorted((r for r in list_bucket(False)
                    if r["folder"] == args.hour and r["camera"] in cam_zone),
                   key=lambda r: (r["start"], r["camera"]))
    done = set()
    if ACTIVITY.exists():
        done = {r["clip"] for r in csv.DictReader(open(ACTIVITY))}
    else:
        with open(ACTIVITY, "w", newline="") as f:
            csv.writer(f).writerow(FIELDS)
    todo = [c for c in clips if Path(c["key"]).name not in done]
    print(f"{len(clips)} clips for {len(CAMERAS)} cameras in {args.hour}; "
          f"{len(todo)} to process ({sum(c['size'] for c in todo) / 1e9:.2f} GB)")

    detector = PersonDetector()
    with tempfile.TemporaryDirectory() as tmp:
        for i, clip in enumerate(todo, 1):
            name = Path(clip["key"]).name
            zone = cam_zone[clip["camera"]]
            dest = Path(tmp) / name
            print(f"[{i:2d}/{len(todo)}] {zone:<9} {clip['camera']} {clip['start']} "
                  f"{clip['size'] / 1e6:6.1f} MB ...", end=" ", flush=True)
            try:
                fetch(clip["key"], dest, None)
                samples = list(sample_clip(dest, detector))
            except Exception as e:  # network/decode errors: skip, rerun resumes
                print(f"FAILED: {e}")
                continue
            finally:
                dest.unlink(missing_ok=True)
            with open(ACTIVITY, "a", newline="") as f:
                w = csv.writer(f)
                for t, n, conf in samples:
                    w.writerow([zone, clip["camera"], name, window_of(clip["start"]),
                                f"{t:.0f}", n, f"{conf:.3f}" if conf else ""])
            people = [n for _, n, _ in samples]
            print(f"{len(samples)} samples, mean {sum(people) / max(len(people), 1):.1f}, "
                  f"max {max(people, default=0)}")

    summarise()
    return 0


if __name__ == "__main__":
    sys.exit(main())
