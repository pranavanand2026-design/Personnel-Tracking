"""Baseline accuracy of the person detector against MEVA annotations.

MEVA annotates only people taking part in labelled activities, not every
person in view (checked visually). So the annotations support:
  - detection RECALL: did YOLO find each annotated person? (IoU >= 0.5)
  - recall by apparent size (distance), camera and confidence threshold
  - DEFINITE UNDERCOUNTS: frames where YOLO counts fewer people than MEVA's
    partial count, which is a lower bound on the true count
They do NOT support precision or count error: unannotated people would show
up as false positives. Those need hand-counted frames.

Statistics use a clip-level bootstrap (frames within a clip are correlated),
reporting 95% percentile confidence intervals.

Steps (both resumable):
  collect  download each annotated clip, sample every N frames, resize to
           1280x720 exactly as the dashboard does, run YOLO11n at a low
           threshold, store GT + all detections per frame, delete the clip
  report   compute statistics at any threshold, write report + charts

Usage:
  .venv/bin/python scripts/eval_meva.py collect [--every 15]
  .venv/bin/python scripts/eval_meva.py report [--conf 0.25]
"""
import argparse
import collections
import json
import random
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from meva_survey import fetch  # noqa: E402

CAMERAS = {"G420": "Entrance", "G423": "Main Corridor", "G421": "Lobby",
           "G336": "Muster Point A", "G299": "Hall", "G339": "Muster Point B"}
HOUR = "2018-03-12/10"
ANN_SETS = ["kitware", "kitware-meva-training"]
GITLAB = "https://gitlab.kitware.com/api/v4/projects/meva%2Fmeva-data-repo/repository/tree"
RAW = "https://gitlab.kitware.com/meva/meva-data-repo/-/raw/master/annotation/DIVA-phase-2/MEVA"
ANN_DIR = ROOT / "footage" / "meva" / "annotations"
OUT = ROOT / "output" / "eval" / "meva_baseline"
FRAMES_DIR = OUT / "frames"
SIZE = (1280, 720)
COLLECT_CONF = 0.05  # store everything; thresholds are applied in the report
IOU_MATCH = 0.5
GT_DEDUP_IOU = 0.8  # MEVA sometimes boxes one person twice (one track per activity)
HEIGHT_BINS = [(0, 50), (50, 100), (100, 200), (200, 10_000)]  # px at 720p
THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7]
BOOT = 2000


# ---------------------------------------------------------------- annotations
def list_annotated() -> list[dict]:
    index = ANN_DIR / "index.json"
    if index.exists():
        return json.loads(index.read_text())
    clips = []
    path = HOUR.replace("/", "%2F")
    for s in ANN_SETS:
        url = f"{GITLAB}?path=annotation%2FDIVA-phase-2%2FMEVA%2F{s}%2F{path}&per_page=100"
        for item in json.loads(urllib.request.urlopen(url, timeout=30).read()):
            name = item["name"]
            if name.endswith(".geom.yml"):
                base = name[: -len(".geom.yml")]
                cam = base.split(".")[-1]
                if cam in CAMERAS:
                    clips.append({"set": s, "base": base, "camera": cam})
    clips.sort(key=lambda c: c["base"])
    ANN_DIR.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(clips, indent=2))
    return clips


def load_gt(clip: dict) -> dict[int, list[tuple]]:
    """frame -> person boxes (x1, y1, x2, y2) in original pixels."""
    d = ANN_DIR / clip["set"]
    d.mkdir(parents=True, exist_ok=True)
    for kind in ("geom", "types"):
        p = d / f"{clip['base']}.{kind}.yml"
        if not p.exists():
            url = f"{RAW}/{clip['set']}/{HOUR}/{clip['base']}.{kind}.yml"
            p.write_bytes(urllib.request.urlopen(url, timeout=60).read())
    types = {}
    for line in open(d / f"{clip['base']}.types.yml"):
        m = re.search(r"'cset3': \{'(\w+)'.*?'id1': (\d+)", line)
        if m:
            types[int(m[2])] = m[1]
    gt = collections.defaultdict(list)
    for line in open(d / f"{clip['base']}.geom.yml"):
        m = re.search(r"'g0': '(\d+) (\d+) (\d+) (\d+)'.*?'id1': (\d+).*?'ts0': (\d+)", line)
        if m and types.get(int(m[5])) == "person":
            gt[int(m[6])].append(tuple(int(m[i]) for i in range(1, 5)))
    return gt


