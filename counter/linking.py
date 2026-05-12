"""Cross-zone linking: give each track a person, without faces or names.

The linker keeps a list of people, each with appearance profiles (vectors from
counter.appearance), where and when they were last seen, whether they are in
view right now, and a log of their sightings. When a track is decided it is
matched against people who are not in view anywhere and were last seen:
  - in the same or a neighbouring zone (layout paths) within `window_s`, or
  - anywhere within `long_window_s`, with the stricter `long_min_sim`
    (people walk through areas without cameras).
No match good enough: a new person.

OnlineLinker is used live by the hub; assign_people runs the same logic over
recorded tracks for scripts/eval_tracking.py. No I/O here.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class LinkParams:
    method: str = "appearance"   # "timing" | "appearance"
    window_s: float = 30.0       # longest walk between neighbouring zones
    min_sim: float = 0.7         # appearance: below this, not the same person
    long_window_s: float = 600.0
    long_min_sim: float = 0.6
    margin: float = 0.05         # best vs second-best similarity: closer = uncertain
    gallery: bool = True         # match against each past track profile (max), not their mean
    min_vectors: int = 2         # tracks with fewer vectors don't update a person's profile


@dataclass
class Person:
    pid: int
    zone: str
    last_end: float
    profile: np.ndarray | None = None
    weight: int = 0
    active: int = 0              # tracks of this person in view right now
    gallery: list = field(default_factory=list)  # past track profiles, most recent last
    log: list = field(default_factory=list)      # one entry per sighting (track)

    def similarity(self, v: np.ndarray | None, use_gallery: bool) -> float:
        if v is None or self.profile is None:
            return 0.0
        if use_gallery and self.gallery:
            return max(float(np.dot(v, g)) for g in self.gallery)
        return float(np.dot(v, self.profile))

    def absorb(self, v: np.ndarray | None, n: int = 1) -> None:
        if v is None:
            return
        self.gallery = self.gallery[-19:] + [v]
        if self.profile is None:
            self.profile, self.weight = v, n
            return
        m = self.profile * self.weight + v * n
        self.profile = m / max(float(np.linalg.norm(m)), 1e-9)
        self.weight += n


class OnlineLinker:
    def __init__(self, neighbours: dict[str, set[str]], p: LinkParams | None = None):
        self.neighbours = neighbours
        self.p = p or LinkParams()
        self.people: dict[int, Person] = {}
        self.owner: dict[str, Person] = {}      # track key -> person
        self._uncertain: dict[str, bool] = {}
        self._next = 1

    def decide(self, key: str, zone: str, start: float, early: np.ndarray | None) -> dict:
        """A track is old enough to be given a person. Returns the decision."""
        p = self.p
        near = self.neighbours.get(zone, set()) | {zone}
        cands = []
        for q in self.people.values():
            gap = start - q.last_end
            if q.active or (q.zone == zone and gap < 0) or gap < -1.0:
                continue  # in view somewhere else when this track started
            if q.zone in near and gap <= p.window_s:
                need = p.min_sim
            elif gap <= p.long_window_s:
                need = p.long_min_sim
            else:
                continue
            cands.append((q.similarity(early, p.gallery), need, gap, q))
        best, uncertain = None, False
        if p.method == "timing":
            local = [c for c in cands if c[3].zone in near and c[2] <= p.window_s]
            if local:
                best = min(local, key=lambda c: c[2])
                uncertain = len(local) > 1
        else:
            ok = sorted((c for c in cands if c[0] >= c[1]), key=lambda c: -c[0])
            if ok:
                best = ok[0]
                uncertain = len(ok) > 1 and ok[0][0] - ok[1][0] < p.margin
        if best:
            q = best[3]
            d = {"key": key, "person": q.pid, "new": False, "uncertain": uncertain,
                 "sim": round(best[0], 3), "gap": round(best[2], 1), "from_zone": q.zone,
                 "candidates": len(cands)}
        else:
            q = Person(self._next, zone, start)
            self._next += 1
            self.people[q.pid] = q
            q.absorb(early)  # a new person needs a profile to be found again
            d = {"key": key, "person": q.pid, "new": True, "uncertain": False, "sim": None,
                 "gap": None, "from_zone": None, "candidates": len(cands)}
        q.active += 1
        q.zone = zone
        q.log.append({"track": key, "zone": zone, "start": start, "end": None,
                      "from_zone": d["from_zone"], "gap": d["gap"], "sim": d["sim"],
                      "uncertain": uncertain, "new": d["new"]})
        self.owner[key] = q
        self._uncertain[key] = uncertain
        return d

    def end(self, key: str, end: float, full: np.ndarray | None, n_vectors: int) -> None:
        q = self.owner.get(key)
        if q is None:
            return
        q.active = max(0, q.active - 1)
        q.last_end = max(q.last_end, end)
        for e in reversed(q.log):
            if e["track"] == key:
                e["end"] = end
                q.zone = e["zone"]
                break
        if n_vectors >= self.p.min_vectors and not self._uncertain.get(key):
            q.absorb(full)

    def forget_before(self, t: float) -> None:
        """Retention: drop people not seen since t (and their logs)."""
        gone = [pid for pid, q in self.people.items() if not q.active and q.last_end < t]
        for pid in gone:
            q = self.people.pop(pid)
            for e in q.log:
                self.owner.pop(e["track"], None)
                self._uncertain.pop(e["track"], None)


def assign_people(tracks: list[dict], neighbours: dict[str, set[str]],
                  p: LinkParams) -> list[dict]:
    """Offline: run OnlineLinker over recorded tracks, deciding each at its start
    with its "early" profile. tracks: {"key", "zone", "start", "end", "early",
    "full", "vecs"}. Returns one decision per track, in start order."""
    link = OnlineLinker(neighbours, p)
    events = [(t["start"], 1, t) for t in tracks] + [(t["end"], 0, t) for t in tracks]
    events.sort(key=lambda e: (e[0], e[1]))  # ends before starts at the same moment
    out = []
    for _, is_start, t in events:
        if is_start:
            out.append(link.decide(t["key"], t["zone"], t["start"], t["early"]))
        else:
            link.end(t["key"], t["end"], t["full"], len(t.get("vecs", ())))
    return out
