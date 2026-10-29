"""Numpy-only stand-in for the YOLO stage.

The real worker will call ultralytics/torch inside the GPU image.  Until that
image is worth building, this module synthesises plausible detections so the
rest of the chain (rendering, RTMP push, WebRTC playback) can be developed
and tested end to end.

Nothing here depends on torch, CUDA or the actual ``best.pt`` weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Small COCO-flavoured label set so rendered boxes look like real output.
LABELS = ("person", "car", "truck", "bus", "bicycle")


@dataclass(frozen=True)
class Detection:
    """One detection in pixel coordinates, top-left origin."""

    x1: int
    y1: int
    x2: int
    y2: int
    score: float
    label: str


@dataclass
class _Track:
    """Internal state of one synthetic object."""

    cx: float
    cy: float
    w: float
    h: float
    vx: float
    vy: float
    label: str
    score: float
    ttl: int


class MockDetector:
    """Random-walk box generator with a stable identity per track.

    Boxes spawn, drift, bounce off the frame edges and expire after a random
    lifetime, which produces output that looks much closer to a real detector
    than independent per-frame noise.
    """

    def __init__(
        self,
        seed: int = 7,
        max_objects: int = 4,
        spawn_prob: float = 0.08,
        min_score: float = 0.35,
    ) -> None:
        if max_objects < 0:
            raise ValueError("max_objects must be >= 0")
        self.seed = seed
        self.max_objects = max_objects
        self.spawn_prob = spawn_prob
        self.min_score = min_score
        self._rng = np.random.default_rng(seed)
        self._tracks: list[_Track] = []
        self._size: tuple[int, int] | None = None

    def reset(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self._tracks.clear()
        self._size = None

    def detect(self, frame: np.ndarray, index: int = 0) -> list[Detection]:
        """Return detections for ``frame`` (H, W, 3 uint8, BGR)."""
        del index  # kept for interface parity with a real detector
        height, width = frame.shape[:2]
        if self._size != (width, height):
            # Resolution change invalidates normalised track positions.
            self._size = (width, height)
            self._tracks.clear()

        rng = self._rng
        if len(self._tracks) < self.max_objects and rng.random() < self.spawn_prob:
            self._tracks.append(self._new_track(width, height))

        alive: list[_Track] = []
        detections: list[Detection] = []
        for track in self._tracks:
            track.cx += track.vx
            track.cy += track.vy
            half_w, half_h = track.w / 2, track.h / 2

            if track.cx - half_w < 0:
                track.cx, track.vx = half_w, abs(track.vx)
            elif track.cx + half_w > width:
                track.cx, track.vx = width - half_w, -abs(track.vx)
            if track.cy - half_h < 0:
                track.cy, track.vy = half_h, abs(track.vy)
            elif track.cy + half_h > height:
                track.cy, track.vy = height - half_h, -abs(track.vy)

            track.score = float(
                np.clip(track.score + rng.normal(0.0, 0.008), self.min_score, 0.98)
            )
            track.ttl -= 1
            if track.ttl <= 0:
                continue

            x1 = int(round(track.cx - half_w))
            y1 = int(round(track.cy - half_h))
            x2 = int(round(track.cx + half_w))
            y2 = int(round(track.cy + half_h))
            detections.append(
                Detection(x1, y1, x2, y2, round(track.score, 3), track.label)
            )
            alive.append(track)

        self._tracks = alive
        detections.sort(key=lambda d: -d.score)
        return detections

    def _new_track(self, width: int, height: int) -> _Track:
        rng = self._rng
        label = str(rng.choice(LABELS))
        box_w = float(rng.uniform(0.08, 0.32)) * width
        box_h = float(rng.uniform(0.10, 0.38)) * height
        box_w = min(box_w, width)
        box_h = min(box_h, height)
        speed = max(width, height) / 900.0
        return _Track(
            cx=float(rng.uniform(box_w / 2, width - box_w / 2)),
            cy=float(rng.uniform(box_h / 2, height - box_h / 2)),
            w=box_w,
            h=box_h,
            vx=float(rng.uniform(-1.5, 1.5) * speed),
            vy=float(rng.uniform(-1.0, 1.0) * speed),
            label=label,
            score=float(rng.uniform(0.45, 0.95)),
            ttl=int(rng.integers(40, 160)),
        )
