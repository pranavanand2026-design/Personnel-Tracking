"""Per-zone tracking for the live workers: YOLO11n + BoT-SORT, appearance
profiles per track, and the track events the hub links into people.

Events (dicts sent through the worker's Publisher, alongside ZoneStates):
  track_decide: a track is DECIDE_S old (or ended sooner): its early profile
  track_end:    a track has not been seen for LOST_S: its full profile
Crops are encoded and dropped; only vectors leave the worker.
"""
import time
from pathlib import Path

import numpy as np

from counter.appearance import AppearanceEncoder, profile, usable
from counter.detector import MODEL_PATH, PERSON, pick_device

TRACKER_CFG = Path(__file__).resolve().parent / "trackers" / "botsort_static.yaml"
DECIDE_S = 5.0       # matches scripts/eval_tracking.py: better than deciding at 3 s
LOST_S = 1.0         # not seen this long: the track has ended
MIN_TRACK_S = 0.5    # shorter tracks are flicker: never linked
EARLY_S = 2.0        # sample appearance every 0.5 s while a track is this young, then 1 s


class PersonTracker:
    """Persistent BoT-SORT IDs across calls. reset() starts fresh IDs."""

    def __init__(self, imgsz: int = 640, device: str | None = None):
        from ultralytics import YOLO
        self.model = YOLO(str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt")
        self.imgsz = imgsz
        self.device = device or pick_device()
        self.last_ms = 0.0

    def track(self, frame: np.ndarray) -> list[tuple[int, float, float, float, float, float]]:
        """(track id, x1, y1, x2, y2, conf) for each person in view."""
        t = time.perf_counter()
        r = self.model.track(frame, persist=True, tracker=str(TRACKER_CFG), classes=[PERSON],
                             imgsz=self.imgsz, device=self.device, verbose=False)[0]
        self.last_ms = (time.perf_counter() - t) * 1000
        b = r.boxes
        if b is None or b.id is None:
            return []
        return [(int(i), *map(float, xyxy), float(c))
                for i, xyxy, c in zip(b.id.int().tolist(), b.xyxy.cpu().tolist(), b.conf.cpu().tolist())]

    def reset(self) -> None:
        pred = getattr(self.model, "predictor", None)
        for tr in getattr(pred, "trackers", None) or []:
            tr.reset()


class TrackBook:
    """Bookkeeping for one zone's tracks: appearance sampling and events."""

    def __init__(self, zone_id: str, encoder: AppearanceEncoder | None = None):
        self.zone_id = zone_id
        self.enc = encoder or AppearanceEncoder()
        self.tracks: dict[int, dict] = {}
        # bumps on reset; seeded from the clock so a restarted worker never reuses keys
        self.run = int(time.time())

    def key(self, tid: int) -> str:
        return f"{self.zone_id}:{self.run}:{tid}"

    def update(self, frame: np.ndarray, rows: list, now: float) -> list[dict]:
        """Feed one frame's tracks; returns events to publish."""
        h, w = frame.shape[:2]
        want = []
        for tid, x1, y1, x2, y2, _ in rows:
            t = self.tracks.setdefault(tid, {"start": now, "vecs": [], "last_vec": -1e9,
                                             "decided": False})
            t["last"] = now
            every = 0.5 if now - t["start"] < EARLY_S else 1.0
            box = (x1, y1, x2, y2)
            if now - t["last_vec"] >= every and usable(box, w, h):
                want.append((tid, box))
                t["last_vec"] = now
        if want:
            for (tid, _), v in zip(want, self.enc.encode(frame, [b for _, b in want])):
                self.tracks[tid]["vecs"].append(v)
        events = []
        for tid, t in list(self.tracks.items()):
            if not t["decided"] and now - t["start"] >= DECIDE_S:
                events.append(self._decide(tid, t))
            if now - t["last"] >= LOST_S:
                events += self._end(tid, t)
        return events

    def end_all(self) -> list[dict]:
        """Recording looped or worker stopping: every track ends now."""
        events = []
        for tid, t in list(self.tracks.items()):
            events += self._end(tid, t)
        self.run += 1
        return events

    def _decide(self, tid: int, t: dict) -> dict:
        t["decided"] = True
        early = profile(t["vecs"])
        return {"event": "track_decide", "zone_id": self.zone_id, "key": self.key(tid),
                "track_id": tid, "start": t["start"],
                "profile": None if early is None else early.tolist()}

    def _end(self, tid: int, t: dict) -> list[dict]:
        del self.tracks[tid]
        if t["last"] - t["start"] < MIN_TRACK_S:
            return []
        out = [] if t["decided"] else [self._decide(tid, t)]
        full = profile(t["vecs"])
        out.append({"event": "track_end", "zone_id": self.zone_id, "key": self.key(tid),
                    "end": t["last"], "n_vectors": len(t["vecs"]),
                    "profile": None if full is None else full.tolist()})
        return out
