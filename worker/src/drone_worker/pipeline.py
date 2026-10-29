"""Video in -> annotated video out, using the mock detector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2

from .mock import MockDetector
from .render import draw_detections


@dataclass
class AnnotateResult:
    frames: int
    detections: int
    output: Path
    width: int
    height: int
    fps: float


def annotate_video(
    source: Path,
    output: Path,
    *,
    detector: MockDetector | None = None,
    limit: int | None = None,
    frames_dir: Path | None = None,
    frame_every: int = 30,
) -> AnnotateResult:
    """Read ``source``, render mock detections and write ``output``."""
    source = Path(source)
    output = Path(output)
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {source}")

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        if width <= 0 or height <= 0:
            raise RuntimeError(f"invalid video size {width}x{height}: {source}")

        output.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError(f"cannot open video writer: {output}")

        if frames_dir is not None:
            Path(frames_dir).mkdir(parents=True, exist_ok=True)

        detector = detector or MockDetector()
        detections_total = 0
        index = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                detections = detector.detect(frame, index)
                detections_total += len(detections)
                draw_detections(frame, detections, index=index, fps=fps)
                writer.write(frame)

                if frames_dir is not None and index % frame_every == 0:
                    cv2.imwrite(
                        str(Path(frames_dir) / f"frame_{index:05d}.jpg"), frame
                    )

                index += 1
                if limit is not None and index >= limit:
                    break
        finally:
            writer.release()
    finally:
        cap.release()

    return AnnotateResult(
        frames=index,
        detections=detections_total,
        output=output,
        width=width,
        height=height,
        fps=fps,
    )


def probe_video(source: Path) -> dict[str, float]:
    """Return basic metadata for ``source``."""
    source = Path(source)
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {source}")
    try:
        return {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(cap.get(cv2.CAP_PROP_FPS)),
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
    finally:
        cap.release()
