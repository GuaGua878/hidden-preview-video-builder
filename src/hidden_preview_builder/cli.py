from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __publisher__, __version__
from .service import BuildFailure, BuildOptions, run_build


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an MP4 whose public playback is Video A and whose hidden "
            "physical preroll is an image or Video B."
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"Hidden Preview Builder {__version__} "
            f"(publisher: {__publisher__})"
        ),
    )
    parser.add_argument("--main-video", required=True, type=Path)
    parser.add_argument("--preview-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--fit",
        choices=["contain", "cover", "stretch"],
        required=True,
    )
    parser.add_argument(
        "--preview-kind",
        choices=["auto", "image", "video"],
        default="auto",
    )
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--audio-bitrate", default="256k")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep validation artifacts under the system temp directory.",
    )
    parser.add_argument(
        "--ffmpeg-dir",
        type=Path,
        help="Directory containing both ffmpeg and ffprobe.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ffmpeg = None
    ffprobe = None
    if args.ffmpeg_dir is not None:
        suffix = ".exe" if sys.platform == "win32" else ""
        ffmpeg = args.ffmpeg_dir / f"ffmpeg{suffix}"
        ffprobe = args.ffmpeg_dir / f"ffprobe{suffix}"

    def progress(stage: str, message: str) -> None:
        print(f"[{stage}] {message}", file=sys.stderr, flush=True)

    try:
        outcome = run_build(
            BuildOptions(
                main_video=args.main_video,
                preview_source=args.preview_source,
                output=args.output,
                fit=args.fit,
                preview_kind=args.preview_kind,
                preset=args.preset,
                crf=args.crf,
                audio_bitrate=args.audio_bitrate,
                keep_artifacts=args.keep_artifacts,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            ),
            progress=progress,
        )
    except BuildFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
