from pathlib import Path

from counter.sources.base import FrameSource
from counter.sources.demo_registry import FEEDS, feed_path
from counter.sources.demo_source import DemoSource
from counter.sources.file_source import FileSource
from counter.sources.pi_camera import PiCameraSource
from counter.sources.rtsp_source import RTSPSource
from counter.sources.usb_camera import USBCameraSource

ROOT = Path(__file__).resolve().parent.parent.parent


def make_source(cfg: dict) -> FrameSource:
    """Build a FrameSource from a zone's `source:` config block."""
    kind = cfg["type"]
    if kind == "file":
        path = Path(cfg["path"])
        return FileSource(path if path.is_absolute() else ROOT / path)
    if kind == "demo":
        feed = cfg["feed"]
        return DemoSource(feed_path(feed), cfg["epoch"], feed_id=feed,
                          mask=FEEDS.get(feed, {}).get("mask"))
    if kind == "rtsp":
        return RTSPSource(cfg["url"])
    if kind == "usb_camera":
        return USBCameraSource(cfg.get("device", 0))
    if kind == "pi_camera":
        return PiCameraSource()
    raise ValueError(f"Unknown source type: {kind}")
