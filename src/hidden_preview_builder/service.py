from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import (
    TIMELINE_POLICIES,
    ProgressCallback,
    build_hidden_preview,
)


@dataclass(frozen=True)
class BuildOptions:
    main_video: Path
    preview_source: Path
    output: Path
    fit: str
    timeline_policy: str = "strict"
    preview_kind: str = "auto"
    preset: str = "medium"
    crf: int = 18
    audio_bitrate: str = "256k"
    keep_artifacts: bool = False
    ffmpeg: Path | None = None
    ffprobe: Path | None = None


@dataclass(frozen=True)
class BuildOutcome:
    output: Path
    byte_size: int
    sha256: str
    fps: str
    duration_seconds: float
    width: int
    height: int
    public_frames: int
    physical_frames: int
    source_frames: int
    timeline_policy: str
    timeline_normalized: bool
    pts_discontinuities: int
    missing_frame_slots: int
    ctts_version: int
    ctts_offset_min: int
    ctts_offset_max: int
    raw_first_composition_pts: int
    edit_list_media_time_ticks: int
    edit_list_media_time_frames: int
    audio_codec: str
    audio_sample_rate: int
    audio_channels: int
    artifacts_dir: Path | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_status": "PASS",
            "output": str(self.output),
            "bytes": self.byte_size,
            "sha256": self.sha256,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "resolution": f"{self.width}x{self.height}",
            "public_frames": self.public_frames,
            "physical_frames": self.physical_frames,
            "source_frames": self.source_frames,
            "timeline": {
                "policy": self.timeline_policy,
                "normalized": self.timeline_normalized,
                "pts_discontinuities": self.pts_discontinuities,
                "missing_frame_slots": self.missing_frame_slots,
            },
            "ctts": {
                "version": self.ctts_version,
                "offset_min": self.ctts_offset_min,
                "offset_max": self.ctts_offset_max,
            },
            "raw_first_composition_pts": self.raw_first_composition_pts,
            "edit_list": {
                "media_time_ticks": self.edit_list_media_time_ticks,
                "media_time_frames": self.edit_list_media_time_frames,
            },
            "audio": {
                "codec": self.audio_codec,
                "sample_rate": self.audio_sample_rate,
                "channels": self.audio_channels,
            },
            "artifacts_dir": (
                str(self.artifacts_dir)
                if self.artifacts_dir is not None
                else None
            ),
            "platform_note": (
                "If a platform ignores the video edit list, its thumbnail "
                "path may sample the hidden preview. If it applies or "
                "flattens the edit list, it will sample Video A."
            ),
        }


class BuildFailure(RuntimeError):
    def __init__(self, message: str, artifacts_dir: Path):
        super().__init__(message)
        self.artifacts_dir = artifacts_dir


def _is_strict_child(path: Path, parent: Path) -> bool:
    resolved_path = os.path.normcase(str(path.resolve()))
    resolved_parent = os.path.normcase(str(parent.resolve()))
    return (
        resolved_path != resolved_parent
        and os.path.commonpath([resolved_path, resolved_parent])
        == resolved_parent
    )


def _remove_success_artifacts(run_dir: Path, temp_root: Path) -> None:
    if not _is_strict_child(run_dir, temp_root):
        raise RuntimeError(
            f"Refusing to remove temp directory outside {temp_root}: "
            f"{run_dir}"
        )
    shutil.rmtree(run_dir)


def _outcome_from_result(
    result: dict[str, Any],
    artifacts_dir: Path | None,
) -> BuildOutcome:
    target = result["target_from_video_a"]
    output = result["output"]
    patch = result["container_patch"]
    timeline = target["timeline"]
    container = result["verification"]["container"]
    ctts = container["tracks"]["vide"]["ctts"]
    if ctts is None:
        raise RuntimeError("Validated output unexpectedly has no ctts box")
    return BuildOutcome(
        output=Path(output["path"]),
        byte_size=int(output["bytes"]),
        sha256=str(output["sha256"]),
        fps=str(target["fps"]),
        duration_seconds=float(target["duration_seconds"]),
        width=int(target["width"]),
        height=int(target["height"]),
        public_frames=int(target["public_frames"]),
        physical_frames=int(target["physical_frames"]),
        source_frames=int(target["source_frames"]),
        timeline_policy=str(timeline["policy"]),
        timeline_normalized=bool(timeline["normalized"]),
        pts_discontinuities=int(timeline["pts_discontinuities"]),
        missing_frame_slots=int(timeline["missing_frame_slots"]),
        ctts_version=int(ctts["version"]),
        ctts_offset_min=int(ctts["offset_min"]),
        ctts_offset_max=int(ctts["offset_max"]),
        raw_first_composition_pts=int(
            patch["raw_first_composition_pts"]
        ),
        edit_list_media_time_ticks=int(
            patch["video_elst_media_time"]
        ),
        edit_list_media_time_frames=int(
            patch["video_elst_media_time_frames"]
        ),
        audio_codec="AAC-LC",
        audio_sample_rate=int(target["audio_sample_rate"]),
        audio_channels=int(target["audio_channels"]),
        artifacts_dir=artifacts_dir,
    )


def run_build(
    options: BuildOptions,
    progress: ProgressCallback | None = None,
) -> BuildOutcome:
    main_video = options.main_video.expanduser().resolve()
    preview_source = options.preview_source.expanduser().resolve()
    output = options.output.expanduser().resolve()
    if output.name.lower() != "fin.mp4":
        raise ValueError("The final output filename must be fin.mp4")
    if not main_video.is_file():
        raise FileNotFoundError(main_video)
    if not preview_source.is_file():
        raise FileNotFoundError(preview_source)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing output: {output}"
        )
    if options.fit not in {"contain", "cover", "stretch"}:
        raise ValueError(f"Unsupported fit mode: {options.fit}")
    if options.timeline_policy not in TIMELINE_POLICIES:
        raise ValueError(
            f"Unsupported timeline policy: {options.timeline_policy}"
        )

    temp_root = (
        Path(tempfile.gettempdir()) / "hidden-preview-video-builder"
    ).resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(
        tempfile.mkdtemp(prefix="workflow4-", dir=temp_root)
    ).resolve()
    artifacts_dir = run_dir / "artifacts"
    validated = False

    try:
        result = build_hidden_preview(
            main_video=main_video,
            preview_source=preview_source,
            output=output,
            artifacts_dir=artifacts_dir,
            preview_kind=options.preview_kind,
            fit=options.fit,
            timeline_policy=options.timeline_policy,
            preset=options.preset,
            crf=options.crf,
            audio_bitrate=options.audio_bitrate,
            ffmpeg=options.ffmpeg,
            ffprobe=options.ffprobe,
            progress=progress,
        )
        manifest_path = artifacts_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            result.get("overall_status") != "PASS"
            or manifest.get("overall_status") != "PASS"
        ):
            raise RuntimeError("Local validation did not return PASS")
        validated = True
        outcome = _outcome_from_result(
            result,
            run_dir if options.keep_artifacts else None,
        )
        if not options.keep_artifacts:
            _remove_success_artifacts(run_dir, temp_root)
        return outcome
    except Exception as exc:
        # The destination was guaranteed not to exist before this run, so an
        # output created before a later validation failure is incomplete and
        # safe to remove. Diagnostic artifacts remain in the temp directory.
        if not validated and output.is_file():
            try:
                output.unlink()
            except OSError:
                pass
        if isinstance(exc, BuildFailure):
            raise
        raise BuildFailure(
            f"{exc}\nDiagnostic files: {run_dir}",
            run_dir,
        ) from exc
