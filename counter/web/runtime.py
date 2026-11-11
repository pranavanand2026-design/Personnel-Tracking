"""Go live: turn the saved layout into the runtime config and run the workers.

data/runtime_config.json replaces the old hand-written zones.yaml. The zone
workers are started from that file, never from hard-coded site details.
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from counter.sources.demo_registry import FEEDS
from counter.web import db
from counter.zone_worker import Supervisor

RUNTIME_CONFIG = db.DB_PATH.parent / "runtime_config.json"


def source_block(cam: dict, epoch: float) -> dict:
    kind, src = cam["source_type"], cam["source"]
    if kind == "demo":
        return {"type": "demo", "feed": src, "epoch": epoch}
    if kind == "file":
        return {"type": "file", "path": src}
    if kind == "rtsp":
        return {"type": "rtsp", "url": src}
    raise ValueError(f"Camera {cam['id']} has no source")


def build_config() -> dict:
    org = db.get_org()
    roles = {r["key"]: r for r in db.get_roles()}
    cams = {c["id"]: c for c in db.get_cameras()}
    layout = db.get_layout()
    epoch = time.time()  # shared demo clock: every demo camera plays from here
    zones = []
    for z in layout["zones"]:
        cam = cams[z["camera_id"]]
        zones.append({
            "id": z["id"], "name": z["name"], "role": z["role"],
            "behaviour": roles[z["role"]]["behaviour"], "capacity": z["capacity"],
            "camera_id": cam["id"], "camera_name": cam["name"],
            "offline": bool(cam["offline"]),
            "source": source_block(cam, epoch),
            # long views need a sharper detector for distant people
            "detect_size": FEEDS.get(cam["source"], {}).get("detect_size", 640)
            if cam["source_type"] == "demo" else 640,
        })
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "organisation": org["name"], "site": org["site_name"],
        "demo_epoch": epoch,
        "zones": zones,
        "paths": layout["paths"],
    }


class Runtime:
    """Holds the running Supervisor (if live)."""

    def __init__(self):
        self.sup: Supervisor | None = None
        self.config: dict | None = None
        self._lock = threading.Lock()

    @property
    def live(self) -> bool:
        return self.sup is not None

    def go_live(self) -> dict:
        config = build_config()
        RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_CONFIG.write_text(json.dumps(config, indent=2))
        self.start_from_file()
        db.update_org(live=1, live_since=config["generated_at"])
        return config

    def start_from_file(self) -> None:
        config = json.loads(Path(RUNTIME_CONFIG).read_text())
        with self._lock:
            if self.sup:
                self.sup.stop()
            self.sup = Supervisor(config["zones"], config.get("paths", []))
            self.config = config
            self.sup.start()

    def stop(self) -> None:
        with self._lock:
            if self.sup:
                self.sup.stop()
            self.sup, self.config = None, None
        db.update_org(live=0)

    def set_camera_offline(self, cam_id: str, offline: bool) -> None:
        """Apply a camera's Offline toggle to the running zone, if any."""
        with self._lock:
            if not self.sup:
                return
            for z in self.sup.zones.values():
                if z["camera_id"] == cam_id:
                    (self.sup.stop_zone if offline else self.sup.start_zone)(z["id"])

    def states(self) -> list[dict]:
        return self.sup.hub.states() if self.sup else []

    def people(self) -> dict:
        return self.sup.hub.people_by_zone() if self.sup else {}

    def person(self, name: str) -> dict | None:
        return self.sup.hub.person(name) if self.sup else None
