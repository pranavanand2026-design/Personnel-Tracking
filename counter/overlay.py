"""Debug-style overlay: boxes, HUD and hover info panel.

Drawing happens on an upscaled copy of the frame (CAVIAR is only 384x288),
so all detection coordinates are multiplied by `scale`.
"""
import cv2
import numpy as np

from counter.detector import Detection

FONT = cv2.FONT_HERSHEY_SIMPLEX
BOX = (0, 200, 0)
BOX_HOVER = (0, 255, 255)
HUD = (0, 255, 255)


def _text_bg(img, text, org, scale=0.5, color=(255, 255, 255), thick=1):
    (w, h), base = cv2.getTextSize(text, FONT, scale, thick)
    x, y = org
    cv2.rectangle(img, (x - 2, y - h - 3), (x + w + 2, y + base), (0, 0, 0), -1)
    cv2.putText(img, text, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def draw_boxes(img: np.ndarray, dets: list[Detection], scale: float,
               hovered: int | None) -> None:
    for i, d in enumerate(dets):
        color = BOX_HOVER if i == hovered else BOX
        p1 = (int(d.x1 * scale), int(d.y1 * scale))
        p2 = (int(d.x2 * scale), int(d.y2 * scale))
        cv2.rectangle(img, p1, p2, color, 3 if i == hovered else 2)
        # Confidence only: distant people are packed tightly; hover for details
        _text_bg(img, f"{d.conf:.2f}", (p1[0], max(p1[1] - 4, 14)),
                 scale=0.4, color=color)


def draw_tracks(img: np.ndarray, rows: list, labels: dict, scale: float) -> None:
    """rows: (track id, x1, y1, x2, y2, conf). labels: track id -> person label
    (e.g. P-0040); people not yet identified show their track number."""
    for tid, x1, y1, x2, y2, conf in rows:
        p1 = (int(x1 * scale), int(y1 * scale))
        p2 = (int(x2 * scale), int(y2 * scale))
        cv2.rectangle(img, p1, p2, BOX, 2)
        label = labels.get(tid) or f"t{tid}"
        _text_bg(img, f"{label} {conf:.2f}", (p1[0], max(p1[1] - 4, 14)), scale=0.45, color=BOX)


def draw_hud(img: np.ndarray, lines: list[str]) -> None:
    # Bottom-left: the far end of the corridor (top of frame) stays visible
    y0 = img.shape[0] - 10 - (len(lines) - 1) * 22
    for i, line in enumerate(lines):
        _text_bg(img, line, (8, y0 + i * 22), scale=0.55, color=HUD)


def draw_hover_panel(img: np.ndarray, d: Detection, idx: int, frame_h: int,
                     mouse: tuple[int, int]) -> None:
    cx, cy = d.centre
    lines = [
        f"Detection #{idx + 1}",
        "Track ID: (Stage 3)",
        f"Confidence: {d.conf:.3f}",
        f"Box: {d.w:.0f} x {d.h:.0f} px",
        f"Height: {d.h / frame_h:.0%} of frame",
        f"Centre: ({cx:.0f}, {cy:.0f})",
        f"Feet at y = {d.y2:.0f}",
    ]
    pad, lh = 8, 20
    w = max(cv2.getTextSize(l, FONT, 0.5, 1)[0][0] for l in lines) + 2 * pad
    h = lh * len(lines) + pad
    H, W = img.shape[:2]
    x = min(mouse[0] + 16, W - w - 4)
    y = min(mouse[1] + 16, H - h - 4)
    roi = img[y:y + h, x:x + w]
    img[y:y + h, x:x + w] = (roi * 0.25).astype(np.uint8)  # translucent panel
    cv2.rectangle(img, (x, y), (x + w, y + h), BOX_HOVER, 1)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (x + pad, y + pad + 12 + i * lh), FONT, 0.5,
                    BOX_HOVER if i == 0 else (255, 255, 255), 1, cv2.LINE_AA)
