"""One process per zone: source -> tracker -> ZoneState + track events -> Publisher.

The published count is the median of the per-frame track counts over the last
second, so it doesn't flicker. Track events go to the hub, which links them
into people and sends person labels back (for the boxes) on `labels_in`.
Annotated JPEG frames are only produced while `stream_wanted` is set, i.e.
while a browser has that zone open. Zones can be started and stopped one at a
time (the camera "Offline" toggle stops its zone's worker).
"""
import csv
import multiprocessing as mp
import statistics
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from counter.hub import Hub, LocalPublisher, Publisher

PUBLISH_EVERY_S = 1.0
DISPLAY_SCALE = 2.0
MAX_STREAM_W = 1280
JPEG_QUALITY = 80
TRACK_W = 1280  # larger frames are scaled to this width before tracking
EVENTS_CSV = Path(__file__).resolve().parent.parent / "output" / "live_events.csv"


def log_event(zone: dict, event: str, detail: str = "") -> None:
    """Append one line to output/live_events.csv (shared by all workers)."""
    EVENTS_CSV.parent.mkdir(exist_ok=True)
    try:  # exclusive create: only one worker writes the header
        with open(EVENTS_CSV, "x", newline="") as f:
            csv.writer(f).writerow(["wall_time", "zone_id", "zone", "camera_id", "event", "detail"])
    except FileExistsError:
        pass
    with open(EVENTS_CSV, "a", newline="") as f:
        csv.writer(f).writerow([datetime.now().isoformat(timespec="seconds"), zone["id"], zone["name"],
                    zone.get("camera_id", ""), event, detail])


