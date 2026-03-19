"""ZoneState: the JSON-serialisable message each zone publishes once per second."""
import socket
import time
from pathlib import Path

import psutil

LOW_CONF = 0.4
THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")  # Raspberry Pi / Linux


def read_temperature() -> float | None:
    """CPU temperature in °C, or None where it can't be read (e.g. macOS)."""
    if hasattr(psutil, "sensors_temperatures"):
        for entries in (psutil.sensors_temperatures() or {}).values():
            if entries:
                return round(entries[0].current, 1)
    if THERMAL.exists():
        try:
            return round(int(THERMAL.read_text().strip()) / 1000, 1)
        except (OSError, ValueError):
            pass
    return None


class Telemetry:
    """Host and worker-process telemetry. cpu_percent needs a priming call."""

    def __init__(self):
        self.hostname = socket.gethostname()
        self.proc = psutil.Process()
        psutil.cpu_percent(None)
        self.proc.cpu_percent(None)

    def sample(self) -> dict:
        return {
            "hostname": self.hostname,
            "cpu_percent": psutil.cpu_percent(None),
            "memory_percent": psutil.virtual_memory().percent,
            "temperature_c": read_temperature(),
            # Can exceed 100 on multi-core hosts (100 = one full core)
            "worker_cpu_percent": round(self.proc.cpu_percent(None), 1),
        }


def build_zone_state(zone: dict, people_in_view: int, confs: list[float],
                     frames: int, window_s: float, inference_ms: float,
                     source_info: dict, telemetry: dict) -> dict:
    """confs: every detection confidence seen in the last window."""
    return {
        "zone_id": zone["id"],
        "name": zone["name"],
        "role": zone["role"],
        "people_in_view": people_in_view,
        "capacity": zone["capacity"],
        "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        "low_confidence_share":
            round(sum(c < LOW_CONF for c in confs) / len(confs), 3) if confs else 0.0,
        "fps": round(frames / window_s, 1) if window_s > 0 else 0.0,
        "inference_ms": round(inference_ms, 1),
        "source_type": source_info.get("type"),
        "source": source_info,
        "host": telemetry,
        "last_update": time.time(),
        "status": "ok",
    }
