"""Hub: keeps the latest ZoneState per zone and links track events into people.
Workers reach it via a Publisher.

People are anonymous (P-0001, ...): appearance profiles and sightings in
memory only, forgotten FORGET_AFTER_S after they were last seen.

LocalPublisher  - multiprocessing queue to a hub on the same machine (now).
MqttPublisher   - stub; a Raspberry Pi will publish identical dicts over MQTT.
"""
import json
import queue
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict

import numpy as np

from counter.linking import OnlineLinker

STALE_AFTER_S = 3.0
OFFLINE_AFTER_S = 10.0
FORGET_AFTER_S = 30 * 60   # retention for people and their sightings
LAST_SEEN_S = 10 * 60      # "last seen here" lists people seen in the last 10 minutes


def label(pid: int) -> str:
    return f"P-{pid:04d}"


class Publisher(ABC):
    @abstractmethod
    def publish(self, state: dict) -> None:
        """Send one ZoneState dict to the hub."""


class LocalPublisher(Publisher):
    def __init__(self, q):
        self.q = q  # multiprocessing.Queue shared with the hub

    def publish(self, state: dict) -> None:
        self.q.put(state)


class MqttPublisher(Publisher):
    """Stub. Will publish json.dumps(state) to site/<site>/zone/<zone_id>/state."""

    def __init__(self, broker_host: str, site: str, port: int = 1883):
        self.topic_root = f"site/{site}/zone"
        raise NotImplementedError("MqttPublisher is not implemented yet")

    def publish(self, state: dict) -> None:
        topic = f"{self.topic_root}/{state['zone_id']}/state"
        payload = json.dumps(state)
        raise NotImplementedError(topic, payload)


class Hub:
    def __init__(self, zones: list[dict], paths: list[dict] | None = None):
        self.zones = zones
        self._latest: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._alive = {z["id"]: True for z in zones}
        neighbours = defaultdict(set)
        for p in paths or []:
            neighbours[p["from_zone"]].add(p["to_zone"])
            neighbours[p["to_zone"]].add(p["from_zone"])
        self.linker = OnlineLinker(neighbours)
        self._plock = threading.Lock()
        self._forgot = time.time()
        self.on_label = None  # (zone_id, track key, label) -> None, set by the Supervisor

    def receive(self, state: dict) -> None:
        if "event" in state:
            self._track_event(state)
            return
        with self._lock:
            self._latest[state["zone_id"]] = state

    def _track_event(self, e: dict) -> None:
        v = None if e.get("profile") is None else np.asarray(e["profile"], np.float32)
        with self._plock:
            if e["event"] == "track_decide":
                d = self.linker.decide(e["key"], e["zone_id"], e["start"], v)
                if self.on_label:
                    self.on_label(e["zone_id"], e["key"], label(d["person"]))
            elif e["event"] == "track_end":
                self.linker.end(e["key"], e["end"], v, e.get("n_vectors", 0))
            now = time.time()
            if now - self._forgot > 60:
                self.linker.forget_before(now - FORGET_AFTER_S)
                self._forgot = now

    def people_by_zone(self) -> dict:
        """Per zone: people in view now and people last seen there (not in view anywhere)."""
        now = time.time()
        out = {z["id"]: {"in_view": [], "last_seen": []} for z in self.zones}
        with self._plock:
            for q in self.linker.people.values():
                if q.zone not in out:
                    continue
                if q.active:
                    since = next((e["start"] for e in reversed(q.log) if e["end"] is None), q.last_end)
                    out[q.zone]["in_view"].append({"person": label(q.pid), "since": since})
                elif now - q.last_end <= LAST_SEEN_S:
                    out[q.zone]["last_seen"].append({"person": label(q.pid), "at": q.last_end})
        for v in out.values():
            v["in_view"].sort(key=lambda x: x["since"])
            v["last_seen"].sort(key=lambda x: -x["at"])
        return out

    def person(self, name: str) -> dict | None:
        """One person's sightings, oldest first, and last known location."""
        try:
            pid = int(name.removeprefix("P-"))
        except ValueError:
            return None
        names = {z["id"]: z["name"] for z in self.zones}
        with self._plock:
            q = self.linker.people.get(pid)
            if q is None:
                return None
            log = [{**{k: e[k] for k in ("start", "end", "gap", "sim", "uncertain", "new")},
                    "zone": names.get(e["zone"], e["zone"]),
                    "from_zone": names.get(e["from_zone"]) if e["from_zone"] else None}
                   for e in q.log]
            return {"person": label(pid), "in_view": bool(q.active),
                    "zone": names.get(q.zone, q.zone), "last_seen": q.last_end, "log": log}

    def set_alive(self, zone_id: str, alive: bool) -> None:
        self._alive[zone_id] = alive

    def drain_local(self, q, stop: threading.Event) -> None:
        """Thread target: move states from a LocalPublisher queue into the hub."""
        while not stop.is_set():
            try:
                self.receive(q.get(timeout=0.5))
            except queue.Empty:
                pass

    def states(self) -> list[dict]:
        """Latest state per configured zone, with status from message age."""
        now = time.time()
        out = []
        with self._lock:
            for z in self.zones:
                s = dict(self._latest.get(z["id"]) or {
                    "zone_id": z["id"], "name": z["name"], "role": z["role"],
                    "capacity": z["capacity"], "people_in_view": None,
                    "last_update": None,
                })
                age = now - s["last_update"] if s["last_update"] else None
                if s.get("error") or age is None or age > OFFLINE_AFTER_S \
                        or not self._alive[z["id"]]:
                    s["status"] = "offline"
                elif age > STALE_AFTER_S:
                    s["status"] = "stale"
                else:
                    s["status"] = "ok"
                s["age_s"] = round(age, 1) if age is not None else None
                out.append(s)
        return out
