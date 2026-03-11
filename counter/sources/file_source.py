"""Video file played like a live camera: native frame rate, loops at the end.

The frame position follows the wall clock. If the consumer is slower than the
video, frames are skipped (as a real camera would drop them) rather than the
video slowing down, so slowdowns show up as lower processed fps.
"""
import time
from pathlib import Path

import cv2
import numpy as np

from counter.sources.base import FrameSource


class FileSource(FrameSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise IOError(f"Could not open {self.path}")
        self._fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._pos = 0        # index of the next frame the capture will return
        self._loops = 0
        self._start = time.perf_counter()

    def _rewind(self) -> None:
        # Reopen rather than seek: seeking to frame 0 fails on MPEG-1 files
        self.cap.release()
        self.cap = cv2.VideoCapture(str(self.path))
        self._pos = 0
        self._loops += 1
        self._start = time.perf_counter()

    def read(self) -> tuple[np.ndarray | None, float]:
        for _ in range(2):  # second pass only after looping to the start
            target = int((time.perf_counter() - self._start) * self._fps)
            if target < self._pos:  # consumer is ahead of real time: wait
                time.sleep((self._pos - target) / self._fps)
                target = self._pos
            while self._pos < target and self.cap.grab():  # behind: drop frames
                self._pos += 1
            if self._pos >= target:
                ok, frame = self.cap.read()
                if ok:
                    ts = self._pos / self._fps
                    self._pos += 1
                    return frame, ts
            self._rewind()
        return None, 0.0

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def source_info(self) -> dict:
        return {"type": "file", "path": str(self.path), "name": self.path.name,
                "loops": self._loops,
                "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}

    def close(self) -> None:
        self.cap.release()
