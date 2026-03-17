"""Network camera over RTSP. Stub: same interface as FileSource, not implemented yet."""
from counter.sources.base import FrameSource


class RTSPSource(FrameSource):
    def __init__(self, url: str):
        raise NotImplementedError("RTSP cameras are not implemented yet")

    def read(self):
        raise NotImplementedError

    @property
    def fps(self) -> float:
        raise NotImplementedError

    @property
    def source_info(self) -> dict:
        raise NotImplementedError
