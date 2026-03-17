"""Raspberry Pi camera via Picamera2. Stub: same interface as FileSource,
not implemented yet."""
from counter.sources.base import FrameSource


class PiCameraSource(FrameSource):
    def __init__(self, width: int = 640, height: int = 480, fps: float = 25.0):
        raise NotImplementedError("PiCameraSource is not implemented yet")

    def read(self):
        raise NotImplementedError

    @property
    def fps(self) -> float:
        raise NotImplementedError

    @property
    def source_info(self) -> dict:
        raise NotImplementedError
