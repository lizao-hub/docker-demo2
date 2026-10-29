"""Command line entry point for the mock worker."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .mock import MockDetector
from .pipeline import annotate_video, probe_video

_DEFAULT_SOURCE = "rtsp://127.0.0.1:8554/drone1"
_DEFAULT_DEST = "rtmp://127.0.0.1:1935/drone1_yolo"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drone-worker",
        description="Mock YOLO worker: renders numpy-generated boxes onto video.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    annotate = sub.add_parser("annotate", help="write an annotated copy of a video")
    annotate.add_argument(
        "--input",
        default="assets/drone.mp4",
        help="source video (default: assets/drone.mp4, relative to repo root)",
    )
    annotate.add_argument(
        "--output",
        default="worker/out/annotated.mp4",
        help="destination mp4 (default: worker/out/annotated.mp4)",
    )
    annotate.add_argument(
        "--limit", type=int, default=None, help="stop after N frames"
    )
    annotate.add_argument("--seed", type=int, default=7, help="RNG seed")
    annotate.add_argument(
        "--max-objects", type=int, default=4, help="max simultaneous mock boxes"
    )
    annotate.add_argument(
        "--frames-dir",
        default=None,
        help="also dump a JPEG every --frame-every frames",
    )
    annotate.add_argument(
        "--frame-every", type=int, default=30, help="JPEG dump interval"
    )

    info = sub.add_parser("info", help="print video metadata")
    info.add_argument("--input", default="assets/drone.mp4")

    relay = sub.add_parser("relay", help="pull a live stream and publish it annotated")
    relay.add_argument(
        "--source",
        default=os.environ.get("DRONE_SOURCE", _DEFAULT_SOURCE),
        help=f"input URL (env DRONE_SOURCE, default {_DEFAULT_SOURCE})",
    )
    relay.add_argument(
        "--dest",
        default=os.environ.get("DRONE_DEST", _DEFAULT_DEST),
        help=f"output URL (env DRONE_DEST, default {_DEFAULT_DEST})",
    )
    relay.add_argument(
        "--ffmpeg",
        default=os.environ.get("FFMPEG_BIN", "ffmpeg"),
        help="ffmpeg executable (env FFMPEG_BIN)",
    )
    relay.add_argument("--bitrate", default="4M", help="H.264 target bitrate")
    relay.add_argument("--preset", default="veryfast", help="x264 preset")
    relay.add_argument(
        "--retry-delay", type=float, default=2.0, help="seconds between reconnects"
    )
    relay.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="stop after N seconds (0 = run forever)",
    )
    relay.add_argument("--seed", type=int, default=7, help="RNG seed")
    relay.add_argument(
        "--max-objects", type=int, default=4, help="max simultaneous mock boxes"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "info":
        try:
            meta = probe_video(Path(args.input))
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"{args.input}: {meta['width']}x{meta['height']}, "
            f"{meta['fps']:.2f} fps, {meta['frames']} frames"
        )
        return 0

    if args.command == "relay":
        from .relay import RelayConfig, relay

        cfg = RelayConfig(
            source=args.source,
            dest=args.dest,
            ffmpeg=args.ffmpeg,
            bitrate=args.bitrate,
            preset=args.preset,
            retry_delay=args.retry_delay,
            max_seconds=args.duration,
            seed=args.seed,
            max_objects=args.max_objects,
        )
        return relay(cfg)

    try:
        detector = MockDetector(seed=args.seed, max_objects=args.max_objects)
        result = annotate_video(
            Path(args.input),
            Path(args.output),
            detector=detector,
            limit=args.limit,
            frames_dir=Path(args.frames_dir) if args.frames_dir else None,
            frame_every=args.frame_every,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {result.output} | {result.frames} frames | "
        f"{result.detections} detections | {result.width}x{result.height} "
        f"@ {result.fps:.2f} fps"
    )
    return 0