# ---------------------------------------------------------------- collect
def collect(every: int) -> None:
    from counter.detector import PersonDetector
    sys.path.insert(0, str(ROOT / "scripts"))
    from meva_survey import list_bucket

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    clips = list_annotated()
    videos = {Path(r["key"]).name: r for r in list_bucket(False)}
    det = PersonDetector(conf=COLLECT_CONF)
    print(f"{len(clips)} annotated clips; sampling every {every} frames")
    for i, clip in enumerate(clips, 1):
        out = FRAMES_DIR / f"{clip['base']}.json"
        if out.exists():
            print(f"[{i:2d}/{len(clips)}] {clip['base']}: done, skipping")
            continue
        video = videos.get(f"{clip['base']}.r13.avi")
        if not video:
            print(f"[{i:2d}/{len(clips)}] {clip['base']}: video not in bucket listing, skipping")
            continue
        gt = load_gt(clip)
        print(f"[{i:2d}/{len(clips)}] {clip['base']} ({video['size'] / 1e6:.0f} MB) ...",
              end=" ", flush=True)
        frames = []
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.avi"
            fetch(video["key"], src, None)
            cap = cv2.VideoCapture(str(src))
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            sx, sy = SIZE[0] / w, SIZE[1] / h
            f = 0
            while True:
                if f % every:
                    if not cap.grab():
                        break
                    f += 1
                    continue
                ok, img = cap.read()
                if not ok:
                    break
                img = cv2.resize(img, SIZE, interpolation=cv2.INTER_AREA)  # as the dashboard
                dets = det.detect(img)
                frames.append({
                    "f": f,
                    "gt": [[round(x1 * sx, 1), round(y1 * sy, 1), round(x2 * sx, 1), round(y2 * sy, 1)]
                           for x1, y1, x2, y2 in gt.get(f, [])],
                    "det": [[round(d.x1, 1), round(d.y1, 1), round(d.x2, 1), round(d.y2, 1),
                             round(d.conf, 4)] for d in dets],
                })
                f += 1
            cap.release()
        out.write_text(json.dumps({**clip, "source_size": [w, h], "every": every,
                                   "frames": frames}))
        n_gt = sum(len(x["gt"]) for x in frames)
        print(f"{len(frames)} frames, {n_gt} annotated boxes")


