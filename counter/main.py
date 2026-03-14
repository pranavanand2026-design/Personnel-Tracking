"""Corridor people counter — Stage 2: detection + boxes.

Keys: space = pause/resume, q or Esc = quit.
Hover the mouse over a person's box to see their live stats.
"""
import argparse
import time
from datetime import datetime
from pathlib import Path

import cv2

from counter.detector import PersonDetector
from counter.logger import DetectionLog
from counter.overlay import draw_boxes, draw_hover_panel, draw_hud
from counter.picker import choose_video

ROOT = Path(__file__).resolve().parent.parent
FOOTAGE = ROOT / "footage"
OUTPUT = ROOT / "output"
WINDOW = "Corridor counter"


def count_frames(video_path: Path) -> int:
    """Count frames by grabbing them; MPEG-1 header counts are unreliable."""
    cap = cv2.VideoCapture(str(video_path))
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    return n


def hovered_index(dets, x: float, y: float) -> int | None:
    """Smallest box under the cursor, so overlapping people stay selectable."""
    hits = [i for i, d in enumerate(dets) if d.contains(x, y)]
    return min(hits, key=lambda i: dets[i].w * dets[i].h) if hits else None


def play(video_path: Path, scale: float, conf: float) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_delay = 1.0 / src_fps
    total = count_frames(video_path)

    detector = PersonDetector(conf=conf)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = DetectionLog(OUTPUT, video_path.stem, run_id)
    print(f"Playing {video_path.name}: {src_fps:.1f} fps, {total} frames, "
          f"device={detector.device}")

    mouse = {"pos": (-1, -1)}
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, lambda ev, x, y, *_: mouse.update(pos=(x, y)))

    paused = False
    frame = None
    dets = []
    frame_idx = 0
    last = time.perf_counter()
    fps = 0.0

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            dets = detector.detect(frame)
            log.log(frame_idx, (frame_idx - 1) / src_fps, dets, detector.last_ms)
            now = time.perf_counter()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6))
            last = now

        shown = cv2.resize(frame, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_LINEAR)
        mx, my = mouse["pos"]
        hov = hovered_index(dets, mx / scale, my / scale)

        draw_boxes(shown, dets, scale, hov)
        hud = [
            f"frame {frame_idx}/{total}   t={(frame_idx - 1) / src_fps:5.1f}s",
            f"FPS {fps:4.1f}   infer {detector.last_ms:4.1f} ms ({detector.device})",
            f"people detected: {len(dets)}",
        ]
        if paused:
            hud.append("PAUSED")
        draw_hud(shown, hud)
        if hov is not None:
            draw_hover_panel(shown, dets[hov], hov, frame.shape[0], (mx, my))
        cv2.imshow(WINDOW, shown)

        # Throttle to the video's own frame rate during playback
        wait_ms = max(1, int((frame_delay - (time.perf_counter() - last)) * 1000))
        key = cv2.waitKey(30 if paused else wait_ms) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord(" "):
            paused = not paused
        if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    log.close()
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    print(f"Detection logs:\n  {log.frames_path}\n  {log.boxes_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Corridor people counter")
    parser.add_argument("video", nargs="?", type=Path,
                        help="video path (skips the picker)")
    parser.add_argument("--no-dialog", action="store_true",
                        help="use the terminal menu instead of the macOS dialog")
    parser.add_argument("--scale", type=float, default=2.0,
                        help="display upscale factor (default 2)")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="detection confidence threshold (default 0.25)")
    args = parser.parse_args()

    video = args.video or choose_video(FOOTAGE, use_dialog=not args.no_dialog)
    if not video:
        raise SystemExit("No video chosen.")
    play(video, args.scale, args.conf)


if __name__ == "__main__":
    main()
