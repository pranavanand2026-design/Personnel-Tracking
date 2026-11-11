"""Score per-zone tracking and cross-zone linking against SmartSpaces ground truth.

Reads the output of scripts/record_zone_tracks.py and the scene's ground truth
(same person ID in every camera). Reports:
  1. Live count per zone: tracked people vs ground truth, every sampled frame.
  2. Tracking within each zone: how often one person's visit is split into
     several track IDs (fragments) and how pure each track is.
  3. Linking across zones: timing only vs appearance vs combined, over a sweep
     of thresholds; precision, recall and decision accuracy; moves between zones followed.
Writes output/eval/tracking/report.md and summary.json.

Usage: .venv/bin/python scripts/eval_tracking.py [output/eval/tracking-reid]
"""
import collections
import gzip
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from counter.appearance import profile  # noqa: E402
from counter.linking import LinkParams, assign_people  # noqa: E402
from counter.sources.demo_registry import DEMO_DIR, DEMO_FEEDS, FEEDS  # noqa: E402
from counter.web.demo import PATHS, ZONES  # noqa: E402

TRK = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output" / "eval" / "tracking"
IOU = 0.5
DECIDE_S = (3.0, 5.0, None)  # link decided this long after a track starts (None: when it ends)
MIN_TRACK_S = 0.5      # shorter tracks are flicker; not linked
VISIT_GAP_S = 2.0      # ground truth: a person out of view longer than this starts a new visit
SMALL_PX = 40          # ground-truth people shorter than this (at 720p) are hard to see


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def load_gt(cams: set[int], scale: float) -> dict:
    gt = collections.defaultdict(lambda: collections.defaultdict(list))  # cam -> frame -> [(pid, box)]
    for line in open(DEMO_DIR / "ground_truth.txt"):
        c, p, f, x, y, w, h = line.split()[:7]
        c = int(c)
        if c in cams:
            x, y, w, h = (float(v) * scale for v in (x, y, w, h))
            gt[c][int(f)].append((int(p), (x, y, x + w, y + h)))
    return gt


def load_tracks(feed_id: str):
    with gzip.open(TRK / f"{feed_id}.tracks.jsonl.gz", "rt") as fh:
        header = json.loads(fh.readline())
        frames = {}
        for line in fh:
            r = json.loads(line)
            frames[r["f"]] = r["t"]
    v = np.load(TRK / f"{feed_id}.vectors.npz")
    return header, frames, v


def match(rows, gts):
    """Track id -> ground-truth person id for one frame (Hungarian on IoU)."""
    if not rows or not gts:
        return {}
    a = np.array([r[1:5] for r in rows]); b = np.array([g[1] for g in gts])
    m = iou_matrix(a, b)
    ri, ci = linear_sum_assignment(-m)
    return {rows[i][0]: gts[j][0] for i, j in zip(ri, ci) if m[i, j] >= IOU}


def pct(x, n):
    return round(100 * x / n, 1) if n else None


