# Corridor people counter (ELEC4712 thesis demo)

Python app that counts people walking through a corridor in recorded video:
YOLO person detection, ByteTrack IDs, a counting line (IN/OUT) and polygon
zones (live occupancy), with every crossing logged to CSV as results data.

## Constraints
- Must eventually run on a single-board computer: keep the model small
  (`yolo11n.pt`, class 0 only) and avoid heavy dependencies.
- Overlay stays debug-style (boxes, IDs, IN/OUT/net, per-zone counts, FPS).
- "User education" (supervisor Platt) refers to camera placement context —
  how/where the camera is mounted affects counting. The counting mechanism
  itself does not change.

## Working style
- Propose a plan and wait for approval before writing code.
- Build in stages and stop after each so it can be tested:
  1) file picker + playback, 2) detection + boxes, 3) tracking + IDs,
  4) line counting, 5) zones, 6) CSV logging.

## Environment
- venv at `.venv` (Python 3.12, Homebrew). Homebrew Python has no Tkinter,
  so the file picker uses the macOS dialog via `osascript`, falling back to a
  terminal menu.
- Run desktop app: `.venv/bin/python -m counter.main`
- Site monitor (setup + live view): `.venv/bin/python -m counter.web` → http://localhost:8000
  - First run: create the single admin with `.venv/bin/python -m counter.web.admin`
    (no sign-up page; scrypt hash in `data/site.db`).
  - Flow: Setup (organisation + site names, or "Load the demo site") → Layout
    (empty plan with "+ Add zone"; select a block for a popover: name, role, camera
    incl. "+ New camera", source) → checklist → Go live → Live. The Cameras page is
    for renaming, testing and the Offline toggle. The layout in SQLite is the config;
    Go live writes `data/runtime_config.json` and starts one worker per zone.
  - Roles live in the `roles` table with JSON behaviour (counts: in_out |
    present | arrivals; outline: door | inside | outside); validation and the
    UI read behaviour, so a new role is a new row.
  - Unknown is never zero: no camera / offline / stale zones show "Unknown".
  - Demo cameras (source type `demo`): NVIDIA PhysicalAI-SmartSpaces 2024 scene 081
    (synthetic hospital, CC-BY-4.0), cameras 0803/0800/0804/0796 = Reception (entry),
    Main Corridor, Waiting Alcove, East Wing Corridor. No person is in two of them at
    once. 1080p, 23,994 frames each, in `footage/smartspaces/scene_081/` (downloaded by
    `scripts/prepare_demo_feeds.py`; `ground_truth.txt` has global person IDs across
    cameras). Played on one shared clock (epoch set at Go live). Registry:
    `counter/sources/demo_registry.py`. Worker events → `output/live_events.csv`.
    People in this scene never leave the building: no door IN/OUT or muster data.
  - People tracking: workers run YOLO11n + BoT-SORT (`counter/tracking.py`,
    `counter/trackers/botsort_static.yaml`) and yolo26n-reid appearance vectors
    (`counter/appearance.py`, crops never stored). Count = median of track counts per
    second. Track events (track_decide at 5 s, track_end) go to the hub, whose
    OnlineLinker (`counter/linking.py`) assigns anonymous IDs (P-0001) by appearance
    within layout neighbours; people + logs in memory only, forgotten 30 min after last
    seen. Zone card: In view / Last seen here lists; click an ID or a box for the log.
    Offline eval: `scripts/record_zone_tracks.py` then `scripts/eval_tracking.py`
    → `output/eval/tracking/report.md` (timing-only linking is useless; appearance
    linking ~60-80% precise; IDs split, so unique-person counts overcount).
    Corridor feed uses detect_size 1280 (demo_registry).
  - Test server on a throwaway DB: launch config `site-monitor-test`
    (port 8001, `SITE_DB` env var).
  - Design follows `Building A muster dashboard (concept).html`
    (evacuation-diagram look, Barlow fonts self-hosted in counter/web/static/fonts).
    Keep it plain and functional: no extra cards, banners or explanatory text.
  - No UI for features that don't work yet (no drill button, no "available
    after Stage N" messages, no RTSP option). Never show simulated numbers.
  - Live header: total people in the building (all non-outside zones) and at
    the muster point (hidden when there is none). Validation requires an entry
    zone but not a muster point. Zone card: present now, mean confidence, frame
    rate, detection time, In view / Last seen here. No dataset tags in the UI
    (credits live on the About page). Layout page mirrors the live view: plan left, zone list
    right; "Add zone" menu creates zones.
- One worker process per zone; MPEG-1 files can't seek to frame 0, so
  FileSource reopens the file to loop.
- Run scripts as `.venv/bin/python scripts/...` or `.venv/bin/python -m awscli`:
  the venv's console-script shebangs break on the space in the project path.
- Test videos go in `footage/`; CSVs go in `output/`.
- Detector baseline vs MEVA annotations: `scripts/eval_meva.py collect` then
  `report` → `output/eval/meva_baseline/` (report.md, summary.json, charts).
  MEVA annotates only activity participants (and sometimes the same person
  twice; merged at IoU ≥ 0.8), so it supports recall and definite undercounts,
  not precision or count error. The Hall (G299) dominates box counts; headline
  recall is reported excluding it and averaged per camera.
