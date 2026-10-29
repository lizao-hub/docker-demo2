"""Live relay: pull a stream, draw mock detections, push the result back.

The pipeline is:

    MediaMTX (drone1) --RTSP--> this process --> ffmpeg --> RTMP (drone1_yolo)

OpenCV decodes and draws; ffmpeg encodes/remuxes and publishes, because
``cv2.VideoWriter`` cannot reliably write RTMP.  Raw BGR frames are piped to
ffmpeg's stdin.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field

import cv2

from .mock import MockDetector
from .render import draw_detections

_OPEN_TIMEOUT_MS = 5000
_READ_TIMEOUT_MS = 5000
_FFMPEG_STOP_TIMEOUT = 3.0


@dataclass
class RelayConfig:
    source: str
    dest: str
    ffmpeg: str = "ffmpeg"
    bitrate: str = "4M"
    preset: str = "veryfast"
    retry_delay: float = 2.0
    max_seconds: float = 0.0
    seed: int = 7
    max_objects: int = 4
    extra: dict[str, str] = field(default_factory=dict)  # reserved


def _log(message: str) -> None:
    print(f"[relay] {message}", flush=True)


def _interrupt(signum: int, frame: object) -> None:
    """Turn SIGTERM into KeyboardInterrupt so ffmpeg is closed cleanly."""
    del signum, frame
    raise KeyboardInterrupt


def _resolve_ffmpeg(name: str) -> tuple[str | None, bool]:
    """Find ffmpeg on PATH, or fall back to the bundled binary.

    Returns ``(path, is_bundled)``.  The container image installs the
    ``imageio-ffmpeg`` wheel instead of a system ffmpeg, which keeps the image
    small and the build offline-friendly.  Local runs still use the normal PATH
    lookup first.
    """
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return (name, False) if os.path.isfile(name) else (None, False)

    found = shutil.which(name)
    if found:
        return found, False

    try:
        import imageio_ffmpeg
    except ImportError:
        return None, False
    try:
        return imageio_ffmpeg.get_ffmpeg_exe(), True
    except Exception:  # pragma: no cover - defensive, binary missing
        return None, False



def _ffmpeg_command(cfg: RelayConfig, width: int, height: int, fps: float) -> list[str]:
    gop = max(1, int(round(fps * 2)))
    return [
        cfg.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        # raw frames on stdin
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{fps:.6f}",
        "-i",
        "pipe:0",
        # encode + publish
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        cfg.preset,
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(gop),
        "-b:v",
        cfg.bitrate,
        "-f",
        "flv",
        cfg.dest,
    ]


def _start_ffmpeg(cfg: RelayConfig, width: int, height: int, fps: float) -> subprocess.Popen:
    command = _ffmpeg_command(cfg, width, height, fps)
    _log(f"ffmpeg -> {cfg.dest} ({width}x{height} @ {fps:.2f} fps)")
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )


def _stop_ffmpeg(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.stdin is not None:
        try:
            proc.stdin.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=_FFMPEG_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=_FFMPEG_STOP_TIMEOUT)


def _open_source(cfg: RelayConfig) -> cv2.VideoCapture | None:
    # WSL2 does not forward UDP from Windows, so RTSP must use TCP.
    # This has to be set before VideoCapture is constructed.
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

    params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        _OPEN_TIMEOUT_MS,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        _READ_TIMEOUT_MS,
    ]
    try:
        cap = cv2.VideoCapture(cfg.source, cv2.CAP_FFMPEG, params)
    except (TypeError, cv2.error):
        cap = cv2.VideoCapture(cfg.source, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        cap.release()
        return None

    # Harmless if the backend ignores it; keeps latency down when supported.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def _read_fps(cap: cv2.VideoCapture) -> float:
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if not 1.0 <= fps <= 120.0:
        fps = 25.0
    return fps


def _pump(
    cap: cv2.VideoCapture,
    cfg: RelayConfig,
    detector: MockDetector,
    deadline: float | None,
) -> int:
    """Read frames until the source stops; returns frames processed."""
    proc: subprocess.Popen | None = None
    width = height = 0
    fps = _read_fps(cap)
    index = 0
    started = time.monotonic()
    last_report = started

    try:
        while deadline is None or time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                break

            frame_h, frame_w = frame.shape[:2]
            if proc is not None and proc.poll() is not None:
                _log("ffmpeg exited, restarting")
                _stop_ffmpeg(proc)
                proc = None
            if proc is None:
                width, height = frame_w, frame_h
                fps = _read_fps(cap)
                proc = _start_ffmpeg(cfg, width, height, fps)
            elif (frame_w, frame_h) != (width, height):
                _log(f"resolution changed to {frame_w}x{frame_h}, restarting ffmpeg")
                _stop_ffmpeg(proc)
                width, height = frame_w, frame_h
                fps = _read_fps(cap)
                proc = _start_ffmpeg(cfg, width, height, fps)

            detections = detector.detect(frame, index)
            draw_detections(frame, detections, index=index, fps=fps)

            try:
                assert proc.stdin is not None
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                _log("ffmpeg pipe closed, restarting")
                _stop_ffmpeg(proc)
                proc = None

            index += 1
            now = time.monotonic()
            if now - last_report >= 10.0:
                elapsed = now - started
                _log(
                    f"{index} frames, {index / elapsed:.1f} fps, "
                    f"{len(detections)} dets in current frame"
                )
                last_report = now
    finally:
        _stop_ffmpeg(proc)

    return index


def relay(cfg: RelayConfig) -> int:
    """Run until interrupted (or ``max_seconds`` elapses). Returns exit code."""
    ffmpeg, bundled = _resolve_ffmpeg(cfg.ffmpeg)
    if ffmpeg is None:
        _log(f"ffmpeg not found: {cfg.ffmpeg}")
        return 1
    if bundled:
        _log(f"using bundled ffmpeg: {ffmpeg}")
    cfg.ffmpeg = ffmpeg

    _log(f"source {cfg.source}")
    _log(f"dest   {cfg.dest}")
    detector = MockDetector(seed=cfg.seed, max_objects=cfg.max_objects)
    started = time.monotonic()
    deadline = started + cfg.max_seconds if cfg.max_seconds > 0 else None
    total = 0

    previous_sigterm = None
    try:
        previous_sigterm = signal.signal(signal.SIGTERM, _interrupt)
    except (ValueError, OSError):
        # Not the main thread, or the platform does not support it.
        previous_sigterm = None

    try:
        while deadline is None or time.monotonic() < deadline:
            cap = _open_source(cfg)
            if cap is None:
                _log(f"source offline, retrying in {cfg.retry_delay:.1f}s")
                time.sleep(cfg.retry_delay)
                continue

            _log("source connected")
            try:
                frames = _pump(cap, cfg, detector, deadline)
            finally:
                cap.release()
            total += frames
            _log(f"source ended after {frames} frames")

            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(cfg.retry_delay)
    except KeyboardInterrupt:
        _log("interrupted")
    finally:
        elapsed = time.monotonic() - started
        if total:
            _log(f"stopped: {total} frames in {elapsed:.1f}s")
        if previous_sigterm is not None:
            try:
                signal.signal(signal.SIGTERM, previous_sigterm)
            except (ValueError, OSError):
                pass

    return 0
