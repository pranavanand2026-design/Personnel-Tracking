"""CSV logs written to output/."""
import csv
from pathlib import Path

from counter.detector import Detection


class DetectionLog:
    """Per-frame detection counts and per-box details, for comparison with
    the CAVIAR ground truth (miss rate by distance from the camera)."""

    def __init__(self, out_dir: Path, video_stem: str, run_id: str):
        out_dir.mkdir(exist_ok=True)
        self.frames_path = out_dir / f"{video_stem}_{run_id}_detections_per_frame.csv"
        self.boxes_path = out_dir / f"{video_stem}_{run_id}_detections_boxes.csv"
        self._ff = open(self.frames_path, "w", newline="")
        self._bf = open(self.boxes_path, "w", newline="")
        self._frames = csv.writer(self._ff)
        self._boxes = csv.writer(self._bf)
        self._frames.writerow(["frame", "timestamp_s", "count", "mean_conf", "infer_ms"])
        self._boxes.writerow(["frame", "timestamp_s", "x1", "y1", "x2", "y2",
                              "width", "height", "conf"])

    def log(self, frame: int, ts: float, dets: list[Detection], infer_ms: float) -> None:
        mean_conf = sum(d.conf for d in dets) / len(dets) if dets else 0.0
        self._frames.writerow([frame, f"{ts:.3f}", len(dets), f"{mean_conf:.3f}",
                               f"{infer_ms:.1f}"])
        for d in dets:
            self._boxes.writerow([frame, f"{ts:.3f}", f"{d.x1:.1f}", f"{d.y1:.1f}",
                                  f"{d.x2:.1f}", f"{d.y2:.1f}", f"{d.w:.1f}",
                                  f"{d.h:.1f}", f"{d.conf:.3f}"])

    def close(self) -> None:
        self._ff.close()
        self._bf.close()
