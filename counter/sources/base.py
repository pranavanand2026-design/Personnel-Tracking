"""FrameSource interface: anything that yields timestamped frames."""
from abc import ABC, abstractmethod

import numpy as np


class FrameSource(ABC):
    @abstractmethod
    def read(self) -> tuple[np.ndarray | None, float]:
        """Return (frame, timestamp_s). frame is None if no frame is available."""

    @property
    @abstractmethod
    def fps(self) -> float:
        """Native frame rate of the source."""

    @property
    @abstractmethod
    def source_info(self) -> dict:
        """Description for the dashboard, e.g. {"type": "file", "path": ...}."""

    def close(self) -> None:
        pass
