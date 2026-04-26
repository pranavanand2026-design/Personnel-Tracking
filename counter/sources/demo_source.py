"""Demo camera: a recording that behaves like a live camera on a shared clock.

Every demo source computes its frame from the same epoch (set at "Go live"),
so all demo cameras show the same moment of the recording. Frames are
released at real time; if processing lags, frames are skipped. When the
recording wraps, `loops` increments so the worker can reset per-run state.
"""
import time
from pathlib import Path

import cv2
import numpy as np

from counter.sources.base import FrameSource

SEEK_AHEAD_FRAMES = 90  # beyond this, seek instead of grabbing frame by frame


class DemoSource(FrameSource):
    def __init__(self, path: str | Path, epoch: float, feed_id: str = "",
                 mask: list | None = None):
        self.path = Path(path)
        self.feed_id = feed_id
        self.epoch = epoch
        self.mask = mask or []
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise IOError(f"Could not open {self.path}")
        self._fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.total <= 0:
            raise IOError(f"{self.path}: unknown frame count")
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._pos = 0  # index of the next frame the capture returns
        self._cycle = None
        self.loops = 0

    def _clock(self) -> tuple[int, int]:
        """(cycle, frame index) the shared clock points at right now."""
        n = int((time.time() - self.epoch) * self._fps)
        return n // self.total, n % self.total

    def _seek(self, idx: int) -> None:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        self._pos = idx

    def read(self) -> tuple[np.ndarray | None, float]:
        cycle, idx = self._clock()
        if self._cycle is None:
            self._cycle = cycle
            self._seek(idx)
        elif cycle != self._cycle:  # recording wrapped
            self._cycle = cycle
            self.loops += 1
            self.cap.release()
            self.cap = cv2.VideoCapture(str(self.path))
            self._pos = 0
            if idx > SEEK_AHEAD_FRAMES:
                self._seek(idx)
        if idx < self._pos:  # ahead of the clock: wait for the next frame
            time.sleep((self._pos - idx) / self._fps)
            idx = self._pos
        if idx - self._pos > SEEK_AHEAD_FRAMES:
            self._seek(idx)
        while self._pos < idx and self.cap.grab():  # lagging: drop frames
            self._pos += 1
        ok, frame = self.cap.read()
        if not ok:
            return None, 0.0
        ts = self._pos / self._fps
        self._pos += 1
        h, w = frame.shape[:2]
        for x, y, mw, mh in self.mask:  # e.g. a burned-in date
            frame[int(y * h):int((y + mh) * h), int(x * w):int((x + mw) * w)] = 0
        return frame, ts

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def source_info(self) -> dict:
        return {"type": "demo", "feed": self.feed_id, "path": str(self.path),
                "name": self.path.name, "loops": self.loops,
                "width": self.width, "height": self.height,
                "position_s": round(self._pos / self._fps, 1),
                "duration_s": round(self.total / self._fps, 1)}

    def close(self) -> None:
        self.cap.release()