def run_zone(zone: dict, publisher: Publisher, stream_wanted, frames_out,
             stop, parent_pid: int, labels_in=None) -> None:
    """Process target. Imports are local so the parent process stays light."""
    import cv2
    import torch

    from counter.overlay import draw_tracks
    from counter.sources import make_source
    from counter.tracking import PersonTracker, TrackBook
    from counter.zone_state import Telemetry, build_zone_state

    torch.set_num_threads(2)  # workers share the CPU
    try:
        source = make_source(zone["source"])
    except Exception as e:  # e.g. missing demo feed or unimplemented RTSP
        publisher.publish({"zone_id": zone["id"], "error": str(e), "last_update": time.time()})
        log_event(zone, "source_error", str(e))
        return
    tracker = PersonTracker(imgsz=zone.get("detect_size", 640))
    book = TrackBook(zone["id"])
    labels: dict[str, str] = {}  # track key -> person label, from the hub
    telemetry = Telemetry()
    log_event(zone, "start", source.source_info.get("name", ""))

    def send(events):
        for e in events:
            publisher.publish(e)

    window_start = time.perf_counter()
    frames, confs, infer_total, counts = 0, [], 0.0, []
    rows = []
    loops = getattr(source, "loops", 0)
    try:
        while not stop.is_set():
            frame, _ts = source.read()
            if frame is None:
                continue
            if getattr(source, "loops", 0) != loops:
                # Recording wrapped: everyone in view "leaves", IDs start fresh,
                # and a fresh window keeps the jump out of the stats.
                loops = source.loops
                log_event(zone, "loop", f"loop {loops}")
                send(book.end_all())
                tracker.reset()
                labels.clear()
                window_start = time.perf_counter()
                frames, confs, infer_total, counts = 0, [], 0.0, []
            if frame.shape[1] > TRACK_W:
                frame = cv2.resize(frame, (TRACK_W, round(frame.shape[0] * TRACK_W / frame.shape[1])))
            rows = tracker.track(frame)
            send(book.update(frame, rows, time.time()))
            while labels_in is not None:
                try:
                    key, label = labels_in.get_nowait()
                    labels[key] = label
                except queue.Empty:
                    break
            frames += 1
            counts.append(len(rows))
            confs.extend(r[5] for r in rows)
            infer_total += tracker.last_ms

            if stream_wanted.is_set():
                # Upscale small sources (CAVIAR 384x288) but never past 1280 wide
                scale = min(DISPLAY_SCALE, MAX_STREAM_W / frame.shape[1])
                shown = frame.copy() if scale == 1 else cv2.resize(frame, None, fx=scale, fy=scale)
                draw_tracks(shown, rows, {r[0]: labels.get(book.key(r[0])) for r in rows}, scale)
                _draw_clock(cv2, shown)
                ok, jpg = cv2.imencode(".jpg", shown, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    _put_latest(frames_out, jpg.tobytes())

            elapsed = time.perf_counter() - window_start
            if elapsed >= PUBLISH_EVERY_S:
                if os.getppid() != parent_pid:  # server died without stopping us
                    break
                state = build_zone_state(
                    zone, round(statistics.median(counts)) if counts else 0, confs, frames, elapsed,
                    infer_total / frames if frames else 0.0,
                    source.source_info, telemetry.sample())
                state["camera_id"] = zone.get("camera_id")
                h, w = frame.shape[:2]
                state["tracks"] = [{"key": book.key(r[0]), "person": labels.get(book.key(r[0])),
                                    "box": [round(r[1] / w, 4), round(r[2] / h, 4),
                                            round(r[3] / w, 4), round(r[4] / h, 4)]} for r in rows]
                publisher.publish(state)
                window_start = time.perf_counter()
                frames, confs, infer_total, counts = 0, [], 0.0, []
    except KeyboardInterrupt:
        pass
    finally:
        try:
            send(book.end_all())
        except Exception:  # queue gone while the server shuts down
            pass
        source.close()
        log_event(zone, "stop")


def _draw_clock(cv2, img) -> None:
    """Current wall-clock time, top-left, so the view reads as a live camera."""
    text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    cv2.rectangle(img, (8, 8), (20 + w, 20 + h + base), (0, 0, 0), -1)
    cv2.putText(img, text, (14, 14 + h), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                cv2.LINE_AA)


def _put_latest(q, item) -> None:
    """One-slot queue: replace any frame the viewer hasn't taken yet."""
    try:
        q.get_nowait()
    except queue.Empty:
        pass
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


class ZoneStream:
    """Parent-side relay of one zone's JPEG frames to any number of viewers."""

    def __init__(self, frames_in, stream_wanted):
        self.frames_in = frames_in
        self.stream_wanted = stream_wanted
        self.latest: bytes | None = None
        self.seq = 0
        self.viewers = 0
        self._lock = threading.Lock()

    def add_viewer(self) -> None:
        with self._lock:
            self.viewers += 1
            self.stream_wanted.set()

    def remove_viewer(self) -> None:
        with self._lock:
            self.viewers -= 1
            if self.viewers <= 0:
                self.viewers = 0
                self.stream_wanted.clear()
                self.latest = None


class Supervisor:
    """Starts one worker process per zone and wires them to the hub.

    `zones` are runtime-config zone dicts. Zones whose camera is offline are
    registered with the hub (so they show as Unknown) but not started.
    """

    def __init__(self, zones: list[dict], paths: list[dict] | None = None):
        self.ctx = mp.get_context("spawn")
        self.zones = {z["id"]: z for z in zones}
        self.hub = Hub(zones, paths or [])
        self.labels_q = {zid: self.ctx.Queue() for zid in self.zones}
        self.hub.on_label = lambda zid, key, label: self.labels_q[zid].put((key, label))
        self.states_q = self.ctx.Queue()
        self.publisher = LocalPublisher(self.states_q)
        self.stop_threads = threading.Event()
        self.procs: dict[str, mp.Process] = {}
        self.stops: dict[str, object] = {}
        self.streams: dict[str, ZoneStream] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self.hub.drain_local,
                         args=(self.states_q, self.stop_threads), daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()
        for zid, z in self.zones.items():
            if not z.get("offline"):
                self.start_zone(zid)

    def start_zone(self, zid: str) -> None:
        with self._lock:
            if zid in self.procs and self.procs[zid].is_alive():
                return
            z = self.zones[zid]
            z["offline"] = False
            wanted = self.ctx.Event()
            stop = self.ctx.Event()
            frames_q = self.ctx.Queue(maxsize=1)
            stream = self.streams.get(zid)
            if stream:  # keep existing viewers connected across restarts
                stream.frames_in, stream.stream_wanted = frames_q, wanted
                if stream.viewers:
                    wanted.set()
            else:
                stream = self.streams[zid] = ZoneStream(frames_q, wanted)
                threading.Thread(target=self._pump, args=(zid,), daemon=True).start()
            p = self.ctx.Process(target=run_zone, name=f"zone-{zid}",
                                 args=(z, self.publisher, wanted, frames_q, stop, os.getpid(),
                                       self.labels_q[zid]),
                                 daemon=True)
            p.start()
            self.procs[zid], self.stops[zid] = p, stop
            self.hub.set_alive(zid, True)

    def _pump(self, zid: str) -> None:
        stream = self.streams[zid]
        while not self.stop_threads.is_set():
            try:
                stream.latest = stream.frames_in.get(timeout=0.5)
                stream.seq += 1
            except queue.Empty:
                pass

    def stop_zone(self, zid: str) -> None:
        with self._lock:
            self.zones[zid]["offline"] = True
            p, stop = self.procs.pop(zid, None), self.stops.pop(zid, None)
            self.hub.set_alive(zid, False)
        if stop:
            stop.set()
        if p:
            p.join(timeout=3)
            if p.is_alive():
                p.terminate()

    def _watch(self) -> None:
        while not self.stop_threads.is_set():
            for zid in self.zones:
                p = self.procs.get(zid)
                self.hub.set_alive(zid, bool(p and p.is_alive()))
            time.sleep(1.0)

    def stop(self) -> None:
        for stop in list(self.stops.values()):
            stop.set()
        self.stop_threads.set()
        for p in list(self.procs.values()):
            p.join(timeout=3)
            if p.is_alive():
                p.terminate()
        self.procs.clear()
        self.stops.clear()
