"""MEVA/MEVID journey analysis from annotations only (no video, no model).

phase1  footage/meva/analysis/cameras.csv, adjacency.csv, mevid_school_tracklets.csv
phase2  footage/meva/analysis/g420_door_events.csv + feasibility summary

Sources:
- KF1 metadata (camera list, site map) and Kitware KRTD camera models
  (outdoor cameras only; G299/G330 are not in the site coordinate frame and
  the other indoor cameras have no model).
- MEVID annotation data: identity, outfit, camera and tracklet length per
  tracklet. It carries NO date, clip or timestamp, so it cannot place a
  tracklet in time.
- KF1 activity annotations (Kitware), for door enter/exit events.

Usage: .venv/bin/python scripts/meva_journeys.py phase1|phase2
"""
import csv
import collections
import glob
import itertools
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "footage" / "meva" / "metadata"
MEVID = ROOT / "footage" / "meva" / "mevid" / "mevid-v1-annotation-data"
OUT = ROOT / "footage" / "meva" / "analysis"
TARGET = ["G420", "G423", "G421", "G299", "G336"]
SCHOOL = ["G299", "G300", "G328", "G330", "G336", "G339", "G419", "G420", "G421", "G423",
          "G424", "G474", "G638", "G639"]
LOCATION = {  # KF1 site map "visible locations" labels
    "G299": "gym", "G330": "gym", "G421": "cafe", "G419": "doors", "G420": "doors",
    "G423": "hall", "G300": "north (exterior)", "G639": "north (exterior)",
    "G638": "plaza", "G336": "road 3 / circle (also road 1-2, bus lot, parking 1)",
    "G474": "same view as G336 (IR)", "G424": "parking 2-3, road 1-2, parking 1",
    "G328": "parking 3, carport", "G339": "patrol: carport, parking 1-2, road 1-3"}

# Physical adjacency between school cameras. relation:
#   overlap   - the two views share floor area (same room / same outdoor area)
#   adjacent  - a person can walk directly from one view to the other
#   uncovered - connected only through ground no listed camera covers
# basis: site_map (KF1 site map PDF, approximate), krtd (measured camera
# positions), frames (what the camera images show). Confidence is ours.
ADJ = [
    ("G419", "G420", "overlap", "site_map", "high", "both listed under 'doors'"),
    ("G299", "G330", "overlap", "site_map", "high", "both listed under 'gym'; same court from opposite ends"),
    ("G420", "G423", "adjacent", "site_map", "medium", "'hall' box directly beside 'doors' box"),
    ("G419", "G423", "adjacent", "site_map", "medium", "as G420"),
    ("G420", "G299", "adjacent", "site_map", "low", "'doors' box touches 'gym' box; connecting route not shown"),
    ("G419", "G299", "adjacent", "site_map", "low", "as G420"),
    ("G421", "G299", "adjacent", "site_map", "low", "'cafe' box directly beside 'gym' box; door not shown"),
    ("G420", "G300", "adjacent", "site_map,frames", "medium", "G420 shows exterior double doors; 'north' strip is outside them"),
    ("G420", "G639", "adjacent", "site_map,frames", "medium", "as G300"),
    ("G300", "G639", "overlap", "site_map,krtd", "high", "both listed under 'north'"),
    ("G421", "G638", "adjacent", "site_map,frames", "low", "cafe glass doors lead toward the plaza"),
    ("G638", "G336", "adjacent", "site_map,krtd", "medium", "cameras mounted together at the plaza corner"),
    ("G336", "G474", "overlap", "metadata", "high", "EO/IR pair, same view"),
    ("G336", "G424", "overlap", "site_map", "medium", "both cover road 1-2 and parking 1"),
    ("G424", "G328", "overlap", "site_map,krtd", "medium", "both cover parking 3"),
    ("G339", "G328", "overlap", "site_map", "medium", "both cover the carport"),
    ("G339", "G424", "overlap", "site_map", "medium", "both cover parking 2"),
    ("G639", "G328", "adjacent", "site_map,krtd", "low", "north strip continues toward parking 3"),
    ("G420", "G336", "uncovered", "site_map", "low", "out through the doors, round the building to the circle; gap not covered"),
    ("G421", "G336", "uncovered", "site_map", "low", "via the plaza (G638) if the cafe doors are used"),
]


def krtd_positions() -> dict:
    pos = collections.defaultdict(list)
    for p in glob.glob(str(META / "krtd" / "*.school.*.krtd")):
        v = [float(x) for x in open(p).read().split()]
        R, T = np.array(v[9:18]).reshape(3, 3), np.array(v[18:21])
        cam = re.search(r"(G\d+)\.krtd", p)[1]
        if cam not in ("G299", "G330"):  # not in the site ENU frame
            pos[cam].append(-R.T @ T)
    return {c: np.mean(v, axis=0) for c, v in pos.items()}


def mevid_rows() -> list[dict]:
    rows = []
    for split in ("train", "test"):
        info = np.loadtxt(MEVID / f"track_{split}_info.txt").astype(int)
        names = open(MEVID / f"{split}_name.txt").read().split()
        for i, (s, e, pid, outfit, cam) in enumerate(info):
            m = re.match(r"(\d{4})O(\d{3})C(\d{3})T(\d{3})F", names[s])
            rows.append({"split": split, "identity": pid, "outfit": outfit, "camera": f"G{cam}",
                         "tracklet": int(m[4]) if m else "", "chips": e - s + 1,
                         "date": "", "start": "", "end": ""})
    return rows