# ---------------------------------------------------------------- matching
def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(gt: list, dets: list) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching by IoU (highest first). Returns (gi, di, iou)."""
    pairs = sorted(((iou(g, d), gi, di) for gi, g in enumerate(gt) for di, d in enumerate(dets)),
                   reverse=True)
    used_g, used_d, out = set(), set(), []
    for v, gi, di in pairs:
        if v < IOU_MATCH:
            break
        if gi not in used_g and di not in used_d:
            used_g.add(gi); used_d.add(di); out.append((gi, di, v))
    return out


def dedup(boxes: list) -> list:
    """Merge annotated boxes that overlap >= GT_DEDUP_IOU: the same person under two track IDs."""
    kept = []
    for b in boxes:
        if all(iou(b, k) < GT_DEDUP_IOU for k in kept):
            kept.append(b)
    return kept


def score_clip(clip: dict, conf: float) -> dict:
    """Per-clip tallies at one confidence threshold."""
    t = {"gt": 0, "tp": 0, "bins_gt": [0] * len(HEIGHT_BINS), "bins_tp": [0] * len(HEIGHT_BINS),
         "ious": [], "match_conf": [], "frames_with_gt": 0, "undercount_frames": 0,
         "shortfall": 0, "det_unmatched": 0, "det_total": 0,
         "miss_low_conf": 0, "miss_crowded": 0, "miss_none": 0, "gt_raw": 0}
    for fr in clip["frames"]:
        dets = [d for d in fr["det"] if d[4] >= conf]
        t["det_total"] += len(dets)
        t["gt_raw"] += len(fr["gt"])
        gt = dedup(fr["gt"])
        m = match(gt, dets)
        t["det_unmatched"] += len(dets) - len(m)
        matched = {gi for gi, _, _ in m}
        for gi, g in enumerate(gt):
            if gi not in matched:  # why was this annotated person missed?
                if any(iou(g, d) >= IOU_MATCH for d in dets):
                    t["miss_crowded"] += 1    # a box was there but went to a neighbour
                elif any(iou(g, d) >= IOU_MATCH for d in fr["det"]):
                    t["miss_low_conf"] += 1   # found, but scored under the threshold
                else:
                    t["miss_none"] += 1       # nothing overlapping at any confidence
            hgt = g[3] - g[1]
            b = next(i for i, (lo, hi) in enumerate(HEIGHT_BINS) if lo <= hgt < hi)
            t["bins_gt"][b] += 1
            if gi in matched:
                t["bins_tp"][b] += 1
        t["gt"] += len(gt)
        t["tp"] += len(m)
        t["ious"] += [v for _, _, v in m]
        t["match_conf"] += [dets[di][4] for _, di, _ in m]
        if gt:
            t["frames_with_gt"] += 1
            if len(dets) < len(gt):  # MEVA's count is a lower bound: this is a real miss
                t["undercount_frames"] += 1
                t["shortfall"] += len(gt) - len(dets)
    return t


def bootstrap(clips: list, stat, n: int = BOOT, seed: int = 0) -> tuple:
    """Point estimate and 95% percentile CI, resampling whole clips.
    With a single clip there is nothing to resample: the CI is (None, None)."""
    rng = random.Random(seed)
    point = stat(clips)
    if len(clips) < 2:
        return point, None, None
    vals = []
    for _ in range(n):
        v = stat([clips[rng.randrange(len(clips))] for _ in clips])
        if v is not None:
            vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5]) if vals else (float("nan"), float("nan"))
    return point, float(lo), float(hi)


def ratio(num_key, den_key, idx=None):
    def f(tallies):
        num = sum(t[num_key] if idx is None else t[num_key][idx] for t in tallies)
        den = sum(t[den_key] if idx is None else t[den_key][idx] for t in tallies)
        return num / den if den else None
    return f


# ---------------------------------------------------------------- report
def report(conf: float) -> None:
    global IOU_MATCH
    files = sorted(FRAMES_DIR.glob("*.json"))
    if not files:
        sys.exit("No collected clips yet. Run: scripts/eval_meva.py collect")
    clips = [json.loads(p.read_text()) for p in files]
    tallies = [score_clip(c, conf) for c in clips]

    summary = {"threshold": conf, "iou_match": IOU_MATCH, "clips": len(clips),
               "sampled_frames": sum(len(c["frames"]) for c in clips),
               "annotated_boxes": sum(t["gt"] for t in tallies),
               "annotated_boxes_before_dedup": sum(t["gt_raw"] for t in tallies),
               "bootstrap_resamples": BOOT}
    summary["recall"] = bootstrap(tallies, ratio("tp", "gt"))
    # The Hall's bleacher spectators dominate the box count, so also report
    # recall without them and the average over cameras (each camera weighted equally)
    no_hall = [t for t, c in zip(tallies, clips) if c["camera"] != "G299"]
    summary["recall_excl_hall"] = bootstrap(no_hall, ratio("tp", "gt"))
    per_cam = [ratio("tp", "gt")([t for t, c in zip(tallies, clips) if c["camera"] == cam])
               for cam in CAMERAS if any(c["camera"] == cam for c in clips)]
    summary["recall_camera_average"] = float(np.mean([r for r in per_cam if r is not None]))
    summary["undercount_frame_rate"] = bootstrap(tallies, ratio("undercount_frames", "frames_with_gt"))
    summary["mean_shortfall_when_undercounting"] = (
        sum(t["shortfall"] for t in tallies) / max(1, sum(t["undercount_frames"] for t in tallies)))
    ious = [v for t in tallies for v in t["ious"]]
    summary["matched_iou_mean"] = float(np.mean(ious)) if ious else None
    mc = [v for t in tallies for v in t["match_conf"]]
    summary["matched_conf_median"] = float(np.median(mc)) if mc else None
    summary["matched_share_below_0_4"] = float(np.mean(np.array(mc) < 0.4)) if mc else None
    summary["unmatched_detection_share"] = (
        sum(t["det_unmatched"] for t in tallies) / max(1, sum(t["det_total"] for t in tallies)))

    summary["by_height"] = []
    for i, (lo, hi) in enumerate(HEIGHT_BINS):
        r = bootstrap(tallies, ratio("bins_tp", "bins_gt", i))
        summary["by_height"].append({"bin": f"{lo}-{hi if hi < 10_000 else ''}px".replace("-px", "+ px"),
                                     "boxes": sum(t["bins_gt"][i] for t in tallies), "recall": r})

    summary["by_camera"] = []
    for cam, zone in CAMERAS.items():
        sub = [t for t, c in zip(tallies, clips) if c["camera"] == cam]
        if sub:
            summary["by_camera"].append({"camera": cam, "zone": zone, "clips": len(sub),
                                         "boxes": sum(t["gt"] for t in sub),
                                         "recall": bootstrap(sub, ratio("tp", "gt")),
                                         "undercount_frame_rate": ratio("undercount_frames", "frames_with_gt")(sub)})

    # Sensitivity: a looser match (IoU >= 0.3) separates real misses from
    # disagreement about box shape (e.g. MEVA boxes that include carried objects)
    strict, IOU_MATCH = IOU_MATCH, 0.3
    loose = [score_clip(c, conf) for c in clips]
    loose_nh = [t for t, c in zip(loose, clips) if c["camera"] != "G299"]
    summary["iou_0_3"] = {
        "recall": ratio("tp", "gt")(loose), "recall_excl_hall": ratio("tp", "gt")(loose_nh),
        "by_height_excl_hall": [ratio("bins_tp", "bins_gt", i)(loose_nh) for i in range(len(HEIGHT_BINS))]}
    IOU_MATCH = strict
    def causes(ts):
        n = sum(t["gt"] - t["tp"] for t in ts) or 1
        return {k: sum(t[k] for t in ts) / n for k in ("miss_low_conf", "miss_crowded", "miss_none")}
    summary["miss_causes_excl_hall"] = causes(no_hall)
    summary["miss_causes_hall"] = causes([t for t, c in zip(tallies, clips) if c["camera"] == "G299"])
    summary["by_height_excl_hall"] = [bootstrap(no_hall, ratio("bins_tp", "bins_gt", i)) for i in range(len(HEIGHT_BINS))]
    summary["boxes_by_height_excl_hall"] = [sum(t["bins_gt"][i] for t in no_hall) for i in range(len(HEIGHT_BINS))]

    summary["by_threshold"] = []
    for th in THRESHOLDS:
        ts = [score_clip(c, th) for c in clips]
        ts_nh = [t for t, c in zip(ts, clips) if c["camera"] != "G299"]
        summary["by_threshold"].append({"threshold": th, "recall": ratio("tp", "gt")(ts),
                                        "recall_excl_hall": ratio("tp", "gt")(ts_nh),
                                        "detections_per_frame": sum(t["det_total"] for t in ts) / summary["sampled_frames"]})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    charts(summary)
    write_markdown(summary)
    print((OUT / "report.md").read_text())


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def ci(r):
    p, lo, hi = r
    if p is None:
        return "n/a"
    if lo is None:
        return f"{100 * p:.1f}% (1 clip, no CI)"
    return f"{100 * p:.1f}% (95% CI {100 * lo:.1f}–{100 * hi:.1f}%)"


def write_markdown(s: dict) -> None:
    L = [f"# Detector baseline vs MEVA annotations",
         "",
         f"YOLO11n, person class, confidence ≥ {s['threshold']}, frames resized to 1280×720 "
         f"(as the dashboard). Match = IoU ≥ {s['iou_match']}. {s['clips']} annotated clips, "
         f"{s['sampled_frames']:,} sampled frames, {s['annotated_boxes']:,} annotated person boxes "
         f"after merging {s['annotated_boxes_before_dedup'] - s['annotated_boxes']:,} duplicates "
         f"(same person boxed twice, IoU ≥ {GT_DEDUP_IOU}). "
         f"95% CIs from a clip-level bootstrap ({s['bootstrap_resamples']:,} resamples).",
         "",
         "MEVA only annotates people in labelled activities, so these numbers measure **recall** "
         "and **definite undercounts**. Precision and count error need hand-counted frames.",
         "",
         "**Sampling bias:** annotated people are activity participants, not a random sample of "
         "everyone present. In the Hall they are mostly seated spectators at the far end (small, "
         "partly hidden), while the players on court are largely unannotated. Recall here is "
         "therefore recall on *annotated activity participants*, which leans towards harder cases.",
         "",
         "## Headline",
         "",
         f"- **Recall, excluding the Hall:** {ci(s['recall_excl_hall'])} of annotated people detected.",
         f"- **Recall, average over cameras:** {pct(s['recall_camera_average'])} (each camera weighted equally).",
         f"- **Recall, all clips pooled:** {ci(s['recall'])}. The Hall contributes most annotated boxes "
         "(far-side seated spectators) and pulls this down; see By camera.",
         f"- **With a looser match (IoU ≥ 0.3):** {pct(s['iou_0_3']['recall_excl_hall'])} excluding the Hall "
         f"({pct(s['iou_0_3']['recall'])} pooled). The gap to IoU ≥ 0.5 is box-shape disagreement, not missed people.",
         f"- **Definite undercount:** {ci(s['undercount_frame_rate'])} of annotated frames have "
         f"fewer detections than MEVA's partial count (short by "
         f"{s['mean_shortfall_when_undercounting']:.2f} people on average when it happens).",
         f"- **Localisation:** mean IoU of matched boxes {s['matched_iou_mean']:.2f}.",
         f"- **Confidence of correct detections:** median {s['matched_conf_median']:.2f}; "
         f"{pct(s['matched_share_below_0_4'])} score under 0.4.",
         f"- **Detections not matched to an annotation:** {pct(s['unmatched_detection_share'])} "
         "(mostly unannotated real people; not a false-positive rate).",
         "",
         "## Recall by apparent size (person box height at 720p, a proxy for distance)",
         "",
         "| Box height | Annotated boxes | Recall (all) | Recall excl. Hall | Excl. Hall, IoU ≥ 0.3 |",
         "|---|---:|---|---:|---:|"]
    L += [f"| {b['bin']} | {b['boxes']:,} | {ci(b['recall'])} | {ci(s['by_height_excl_hall'][i])} | "
          f"{pct(s['iou_0_3']['by_height_excl_hall'][i])} |" for i, b in enumerate(s["by_height"])]
    mc, mh = s["miss_causes_excl_hall"], s["miss_causes_hall"]
    L += ["", "## Why annotated people were missed", "",
          "| Cause | Excluding Hall | Hall |", "|---|---:|---:|",
          f"| Detected, but confidence under {s['threshold']} | {pct(mc['miss_low_conf'])} | {pct(mh['miss_low_conf'])} |",
          f"| Box went to a neighbouring person (crowding) | {pct(mc['miss_crowded'])} | {pct(mh['miss_crowded'])} |",
          f"| Not detected at any confidence | {pct(mc['miss_none'])} | {pct(mh['miss_none'])} |"]
    L += ["", "## By camera", "", "| Camera | Zone | Clips | Annotated boxes | Recall | Undercount frames |",
          "|---|---|---:|---:|---|---:|"]
    L += [f"| {c['camera']} | {c['zone']} | {c['clips']} | {c['boxes']:,} | {ci(c['recall'])} | "
          f"{pct(c['undercount_frame_rate'])} |" for c in s["by_camera"]]
    L += ["", "## Recall vs confidence threshold", "",
          "| Threshold | Recall excl. Hall | Recall (all) | Detections per frame |", "|---:|---:|---:|---:|"]
    L += [f"| {t['threshold']:.2f} | {pct(t['recall_excl_hall'])} | {pct(t['recall'])} | "
          f"{t['detections_per_frame']:.2f} |" for t in s["by_threshold"]]
    L += ["", "Charts: `recall_by_height.png`, `recall_by_camera.png`, `recall_vs_threshold.png`."]
    (OUT / "report.md").write_text("\n".join(L) + "\n")


def charts(s: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid, mark = "#1C2B39", "#5C6B78", "#D5DCE1", "#2B6CB0"
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": muted, "axes.labelcolor": ink,
                         "xtick.color": muted, "ytick.color": muted, "axes.spines.top": False,
                         "axes.spines.right": False})

    def bars(rows, labels, title, fname, xlabel):
        fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
        p = [100 * r[0] for r in rows]
        x = list(range(len(rows)))
        ax.bar(x, p, width=0.55, color=mark, zorder=2)
        for i, r in zip(x, rows):
            top = 100 * r[0]
            if r[1] is not None:
                ax.errorbar([i], [top], yerr=[[100 * (r[0] - r[1])], [100 * (r[2] - r[0])]], fmt="none",
                            ecolor=ink, elinewidth=1.2, capsize=4, zorder=3)
                top = 100 * r[2]
            label = f"{100 * r[0]:.0f}%" + ("" if r[1] is not None else "\n1 clip")
            ax.text(i, top + 2, label, ha="center", va="bottom", color=ink, fontsize=10, zorder=4)
        ax.set_xticks(list(x), labels)
        ax.set_ylim(0, 110)
        ax.set_yticks(range(0, 101, 20))
        ax.set_ylabel("Recall (%)")
        ax.set_xlabel(xlabel)
        ax.set_title(title, loc="left", color=ink, fontsize=12)
        ax.yaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
        fig.tight_layout()
        fig.savefig(OUT / fname)
        plt.close(fig)

    idx = [i for i, n in enumerate(s["boxes_by_height_excl_hall"]) if n]
    bars([s["by_height_excl_hall"][i] for i in idx],
         [f"{s['by_height'][i]['bin']}\n(n={s['boxes_by_height_excl_hall'][i]:,})" for i in idx],
         f"Recall by person height at 720p, excluding Hall (threshold {s['threshold']}, 95% CI)",
         "recall_by_height.png", "Person box height")
    bc = s["by_camera"]
    bars([c["recall"] for c in bc], [f"{c['zone']}\n{c['camera']}" for c in bc],
         f"Recall by camera (threshold {s['threshold']}, 95% CI)", "recall_by_camera.png", "")

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    th = [t["threshold"] for t in s["by_threshold"]]
    rc = [100 * t["recall_excl_hall"] for t in s["by_threshold"]]
    ax.plot(th, rc, color=mark, linewidth=2, marker="o", markersize=6, zorder=2)
    ax.axvline(s["threshold"], color=muted, linewidth=1, linestyle="--", zorder=1)
    ax.text(s["threshold"] + 0.01, 5, f"deployed {s['threshold']}", color=muted, fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Confidence threshold")
    ax.set_ylabel("Recall (%)")
    ax.set_title("Recall vs confidence threshold (excluding Hall)", loc="left", color=ink, fontsize=12)
    ax.yaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
    fig.tight_layout()
    fig.savefig(OUT / "recall_vs_threshold.png")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--every", type=int, default=15, help="sample every N frames (default 15 = 2 fps)")
    r = sub.add_parser("report")
    r.add_argument("--conf", type=float, default=0.25, help="threshold to report (default 0.25)")
    args = parser.parse_args()
    if args.cmd == "collect":
        collect(args.every)
    else:
        report(args.conf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
