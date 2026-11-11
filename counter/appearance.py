"""Appearance profiles for linking people across zones, without faces or names.

Each person crop becomes a 512-number vector (Ultralytics yolo26n-reid, ONNX)
that mostly reflects clothing colour, texture and body shape. Only vectors leave
this module: crops are never stored.
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
REID_PATH = ROOT / "models" / "yolo26n-reid.onnx"
MIN_CROP_H = 60  # px; smaller people give unreliable profiles


class AppearanceEncoder:
    def __init__(self):
        from ultralytics.trackers.utils.reid import ReID
        # Ultralytics downloads the official asset when the file is missing
        self.reid = ReID(str(REID_PATH) if REID_PATH.exists() else "yolo26n-reid.onnx")

    def encode(self, frame: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
        """boxes: x1, y1, x2, y2. Returns one L2-normalised vector per box."""
        if not boxes:
            return np.zeros((0, 512), np.float32)
        b = np.array(boxes, np.float32)
        xywh = np.stack([(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2,
                         b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], 1)
        e = np.asarray(self.reid(frame, xywh), np.float32)
        return e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-9)


def usable(box: tuple[float, float, float, float], width: int, height: int) -> bool:
    """Large enough and not cut off by the frame edge."""
    x1, y1, x2, y2 = box
    return y2 - y1 >= MIN_CROP_H and x1 > 2 and y1 > 2 and x2 < width - 2 and y2 < height - 2


def profile(vectors: np.ndarray) -> np.ndarray | None:
    """Mean of a track's vectors, re-normalised."""
    if len(vectors) == 0:
        return None
    m = np.asarray(vectors, np.float32).mean(0)
    return m / max(float(np.linalg.norm(m)), 1e-9)