def phase1() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    flags = {}
    for r in csv.DictReader(open(META / "meva-kf1-metadata" / "meva-kf1-cameras.csv")):
        flags[f"G{r['Camera ID'].strip()}"] = (r["interior / exterior"].strip(), r["EO/IR"].strip(),
                                                r["notes"].strip())
    pos = krtd_positions()
    tracks = mevid_rows()
    per_cam = collections.Counter(t["camera"] for t in tracks)
    ids_cam = collections.defaultdict(set)
    for t in tracks:
        ids_cam[t["camera"]].add(t["identity"])

    with open(OUT / "cameras.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["camera", "indoor_outdoor", "eo_ir", "site_map_location", "enu_east_m",
                    "enu_north_m", "mevid_tracklets", "mevid_identities", "kf1_notes"])
        for c in SCHOOL:
            io, eo, note = flags.get(c, ("", "", ""))
            p = pos.get(c)
            w.writerow([c, {"int": "indoor", "ext": "outdoor"}.get(io, io), eo, LOCATION.get(c, ""),
                        f"{p[0]:.1f}" if p is not None else "", f"{p[1]:.1f}" if p is not None else "",
                        per_cam[c], len(ids_cam[c]), note])

    with open(OUT / "adjacency.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["camera_a", "camera_b", "relation", "basis", "confidence", "camera_distance_m",
                    "both_in_target_set", "evidence"])
        for a, b, rel, basis, conf, ev in ADJ:
            d = (f"{np.linalg.norm(pos[a][:2] - pos[b][:2]):.1f}"
                 if a in pos and b in pos else "")
            w.writerow([a, b, rel, basis, conf, d, a in TARGET and b in TARGET, ev])

    with open(OUT / "mevid_school_tracklets.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tracks[0]))
        w.writeheader()
        w.writerows(t for t in tracks if t["camera"] in SCHOOL)

    print(f"cameras.csv: {len(SCHOOL)} school cameras")
    print(f"adjacency.csv: {len(ADJ)} pairs "
          f"({sum(1 for a in ADJ if a[0] in TARGET and a[1] in TARGET)} within the five target cameras)")
    n = sum(1 for t in tracks if t["camera"] in SCHOOL)
    print(f"mevid_school_tracklets.csv: {n} tracklets; date/start/end are empty: "
          "MEVID annotations carry no time information")


# ---------------------------------------------------------------- phase 2
GITLAB = "https://gitlab.kitware.com/api/v4/projects/meva%2Fmeva-data-repo/repository/tree"
RAW = "https://gitlab.kitware.com/meva/meva-data-repo/-/raw/master/annotation/DIVA-phase-2/MEVA"
DOOR = ("person_enters_scene_through_structure", "person_exits_scene_through_structure")


def g420_clips() -> list[tuple[str, str]]:
    """(annotation set, path/base) for every annotated G420 clip in both Kitware sets."""
    cache = OUT / "g420_annotated_clips.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = []
    for s in ("kitware", "kitware-meva-training"):
        base = f"annotation%2FDIVA-phase-2%2FMEVA%2F{s}"
        for date in json.loads(urllib.request.urlopen(f"{GITLAB}?path={base}&per_page=100").read()):
            if date["type"] != "tree":
                continue
            for hour in json.loads(urllib.request.urlopen(
                    f"{GITLAB}?path={base}%2F{date['name']}&per_page=100").read()):
                files = json.loads(urllib.request.urlopen(
                    f"{GITLAB}?path={base}%2F{date['name']}%2F{hour['name']}&per_page=100").read())
                for x in files:
                    if ".G420." in x["name"] and x["name"].endswith(".activities.yml"):
                        out.append((s, f"{date['name']}/{hour['name']}/{x['name']}"))
    cache.write_text(json.dumps(out))
    return out


def phase2() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clips = g420_clips()
    rows, per_clip = [], []
    for s, path in clips:
        local = ROOT / "footage" / "meva" / "annotations" / s / Path(path).name
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(urllib.request.urlopen(f"{RAW}/{s}/{path}", timeout=60).read())
        counts = collections.Counter()
        for line in open(local):
            m = re.search(r"'act2': \{'(\w+)'.*?'timespan': \[\{'tsr0': \[(\d+), (\d+)\]", line)
            if not m:
                continue
            counts[m[1]] += 1
            if m[1] in DOOR:
                rows.append({"set": s, "clip": Path(path).name.replace(".activities.yml", ""),
                             "event": "enter" if "enters" in m[1] else "exit",
                             "start_frame": int(m[2]), "end_frame": int(m[3])})
        per_clip.append((Path(path).name, counts["person_enters_scene_through_structure"],
                         counts["person_exits_scene_through_structure"], sum(counts.values())))
    with open(OUT / "g420_door_events.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["set", "clip", "event", "start_frame", "end_frame"])
        w.writeheader()
        w.writerows(rows)
    enters = sum(r["event"] == "enter" for r in rows)
    exits = len(rows) - enters
    with_events = sum(1 for c in per_clip if c[1] or c[2])
    print(f"G420 annotated clips: {len(clips)}; clips with door events: {with_events}")
    print(f"door events: {enters} enter, {exits} exit (g420_door_events.csv)")
    for name, e, x, total in per_clip[:12]:
        print(f"  {name[:40]}  enter {e:3d}  exit {x:3d}  (all activities {total})")


if __name__ == "__main__":
    {"phase1": phase1, "phase2": phase2}[sys.argv[1]]()
