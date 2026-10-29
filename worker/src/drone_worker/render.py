"""Draw detections onto BGR frames with OpenCV."""

from __future__ import annotations

import cv2
import numpy as np

from .mock import Detection

# BGR colours per label.
_COLORS: dict[str, tuple[int, int, int]] = {
    "person": (80, 220, 120),
    "car": (60, 180, 255),
    "truck": (255, 170, 60),
    "bus": (200, 120, 255),
    "bicycle": (90, 230, 240),
}
_DEFAULT_COLOR = (200, 200, 200)


def draw_detections(
    frame: np.ndarray,
    detections: list[Detection],
    *,
    index: int | None = None,
    fps: float | None = None,
) -> np.ndarray:
    """Draw boxes, labels and a small HUD in place; returns ``frame``."""
    for det in detections:
        color = _COLORS.get(det.label, _DEFAULT_COLOR)
        cv2.rectangle(frame, (det.x1, det.y1), (det.x2, det.y2), color, 2)

        text = f"{det.label} {det.score:.2f}"
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        # Keep the label inside the frame when the box touches the top edge.
        label_y = det.y1 - th - baseline - 4
        if label_y < 0:
            label_y = det.y1 + 2
        top = max(label_y, 0)
        cv2.rectangle(
            frame,
            (det.x1, top),
            (det.x1 + tw + 6, top + th + baseline + 6),
            color,
            thickness=-1,
        )
        cv2.putText(
            frame,
            text,
            (det.x1 + 3, top + th + 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )

    hud = f"MOCK YOLO | dets {len(detections)}"
    if index is not None:
        hud += f" | frame {index}"
    if fps:
        hud += f" | {fps:.1f} fps"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 26), (0, 0, 0), thickness=-1)
    cv2.putText(
        frame,
        hud,
        (8, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )
    return frame
