"""USB camera via OpenCV. Stub: same interface as FileSource, not implemented yet."""
from counter.sources.base import FrameSource


class USBCameraSource(FrameSource):
    def __init__(self, device: int = 0, width: int | None = None,
                 height: int | None = None):
        raise NotImplementedError("USBCameraSource is not implemented yet")

    def read(self):
        raise NotImplementedError

    @property
    def fps(self) -> float:
        raise NotImplementedError

    @property
    def source_info(self) -> dict:
        raise NotImplementedError
