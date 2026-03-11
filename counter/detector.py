"""YOLO11n person detector."""
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "yolo11n.pt"
PERSON = 0


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class PersonDetector:
    def __init__(self, conf: float = 0.25, device: str | None = None):
        MODEL_PATH.parent.mkdir(exist_ok=True)
        # Ultralytics downloads the weights on first use if the file is missing
        self.model = YOLO(str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt")
        if not MODEL_PATH.exists() and Path("yolo11n.pt").exists():
            Path("yolo11n.pt").rename(MODEL_PATH)
        self.conf = conf
        self.device = device or pick_device()
        self.last_ms = 0.0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        t = time.perf_counter()
        result = self.model.predict(
            frame, classes=[PERSON], conf=self.conf, device=self.device, verbose=False
        )[0]
        self.last_ms = (time.perf_counter() - t) * 1000
        boxes = result.boxes
        return [
            Detection(*xyxy, conf=c)
            for xyxy, c in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist())
        ]