def main() -> None:
    feeds = [f for f in DEMO_FEEDS if (TRK / f"{f['id']}.tracks.jsonl.gz").exists()]
    cam_of = {f["id"]: int(f["camera"]) for f in feeds}
    data = {f["id"]: load_tracks(f["id"]) for f in feeds}
    size = data[feeds[0]["id"]][0]["size"]
    gt = load_gt(set(cam_of.values()), size[0] / 1920)
    fps = data[feeds[0]["id"]][0]["fps"]

    # Frame numbering check: which offset lines ground truth up with our boxes
    fid = feeds[0]["id"]; frames = data[fid][1]
    sample = sorted(frames)[::50]
    offset = max((-2, -1, 0, 1, 2), key=lambda o: sum(len(match(frames[f], gt[cam_of[fid]].get(f + o, [])))
                                                   for f in sample))

    summary = {"offset": offset, "zones": {}, "linking": {}}
    tracks_all, track_gt = [], {}
    obs_all = collections.defaultdict(list)            # pid -> [(frame, feed, track id)], all zones
    for feed in feeds:
        fid, cam = feed["id"], cam_of[feed["id"]]
        _, frames, vec = data[fid]
        g = gt[cam]
        # 1. counts
        err, err_vis = [], []
        votes = collections.defaultdict(collections.Counter)
        seen = collections.defaultdict(list)            # pid -> [(frame, track id)]
        for f, rows in frames.items():
            gts = g.get(f + offset, [])
            err.append(len(rows) - len(gts))
            err_vis.append(len(rows) - sum(1 for _, b in gts if b[3] - b[1] >= SMALL_PX))
            m = match(rows, gts)
            for r in rows:
                votes[r[0]][m.get(r[0])] += 1
            for tid, pid in m.items():
                seen[pid].append((f, tid)); obs_all[pid].append((f, fid, tid))
        e = np.array(err); ev = np.array(err_vis)
        gt_n = np.array([len(g.get(f + offset, [])) for f in frames])
        zone = next(z for z in ZONES if z["camera_id"] == fid)["name"]
        z = {"zone": zone, "camera": cam, "frames": len(frames),
             "mean_people_gt": round(float(gt_n.mean()), 2),
             "count_exact_pct": pct(int((e == 0).sum()), len(e)),
             "count_within1_pct": pct(int((abs(e) <= 1).sum()), len(e)),
             "count_mae": round(float(abs(e).mean()), 2), "count_bias": round(float(e.mean()), 2),
             "count_mae_vs_visible": round(float(abs(ev).mean()), 2)}
        # 2. tracking within the zone
        for tid, c in votes.items():
            pid, n = c.most_common(1)[0]
            track_gt[f"{fid}:{tid}"] = pid if pid is not None and n >= 0.5 * sum(c.values()) else None
        visits = frag = 0
        for pid, obs in seen.items():
            obs.sort()
            cur = set(); last = None
            for f, tid in obs:
                if last is not None and (f - last) / fps > VISIT_GAP_S:
                    visits += 1; frag += len(cur) - 1; cur = set()
                cur.add(tid); last = f
            visits += 1; frag += len(cur) - 1
        purity = [c.most_common(1)[0][1] / sum(c.values()) for c in votes.values()]
        z.update({"track_ids": len(votes), "gt_people_seen": len(seen), "gt_visits": visits,
                  "extra_ids_per_visit": round(frag / visits, 2) if visits else None,
                  "track_purity_pct": round(100 * float(np.mean(purity)), 1)})
        summary["zones"][fid] = z
        # tracks for linking
        span = collections.defaultdict(list)
        for f, rows in frames.items():
            for r in rows:
                span[r[0]].append(f)
        by_id = collections.defaultdict(list)
        for i, f, v in zip(vec["id"], vec["f"], vec["v"].astype(np.float32)):
            by_id[int(i)].append((int(f), v))
        for tid, fs in span.items():
            start, end = min(fs) / fps, max(fs) / fps
            if end - start < MIN_TRACK_S:
                continue
            vs = [(f / fps, v) for f, v in by_id.get(tid, [])]
            tracks_all.append({"key": f"{fid}:{tid}", "zone": fid, "start": start, "end": end,
                               "vecs": vs, "full": profile([v for _, v in vs])})

    # 3. linking
    zone_feed = {z["id"]: z["camera_id"] for z in ZONES}
    neighbours = collections.defaultdict(set)
    for a, b in PATHS:
        neighbours[zone_feed[a]].add(zone_feed[b]); neighbours[zone_feed[b]].add(zone_feed[a])
    by_key = {t["key"]: t for t in tracks_all}

    no_vec = sum(1 for t in tracks_all if not t["vecs"])

    def score(p: LinkParams, decide_s: float | None) -> dict:
        for t in tracks_all:
            t["early"] = t["full"] if decide_s is None else profile(
                [v for when, v in t["vecs"] if when <= t["start"] + decide_s])
        dec = assign_people(tracks_all, neighbours, p)
        person_of = {d["key"]: d["person"] for d in dec}
        dur = {t["key"]: t["end"] - t["start"] for t in tracks_all}
        known = collections.defaultdict(collections.Counter)   # person -> truth -> seconds, so far
        seen_truth = set()
        links = right = splits = unc = unc_right = cross = cross_right = 0
        for d in dec:
            g = track_gt.get(d["key"])
            if not d["new"]:
                links += 1
                ok = g is not None and known[d["person"]] and known[d["person"]].most_common(1)[0][0] == g
                right += ok
                unc += d["uncertain"]; unc_right += d["uncertain"] and ok
                if d["from_zone"] != by_key[d["key"]]["zone"]:
                    cross += 1; cross_right += ok
            elif g is not None and g in seen_truth:
                splits += 1  # a real person already known was made a new person
            if g is not None:
                seen_truth.add(g)
            known[d["person"]][g] += dur[d["key"]]
        # identity consistency over time (track level)
        by_truth = collections.defaultdict(collections.Counter)
        for k, pr in person_of.items():
            if track_gt.get(k) is not None:
                by_truth[track_gt[k]][pr] += dur[k]
        tot = sum(sum(c.values()) for c in by_truth.values())
        kept = sum(c.most_common(1)[0][1] for c in by_truth.values())
        pure = sum(c.most_common(1)[0][1] for c in known.values() if c)
        alltime = sum(sum(c.values()) for c in known.values())
        # moves followed: real walks between zones where both tracks got the same person
        moved = followed = 0
        for pid, obs in obs_all.items():
            obs.sort()
            for (f1, z1, t1), (f2, z2, t2) in zip(obs, obs[1:]):
                a, b = f"{z1}:{t1}", f"{z2}:{t2}"
                if z1 != z2 and (f2 - f1) / fps <= p.window_s and a in person_of and b in person_of:
                    moved += 1; followed += person_of[a] == person_of[b]
        return {"method": p.method, "decide_s": decide_s, "min_sim": p.min_sim, "long_min_sim": p.long_min_sim,
                "decisions": len(dec), "links": links, "precision_pct": pct(right, links),
                "cross_zone_links": cross, "cross_zone_precision_pct": pct(cross_right, cross),
                "splits": splits, "uncertain_links": unc, "uncertain_right_pct": pct(unc_right, unc),
                "time_under_main_id_pct": pct(kept, tot), "id_purity_pct": pct(pure, alltime),
                "people": len(known), "gt_people": len(obs_all), "moves": moved,
                "moves_followed_pct": pct(followed, moved)}

    runs = [score(LinkParams(method="timing"), None)]
    for d in DECIDE_S:
        for s_ in (0.5, 0.6, 0.7):
            for ls in (0.6, 0.7):
                runs.append(score(LinkParams(min_sim=s_, long_min_sim=ls), d))
    summary["linking"] = runs
    summary["tracks_linked"] = len(tracks_all)
    best = max(runs[1:], key=lambda r: (r["time_under_main_id_pct"] or 0) + (r["id_purity_pct"] or 0))
    summary["best"] = best
    (TRK / "summary.json").write_text(json.dumps(summary, indent=2))

    lines = ["# Zone tracking and cross-zone linking vs SmartSpaces ground truth", "",
             f"Scene 081, {len(feeds)} cameras, YOLO11n + BoT-SORT at {fps / data[fid][0]['step']:.0f} fps, "
             f"1280x720. Appearance: yolo26n-reid. Ground truth gives every person one ID in all "
             f"cameras. Frame offset used: {offset}.", "",
             "## 1. Live count per zone", "",
             "| Zone | Mean people (truth) | Exact | Within ±1 | Mean error | Bias | Mean error vs people ≥40 px |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for z in summary["zones"].values():
        lines.append(f"| {z['zone']} | {z['mean_people_gt']} | {z['count_exact_pct']}% | {z['count_within1_pct']}% | "
                     f"{z['count_mae']} | {z['count_bias']:+} | {z['count_mae_vs_visible']} |")
    lines += ["", "## 2. Tracking within each zone", "",
              "| Zone | Track IDs | People seen | Visits | Extra IDs per visit | Track purity |",
              "|---|---:|---:|---:|---:|---:|"]
    for z in summary["zones"].values():
        lines.append(f"| {z['zone']} | {z['track_ids']} | {z['gt_people_seen']} | {z['gt_visits']} | "
                     f"{z['extra_ids_per_visit']} | {z['track_purity_pct']}% |")
    lines += ["", f"## 3. Linking across zones ({len(tracks_all)} tracks of {MIN_TRACK_S}+ s)", "",
              "| Method | Decided after | Min similarity (nearby / anywhere) | Links | Precision | Cross-zone links | Cross-zone precision | Moves followed | Splits | Time under one ID | ID purity | People |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in runs:
        sims = "–" if r["method"] == "timing" else f"{r['min_sim']} / {r['long_min_sim'] if r['long_min_sim'] <= 1 else 'off'}"
        when = "–" if r["method"] == "timing" else ("track end" if r["decide_s"] is None else f"{r['decide_s']:.0f} s")
        lines.append(f"| {r['method']} | {when} | {sims} | {r['links']} | {r['precision_pct']}% | {r['cross_zone_links']} | "
                     f"{r['cross_zone_precision_pct']}% | {r['moves_followed_pct']}% | {r['splits']} | "
                     f"{r['time_under_main_id_pct']}% | {r['id_purity_pct']}% | {r['people']} |")
    lines += ["", f"{no_vec} of {len(tracks_all)} tracks never had a usable crop (too small or cut off), "
              "so appearance can't link them; they become new people.", "",
              f"Truth: {runs[0]['gt_people']} people, {runs[0]['moves']} walks between zones. "
              "Precision: links that joined the same person. Moves followed: real walks between two zones "
              "where the leaving and arriving tracks got the same person. Splits: a person already known "
              "was made a new person. Time under one ID: of each real person's tracked time, the share "
              "under their main system ID. ID purity: of each system person's time, the share that is "
              "one real person. 'anywhere' = people last seen in any zone up to 10 min ago."]
    (TRK / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
