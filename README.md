# Personnel Tracking: live headcounts per zone for evacuations

An automated "second count" for wardens. An admin draws a site as zones
(entry, general, muster point), gives each zone a camera, and goes live. Each
camera runs a small person detector and tracker; a central hub shows a live
floor plan with the number of people in every zone and an anonymous activity
log for each person (where they have been, and where they were last seen).

Built as an ELEC4712 thesis project (University of Sydney).

## Principles

- **Unknown is never zero.** A zone with no camera, an offline camera or late
  data shows "Unknown", never 0.
- **Privacy by design.** No faces, names or images are stored. People are
  anonymous IDs (P-0001) described by an appearance vector held in memory and
  forgotten 30 minutes after they were last seen.
- **Edge-ready.** One worker process per camera, with a small model, so each
  camera can run on its own single-board computer.

## How it works

| Stage | Technique |
|---|---|
| Detection | YOLO11n, person class only |
| Tracking within a zone | BoT-SORT (Kalman prediction, two-stage IoU matching) |
| Live count | Median of per-frame track counts over each second |
| Appearance profile | yolo26n-reid, 512-number vector per person crop (crops discarded) |
| Linking across zones | Online linker: match new arrivals to people who recently left a neighbouring zone (layout paths, walking-time windows), with uncertain links marked |

## Results (NVIDIA PhysicalAI-SmartSpaces, scene 081, 4 cameras, 13 minutes)

- Live count within ±1 person: Reception 91%, East Wing 97%, Waiting Alcove 100%;
  long corridor 34%, rising to 73% with a sharper detector setting.
- Track purity: 85–92%.
- Appearance matching: the nearest profile from another zone is the same person 89%
  of the time (chance: 3%).
- Cross-zone links correct: 58–67% (67–82% for links between different zones).
  Timing alone: 2%.
- Detector recall on real footage (MEVA): 56% of annotated people; about 75% for
  people over 200 px tall, near 0% under 50 px. Camera placement matters.

Details: `scripts/eval_tracking.py` and `scripts/eval_meva.py`.

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/prepare_demo_feeds.py      # demo cameras (~740 MB)
.venv/bin/python -m counter.web.admin               # create the admin account
.venv/bin/python -m counter.web                     # http://localhost:8000
```

Then: Setup → "Load the demo site" → Go live.

## Status and next steps

Works with recorded demo cameras and video files. Next: network (RTSP) and USB
cameras, door IN/OUT counting, warden accounts and count history, and validation
on real footage. Note that YOLO11n and the ReID model are AGPL-3.0 licensed.

## Credits

Demo footage: NVIDIA PhysicalAI-SmartSpaces (CC BY 4.0). Evaluation footage:
MEVA by Kitware Inc. and IARPA (CC BY 4.0). Detection and tracking: Ultralytics
(AGPL-3.0). Typeface: Barlow (SIL OFL 1.1).
