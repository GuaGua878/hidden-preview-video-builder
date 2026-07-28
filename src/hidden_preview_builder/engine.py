#!/usr/bin/env python3
"""Build a public Video-A MP4 with hidden preview media in its physical track.

Physical video track:
    [preview source conformed to A] + [Video A]

The video edit list skips the first segment. Normal playback exposes Video A,
while a thumbnail generator that ignores the video edit list sees the hidden
preview segment over the public progress-bar range.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterable


IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
TIMELINE_POLICIES = {"strict", "preserve-duration"}

ProgressCallback = Callable[[str, str], None]


def _noop_progress(_stage: str, _message: str) -> None:
    return


def resolve_media_tools(
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
) -> tuple[str, str]:
    """Find a matching ffmpeg/ffprobe pair.

    A lone, stale ffmpeg earlier on PATH is deliberately skipped. This matters
    on Windows machines that have accumulated multiple FFmpeg installations.
    """

    def usable(path: Path) -> bool:
        return path.is_file()

    if ffmpeg is not None or ffprobe is not None:
        if ffmpeg is None:
            probe_path = Path(ffprobe).expanduser().resolve()
            ffmpeg_path = probe_path.with_name(
                "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
            )
        else:
            ffmpeg_path = Path(ffmpeg).expanduser().resolve()
        if ffprobe is None:
            ffprobe_path = ffmpeg_path.with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
        else:
            ffprobe_path = Path(ffprobe).expanduser().resolve()
        if usable(ffmpeg_path) and usable(ffprobe_path):
            return str(ffmpeg_path), str(ffprobe_path)
        raise RuntimeError(
            "The selected FFmpeg directory must contain both ffmpeg and "
            "ffprobe."
        )

    executable_names = (
        ("ffmpeg.exe", "ffprobe.exe")
        if os.name == "nt"
        else ("ffmpeg", "ffprobe")
    )
    candidate_dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        candidate_dirs.append(Path(sys.executable).resolve().parent)
    configured_dir = os.environ.get("HIDDEN_PREVIEW_FFMPEG_DIR")
    if configured_dir:
        candidate_dirs.append(Path(configured_dir).expanduser())
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        cleaned = os.path.expandvars(entry.strip().strip('"'))
        if cleaned and cleaned != ".":
            candidate_dirs.append(Path(cleaned).expanduser())

    seen: set[str] = set()
    for directory in candidate_dirs:
        key = os.path.normcase(os.path.abspath(str(directory)))
        if key in seen:
            continue
        seen.add(key)
        ffmpeg_path = directory / executable_names[0]
        ffprobe_path = directory / executable_names[1]
        if usable(ffmpeg_path) and usable(ffprobe_path):
            return (
                str(ffmpeg_path.resolve()),
                str(ffprobe_path.resolve()),
            )

    raise RuntimeError(
        "ffmpeg and ffprobe were not found together. Install FFmpeg, put "
        "both programs on PATH or beside the EXE, or set "
        "HIDDEN_PREVIEW_FFMPEG_DIR."
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_fraction(value: str) -> Fraction:
    if not value or value == "0/0":
        raise ValueError(f"Invalid rational value: {value!r}")
    result = Fraction(value)
    if result <= 0:
        raise ValueError(f"Non-positive rational value: {value!r}")
    return result


def fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def seconds_text(value: Fraction) -> str:
    return f"{float(value):.12f}".rstrip("0").rstrip(".")


def fraction_from_decimal(value: str | int | float) -> Fraction:
    return Fraction(str(value))


def safe_int(value: Any, default: int | None = None) -> int:
    if value in (None, "", "N/A"):
        if default is None:
            raise ValueError(f"Missing integer value: {value!r}")
        return default
    return int(value)


class Runner:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def log(self, text: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")

    def run(
        self,
        command: list[str],
        *,
        capture_stdout: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        self.log(
            f"\n[{utc_now()}] COMMAND\n{subprocess.list2cmdline(command)}"
        )
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        if stderr:
            self.log(f"STDERR\n{stderr}")
        self.log(f"RETURN_CODE={result.returncode}")
        if check and result.returncode:
            raise RuntimeError(
                f"Command failed ({result.returncode}): "
                f"{subprocess.list2cmdline(command)}\n{stderr[-5000:]}"
            )
        return result


@dataclass(frozen=True)
class Box:
    start: int
    size: int
    type: str
    header: int

    @property
    def payload(self) -> int:
        return self.start + self.header

    @property
    def end(self) -> int:
        return self.start + self.size


def box_iter(data: bytes | bytearray, start: int, end: int) -> Iterable[Box]:
    position = start
    while position + 8 <= end:
        size32 = struct.unpack_from(">I", data, position)[0]
        box_type = bytes(data[position + 4 : position + 8]).decode(
            "latin1"
        )
        if size32 == 1:
            if position + 16 > end:
                raise RuntimeError(f"Truncated extended box at {position}")
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header = 16
        elif size32 == 0:
            size = end - position
            header = 8
        else:
            size = size32
            header = 8
        if size < header or position + size > end:
            raise RuntimeError(
                f"Invalid MP4 box {box_type!r} at {position}, size={size}"
            )
        yield Box(position, size, box_type, header)
        position += size
    if position != end:
        trailing = bytes(data[position:end])
        if any(trailing):
            raise RuntimeError(f"Unexpected trailing MP4 bytes at {position}")


def children(
    data: bytes | bytearray, parent: Box, box_type: str | None = None
) -> list[Box]:
    items = list(box_iter(data, parent.payload, parent.end))
    if box_type is None:
        return items
    return [item for item in items if item.type == box_type]


def one(data: bytes | bytearray, parent: Box, box_type: str) -> Box:
    matches = children(data, parent, box_type)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {box_type} in {parent.type}, got {len(matches)}"
        )
    return matches[0]


def read_mvhd(
    data: bytes | bytearray, box: Box
) -> tuple[int, int, int]:
    version = data[box.payload]
    if version == 0:
        timescale, duration = struct.unpack_from(
            ">II", data, box.payload + 12
        )
    elif version == 1:
        timescale = struct.unpack_from(">I", data, box.payload + 20)[0]
        duration = struct.unpack_from(">Q", data, box.payload + 24)[0]
    else:
        raise RuntimeError(f"Unsupported mvhd version: {version}")
    return version, timescale, duration


def patch_mvhd_duration(
    data: bytearray, box: Box, duration: int
) -> None:
    version = data[box.payload]
    if version == 0:
        if duration > 0xFFFFFFFF:
            raise RuntimeError("mvhd v0 duration overflow")
        struct.pack_into(">I", data, box.payload + 16, duration)
    elif version == 1:
        struct.pack_into(">Q", data, box.payload + 24, duration)
    else:
        raise RuntimeError(f"Unsupported mvhd version: {version}")


def read_mdhd(
    data: bytes | bytearray, box: Box
) -> tuple[int, int, int]:
    version = data[box.payload]
    if version == 0:
        timescale, duration = struct.unpack_from(
            ">II", data, box.payload + 12
        )
    elif version == 1:
        timescale = struct.unpack_from(">I", data, box.payload + 20)[0]
        duration = struct.unpack_from(">Q", data, box.payload + 24)[0]
    else:
        raise RuntimeError(f"Unsupported mdhd version: {version}")
    return version, timescale, duration


def read_tkhd(
    data: bytes | bytearray, box: Box
) -> tuple[int, int, int]:
    version = data[box.payload]
    if version == 0:
        track_id = struct.unpack_from(">I", data, box.payload + 12)[0]
        duration = struct.unpack_from(">I", data, box.payload + 20)[0]
    elif version == 1:
        track_id = struct.unpack_from(">I", data, box.payload + 20)[0]
        duration = struct.unpack_from(">Q", data, box.payload + 28)[0]
    else:
        raise RuntimeError(f"Unsupported tkhd version: {version}")
    return version, track_id, duration


def patch_tkhd_duration(
    data: bytearray, box: Box, duration: int
) -> None:
    version = data[box.payload]
    if version == 0:
        if duration > 0xFFFFFFFF:
            raise RuntimeError("tkhd v0 duration overflow")
        struct.pack_into(">I", data, box.payload + 20, duration)
    elif version == 1:
        struct.pack_into(">Q", data, box.payload + 28, duration)
    else:
        raise RuntimeError(f"Unsupported tkhd version: {version}")


def read_stts(data: bytes | bytearray, box: Box) -> dict[str, Any]:
    version = data[box.payload]
    entry_count = struct.unpack_from(">I", data, box.payload + 4)[0]
    position = box.payload + 8
    entries: list[dict[str, int]] = []
    for _ in range(entry_count):
        sample_count, sample_delta = struct.unpack_from(
            ">II", data, position
        )
        position += 8
        entries.append(
            {
                "sample_count": sample_count,
                "sample_delta": sample_delta,
            }
        )
    return {
        "version": version,
        "entry_count": entry_count,
        "entries": entries,
        "sample_count": sum(item["sample_count"] for item in entries),
    }


def read_ctts(data: bytes | bytearray, box: Box) -> dict[str, Any]:
    version = data[box.payload]
    entry_count = struct.unpack_from(">I", data, box.payload + 4)[0]
    position = box.payload + 8
    entries: list[dict[str, int]] = []
    for _ in range(entry_count):
        sample_count = struct.unpack_from(">I", data, position)[0]
        if version == 0:
            sample_offset = struct.unpack_from(">I", data, position + 4)[0]
        elif version == 1:
            sample_offset = struct.unpack_from(">i", data, position + 4)[0]
        else:
            raise RuntimeError(f"Unsupported ctts version: {version}")
        position += 8
        entries.append(
            {
                "sample_count": sample_count,
                "sample_offset": sample_offset,
            }
        )
    offsets = [item["sample_offset"] for item in entries]
    return {
        "version": version,
        "entry_count": entry_count,
        "entries": entries,
        "sample_count": sum(item["sample_count"] for item in entries),
        "offset_min": min(offsets),
        "offset_max": max(offsets),
    }


def read_elst(data: bytes | bytearray, box: Box) -> dict[str, Any]:
    version = data[box.payload]
    entry_count = struct.unpack_from(">I", data, box.payload + 4)[0]
    position = box.payload + 8
    entries: list[dict[str, int]] = []
    for _ in range(entry_count):
        if version == 0:
            segment_duration = struct.unpack_from(">I", data, position)[0]
            media_time = struct.unpack_from(">i", data, position + 4)[0]
            rate_integer, rate_fraction = struct.unpack_from(
                ">hh", data, position + 8
            )
            position += 12
        elif version == 1:
            segment_duration = struct.unpack_from(">Q", data, position)[0]
            media_time = struct.unpack_from(">q", data, position + 8)[0]
            rate_integer, rate_fraction = struct.unpack_from(
                ">hh", data, position + 16
            )
            position += 20
        else:
            raise RuntimeError(f"Unsupported elst version: {version}")
        entries.append(
            {
                "segment_duration": segment_duration,
                "media_time": media_time,
                "media_rate_integer": rate_integer,
                "media_rate_fraction": rate_fraction,
            }
        )
    return {
        "version": version,
        "entry_count": entry_count,
        "entries": entries,
    }


def patch_elst_single_entry(
    data: bytearray,
    box: Box,
    *,
    segment_duration: int,
    media_time: int,
) -> None:
    parsed = read_elst(data, box)
    if parsed["entry_count"] != 1:
        raise RuntimeError(
            f"Video elst must have exactly one entry, got {parsed}"
        )
    version = parsed["version"]
    if version == 0:
        if not (0 <= segment_duration <= 0xFFFFFFFF):
            raise RuntimeError("elst v0 segment duration overflow")
        if not (-0x80000000 <= media_time <= 0x7FFFFFFF):
            raise RuntimeError("elst v0 media time overflow")
        struct.pack_into(">I", data, box.payload + 8, segment_duration)
        struct.pack_into(">i", data, box.payload + 12, media_time)
    elif version == 1:
        struct.pack_into(">Q", data, box.payload + 8, segment_duration)
        struct.pack_into(">q", data, box.payload + 16, media_time)
    else:
        raise RuntimeError(f"Unsupported elst version: {version}")


def find_context(data: bytes | bytearray) -> dict[str, Any]:
    roots = list(box_iter(data, 0, len(data)))
    moov_matches = [box for box in roots if box.type == "moov"]
    if len(moov_matches) != 1:
        raise RuntimeError(f"Expected one moov, got {len(moov_matches)}")
    moov = moov_matches[0]
    mvhd = one(data, moov, "mvhd")
    tracks: dict[str, dict[str, Any]] = {}
    stream_order: list[str] = []
    for trak in children(data, moov, "trak"):
        tkhd = one(data, trak, "tkhd")
        mdia = one(data, trak, "mdia")
        mdhd = one(data, mdia, "mdhd")
        hdlr = one(data, mdia, "hdlr")
        handler = bytes(
            data[hdlr.payload + 8 : hdlr.payload + 12]
        ).decode("latin1")
        minf = one(data, mdia, "minf")
        stbl = one(data, minf, "stbl")
        stts = one(data, stbl, "stts")
        ctts_items = children(data, stbl, "ctts")
        edts_items = children(data, trak, "edts")
        elst = (
            one(data, edts_items[0], "elst") if edts_items else None
        )
        tracks[handler] = {
            "trak": trak,
            "tkhd": tkhd,
            "mdia": mdia,
            "mdhd": mdhd,
            "stbl": stbl,
            "stts": stts,
            "ctts": ctts_items[0] if ctts_items else None,
            "elst": elst,
        }
        stream_order.append(handler)
    if set(tracks) != {"vide", "soun"}:
        raise RuntimeError(
            f"Expected one video and one audio track, got {tracks.keys()}"
        )
    return {
        "roots": roots,
        "moov": moov,
        "mvhd": mvhd,
        "tracks": tracks,
        "stream_order": stream_order,
    }


def expand_video_timeline(
    data: bytes | bytearray, context: dict[str, Any]
) -> dict[str, Any]:
    video = context["tracks"]["vide"]
    stts = read_stts(data, video["stts"])
    ctts_box = video["ctts"]
    if ctts_box is None:
        offsets = [0] * stts["sample_count"]
        ctts = None
    else:
        ctts = read_ctts(data, ctts_box)
        offsets = []
        for entry in ctts["entries"]:
            offsets.extend(
                [entry["sample_offset"]] * entry["sample_count"]
            )
    decode_times: list[int] = []
    current = 0
    for entry in stts["entries"]:
        for _ in range(entry["sample_count"]):
            decode_times.append(current)
            current += entry["sample_delta"]
    if len(offsets) != len(decode_times):
        raise RuntimeError(
            f"stts/ctts sample mismatch: {len(decode_times)} != "
            f"{len(offsets)}"
        )
    sample_pts = [
        decode_time + offset
        for decode_time, offset in zip(decode_times, offsets)
    ]
    display_order = sorted(
        range(len(sample_pts)), key=lambda index: (sample_pts[index], index)
    )
    display_pts = [sample_pts[index] for index in display_order]
    return {
        "stts": stts,
        "ctts": ctts,
        "decode_times": decode_times,
        "sample_pts": sample_pts,
        "display_order": display_order,
        "display_pts": display_pts,
    }


def parse_ftyp(data: bytes | bytearray, context: dict[str, Any]) -> dict:
    ftyp_items = [box for box in context["roots"] if box.type == "ftyp"]
    if len(ftyp_items) != 1:
        raise RuntimeError(f"Expected one ftyp, got {len(ftyp_items)}")
    box = ftyp_items[0]
    major = bytes(data[box.payload : box.payload + 4]).decode("latin1")
    minor = struct.unpack_from(">I", data, box.payload + 4)[0]
    brands = [
        bytes(data[position : position + 4]).decode("latin1")
        for position in range(box.payload + 8, box.end, 4)
    ]
    return {
        "major_brand": major,
        "minor_version": minor,
        "compatible_brands": brands,
    }


def full_box_audit(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    context = find_context(data)
    mvhd_version, movie_timescale, movie_duration = read_mvhd(
        data, context["mvhd"]
    )
    timeline = expand_video_timeline(data, context)
    tracks: dict[str, Any] = {}
    for handler, track in context["tracks"].items():
        mdhd_version, mdhd_timescale, mdhd_duration = read_mdhd(
            data, track["mdhd"]
        )
        tkhd_version, track_id, tkhd_duration = read_tkhd(
            data, track["tkhd"]
        )
        tracks[handler] = {
            "track_id": track_id,
            "tkhd_version": tkhd_version,
            "tkhd_duration": tkhd_duration,
            "mdhd_version": mdhd_version,
            "mdhd_timescale": mdhd_timescale,
            "mdhd_duration": mdhd_duration,
            "stts": read_stts(data, track["stts"]),
            "ctts": (
                read_ctts(data, track["ctts"])
                if track["ctts"] is not None
                else None
            ),
            "elst": (
                read_elst(data, track["elst"])
                if track["elst"] is not None
                else None
            ),
        }
    return {
        "ftyp": parse_ftyp(data, context),
        "stream_order": context["stream_order"],
        "movie_timescale": movie_timescale,
        "movie_duration": movie_duration,
        "mvhd_version": mvhd_version,
        "tracks": tracks,
        "raw_first_composition_pts": timeline["display_pts"][0],
        "raw_last_composition_pts": timeline["display_pts"][-1],
        "physical_display_frame_count": len(timeline["display_pts"]),
    }


def patch_container(
    intermediate: Path,
    output: Path,
    *,
    target_frames: int,
    frame_ticks: int,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    data = bytearray(intermediate.read_bytes())
    context = find_context(data)
    video = context["tracks"]["vide"]
    if video["ctts"] is None:
        raise RuntimeError(
            "Encoded H.264 track has no ctts; cannot build the validated "
            "raw-origin-zero path"
        )
    if video["elst"] is None:
        raise RuntimeError("Encoded video track has no edit list")
    ctts_before = read_ctts(data, video["ctts"])
    if ctts_before["version"] != 0:
        raise RuntimeError(f"Expected ctts version 0: {ctts_before}")
    first_entry = ctts_before["entries"][0]
    if first_entry["sample_offset"] <= 0:
        raise RuntimeError(
            f"First ctts run must be positive before patch: {first_entry}"
        )

    # The initial IDR produces a dedicated first CTTS run. Zero only that run
    # so the physical composition origin is exactly zero while leaving the
    # remaining B-picture timing intact.
    if first_entry["sample_count"] >= target_frames:
        raise RuntimeError(
            "The first CTTS run reaches the public Video-A segment; the "
            "encoder did not isolate the hidden preroll timing"
        )
    struct.pack_into(">I", data, video["ctts"].payload + 12, 0)
    timeline = expand_video_timeline(data, context)
    display_pts = timeline["display_pts"]
    if len(display_pts) != target_frames * 2:
        raise RuntimeError(
            f"Physical display frames {len(display_pts)} != "
            f"{target_frames * 2}"
        )
    if display_pts[0] != 0:
        raise RuntimeError(
            f"Raw first composition PTS is {display_pts[0]}, expected 0"
        )
    media_time = display_pts[target_frames]
    visible_pts = display_pts[target_frames : target_frames * 2]
    expected_visible = [
        media_time + index * frame_ticks
        for index in range(target_frames)
    ]
    if visible_pts != expected_visible:
        first_mismatch = next(
            (
                index
                for index, (actual, expected) in enumerate(
                    zip(visible_pts, expected_visible)
                )
                if actual != expected
            ),
            None,
        )
        raise RuntimeError(
            "Visible composition timeline is not uniform; first mismatch "
            f"at {first_mismatch}"
        )

    _, movie_timescale, _ = read_mvhd(data, context["mvhd"])
    _, video_timescale, _ = read_mdhd(data, video["mdhd"])
    if movie_timescale != video_timescale:
        raise RuntimeError(
            f"Movie/video timescales differ: {movie_timescale} vs "
            f"{video_timescale}"
        )
    public_duration = target_frames * frame_ticks
    patch_elst_single_entry(
        data,
        video["elst"],
        segment_duration=public_duration,
        media_time=media_time,
    )
    patch_mvhd_duration(data, context["mvhd"], public_duration)
    patch_tkhd_duration(data, video["tkhd"], public_duration)

    output.write_bytes(data)
    return {
        "first_ctts_entry_before": first_entry,
        "first_ctts_offset_after": 0,
        "raw_first_composition_pts": display_pts[0],
        "video_elst_media_time": media_time,
        "video_elst_media_time_frames": media_time // frame_ticks,
        "video_elst_segment_duration": public_duration,
        "movie_timescale": movie_timescale,
        "video_timescale": video_timescale,
    }


def ffprobe_json(
    runner: Runner,
    ffprobe: str,
    path: Path,
    arguments: list[str],
) -> dict[str, Any]:
    command = [ffprobe, "-v", "error", *arguments, "-of", "json", str(path)]
    result = runner.run(command, capture_stdout=True)
    return json.loads(result.stdout.decode("utf-8"))


def find_stream(
    probe: dict[str, Any], codec_type: str
) -> dict[str, Any]:
    matches = [
        stream
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == codec_type
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {codec_type} stream, got {len(matches)}"
        )
    return matches[0]


def classify_preview(
    preview: Path,
    requested_kind: str,
    preview_probe: dict[str, Any],
) -> str:
    if requested_kind != "auto":
        return requested_kind
    if preview.suffix.lower() in IMAGE_EXTENSIONS:
        return "image"
    format_name = str(
        preview_probe.get("format", {}).get("format_name", "")
    )
    if "image2" in format_name:
        return "image"
    return "video"


def choose_timescale(fps: Fraction) -> tuple[int, int]:
    if fps.denominator in {1000, 1001} and fps.numerator >= 10000:
        factor = 1
    else:
        factor = 1000
    timescale = fps.numerator * factor
    frame_ticks = fps.denominator * factor
    if timescale > 0x7FFFFFFF:
        raise RuntimeError(f"Video timescale is too large: {timescale}")
    return timescale, frame_ticks


def round_positive_fraction(value: Fraction) -> int:
    if value < 0:
        raise ValueError(f"Expected a non-negative fraction, got {value}")
    return (value.numerator * 2 + value.denominator) // (
        value.denominator * 2
    )


def nominal_video_fps(video: dict[str, Any]) -> Fraction:
    candidates = [
        str(video.get("r_frame_rate", "")),
        str(video.get("avg_frame_rate", "")),
    ]
    last_error: Exception | None = None
    for value in candidates:
        try:
            fps = parse_fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            last_error = exc
            continue
        if fps > 1000:
            last_error = ValueError(f"Implausible frame rate: {fps}")
            continue
        # Container averages can have enormous numerators even when the
        # intended cadence is a standard integer/NTSC rate. Keep enough
        # denominator range for 24000/1001, 30000/1001, 60000/1001, etc.
        return fps.limit_denominator(1001)
    raise RuntimeError("Could not determine a nominal Video A frame rate") from (
        last_error
    )


def frame_timing_summary(
    *,
    video: dict[str, Any],
    frame_probe: dict[str, Any],
    fps: Fraction,
    expected_frames: int,
) -> dict[str, Any]:
    frames = frame_probe.get("frames", [])
    if len(frames) != expected_frames:
        raise RuntimeError(
            "Video frame timing probe count does not match the decoded frame "
            f"count: {len(frames)} != {expected_frames}"
        )
    time_base = parse_fraction(str(video.get("time_base", "")))
    nominal_ticks = Fraction(1, 1) / (fps * time_base)
    pts_values: list[int] = []
    durations: list[int] = []
    for index, frame in enumerate(frames):
        pts_value = frame.get(
            "best_effort_timestamp",
            frame.get("pts"),
        )
        if pts_value in (None, "N/A"):
            raise RuntimeError(
                f"Video frame {index} has no usable presentation timestamp"
            )
        pts_values.append(int(pts_value))
        duration_value = frame.get("duration", frame.get("pkt_duration"))
        if duration_value not in (None, "N/A"):
            durations.append(int(duration_value))

    discontinuities: list[dict[str, Any]] = []
    missing_frame_slots = 0
    for index in range(1, len(pts_values)):
        delta = pts_values[index] - pts_values[index - 1]
        if delta <= 0:
            discontinuities.append(
                {
                    "frame_index": index,
                    "delta_ticks": delta,
                    "nominal_ticks": fraction_text(nominal_ticks),
                    "kind": "non_monotonic",
                }
            )
            continue
        if abs(Fraction(delta, 1) - nominal_ticks) <= 1:
            continue
        slots = max(
            1,
            round_positive_fraction(Fraction(delta, 1) / nominal_ticks),
        )
        if delta > nominal_ticks:
            missing_frame_slots += max(0, slots - 1)
        discontinuities.append(
            {
                "frame_index": index,
                "delta_ticks": delta,
                "nominal_ticks": fraction_text(nominal_ticks),
                "nominal_slots": slots,
                "kind": "gap" if delta > nominal_ticks else "short_step",
            }
        )

    duration_outliers = sum(
        1
        for duration in durations
        if abs(Fraction(duration, 1) - nominal_ticks) > 1
    )
    return {
        "first_pts": pts_values[0] if pts_values else 0,
        "last_pts": pts_values[-1] if pts_values else 0,
        "nominal_frame_ticks": fraction_text(nominal_ticks),
        "pts_discontinuities": len(discontinuities),
        "missing_frame_slots": missing_frame_slots,
        "duration_outliers": duration_outliers,
        "discontinuities": discontinuities,
    }


def source_geometry(probe: dict[str, Any]) -> tuple[int, int]:
    video_streams = [
        stream
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    if not video_streams:
        raise RuntimeError("Preview source contains no visual stream")
    return (
        safe_int(video_streams[0].get("width")),
        safe_int(video_streams[0].get("height")),
    )


def aspect_differs(
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> bool:
    left = source_width * target_height
    right = target_width * source_height
    return abs(left - right) > max(left, right) * 0.001


def scale_filter(width: int, height: int, fit: str) -> str:
    if fit == "stretch":
        return (
            f"scale={width}:{height}:flags=lanczos:out_range=tv"
        )
    if fit == "contain":
        return (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=decrease:"
            "flags=lanczos:out_range=tv,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if fit == "cover":
        return (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase:"
            "flags=lanczos:out_range=tv,"
            f"crop={width}:{height}"
        )
    raise RuntimeError(f"Unknown fit mode: {fit}")


def extract_frames(
    runner: Runner,
    ffmpeg: str,
    video: Path,
    output_dir: Path,
    indices: list[int],
    *,
    ignore_editlist: bool,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=False)
    expression = "+".join(f"eq(n\\,{index})" for index in indices)
    pattern = output_dir / "frame_%03d.png"
    command = [ffmpeg, "-v", "error"]
    if ignore_editlist:
        command.extend(["-ignore_editlist", "1"])
    command.extend(
        [
            "-i",
            str(video),
            "-vf",
            f"select='{expression}'",
            "-fps_mode",
            "passthrough",
            str(pattern),
        ]
    )
    runner.run(command)
    produced = sorted(output_dir.glob("frame_*.png"))
    if len(produced) != len(indices):
        raise RuntimeError(
            f"Extracted {len(produced)} verification frames, expected "
            f"{len(indices)}"
        )
    renamed: list[Path] = []
    for index, current in zip(indices, produced):
        target = output_dir / f"frame_{index:09d}.png"
        current.rename(target)
        renamed.append(target)
    return renamed


def full_decode(
    runner: Runner,
    ffmpeg: str,
    output: Path,
    *,
    ignore_editlist: bool,
) -> None:
    command = [ffmpeg, "-v", "error"]
    if ignore_editlist:
        command.extend(["-ignore_editlist", "1"])
    command.extend(["-i", str(output), "-map", "0:v:0"])
    if not ignore_editlist:
        command.extend(["-map", "0:a:0"])
    command.extend(["-f", "null", "-"])
    runner.run(command)


def main_video_spec(
    main_probe: dict[str, Any],
    frame_probe: dict[str, Any],
    *,
    timeline_policy: str = "strict",
) -> dict[str, Any]:
    if timeline_policy not in TIMELINE_POLICIES:
        raise ValueError(f"Unsupported timeline policy: {timeline_policy}")
    video = find_stream(main_probe, "video")
    audio = find_stream(main_probe, "audio")
    fps = nominal_video_fps(video)
    source_frame_count = safe_int(
        video.get("nb_read_frames"), safe_int(video.get("nb_frames"), 0)
    )
    if source_frame_count <= 0:
        raise RuntimeError("Could not count visible frames in Video A")
    width = safe_int(video.get("width"))
    height = safe_int(video.get("height"))
    if width % 2 or height % 2:
        raise RuntimeError(
            f"Video A dimensions must be even for yuv420p: {width}x{height}"
        )
    timing = frame_timing_summary(
        video=video,
        frame_probe=frame_probe,
        fps=fps,
        expected_frames=source_frame_count,
    )
    source_cfr_duration = Fraction(source_frame_count, 1) / fps
    format_duration_value = main_probe.get("format", {}).get("duration")
    if format_duration_value not in (None, "N/A"):
        public_duration = fraction_from_decimal(format_duration_value)
    elif video.get("duration_ts") not in (None, "N/A") and video.get(
        "time_base"
    ) not in (None, "0/0"):
        public_duration = (
            Fraction(int(video["duration_ts"]), 1)
            * Fraction(str(video["time_base"]))
        )
    else:
        public_duration = source_cfr_duration

    duration_mismatch = (
        abs(public_duration - source_cfr_duration) > Fraction(1, 1) / fps
    )
    irregular = (
        timing["pts_discontinuities"] > 0
        or timing["duration_outliers"] > 0
        or duration_mismatch
    )
    if timeline_policy == "strict" and irregular:
        raise RuntimeError(
            "Video A appears variable-frame-rate or has an incompatible "
            "timeline. Use the preserve-duration policy only after choosing "
            "to conform it to CFR."
        )

    if timeline_policy == "preserve-duration":
        frame_count = max(
            1,
            round_positive_fraction(public_duration * fps),
        )
        duration = Fraction(frame_count, 1) / fps
    else:
        frame_count = source_frame_count
        duration = source_cfr_duration

    timing.update(
        {
            "policy": timeline_policy,
            "normalized": (
                timeline_policy == "preserve-duration"
                and (irregular or frame_count != source_frame_count)
            ),
            "source_frame_count": source_frame_count,
            "target_frame_count": frame_count,
            "source_public_duration_seconds": float(public_duration),
            "source_cfr_duration_seconds": float(source_cfr_duration),
            "target_duration_seconds": float(duration),
            "duration_mismatch_over_one_frame": duration_mismatch,
        }
    )
    return {
        "fps": fps,
        "source_frame_count": source_frame_count,
        "frame_count": frame_count,
        "duration": duration,
        "width": width,
        "height": height,
        "audio_sample_rate": safe_int(audio.get("sample_rate")),
        "audio_channels": safe_int(audio.get("channels")),
        "source_video_stream": video,
        "source_audio_stream": audio,
        "timeline": timing,
    }


def staged_encode_plan(
    *,
    ffmpeg: str,
    main_video: Path,
    preview_source: Path,
    preview_kind: str,
    intermediate: Path,
    artifacts: Path,
    spec: dict[str, Any],
    fit: str,
    preset: str,
    crf: int,
    audio_bitrate: str,
    video_timescale: int,
) -> dict[str, Any]:
    fps: Fraction = spec["fps"]
    fps_text = fraction_text(fps)
    frames = spec["frame_count"]
    duration: Fraction = spec["duration"]
    duration_decimal = seconds_text(duration)
    width = spec["width"]
    height = spec["height"]
    scale = scale_filter(width, height, fit)
    setpts = f"setpts=N*{fps.denominator}/({fps.numerator}*TB)"
    preview_chain = (
        f"fps={fps_text}:round=near,{scale},setsar=1,"
        "format=yuv420p,setparams=range=limited,"
        f"trim=end_frame={frames},{setpts}[preview]"
    )
    main_chain = (
        f"fps={fps_text}:round=near,"
        f"scale={width}:{height}:flags=lanczos:out_range=tv,setsar=1,"
        "format=yuv420p,setparams=range=limited,"
        f"trim=end_frame={frames},{setpts}[main]"
    )
    audio_chain = (
        f"aresample={spec['audio_sample_rate']}:async=1:first_pts=0,"
        f"apad=whole_dur={duration_decimal},"
        f"atrim=duration={duration_decimal},asetpts=PTS-STARTPTS[audio]"
    )
    keyint = max(1, round(float(fps)))
    x264_params = (
        f"scenecut=0:open-gop=0:bframes=3:b-adapt=2:ref=1:"
        f"keyint={keyint}:min-keyint={keyint}"
    )
    preview_segment = artifacts / ".fin.preview-segment.tmp.mp4"
    main_segment = artifacts / ".fin.main-segment.tmp.mp4"
    joined_video = artifacts / ".fin.joined-video.tmp.mp4"
    concat_list = artifacts / ".fin.video-concat.txt"
    concat_list.write_text(
        "file '"
        + str(preview_segment.resolve()).replace("\\", "/")
        + "'\nfile '"
        + str(main_segment.resolve()).replace("\\", "/")
        + "'\n",
        encoding="utf-8",
    )

    def video_output_options(path: Path) -> list[str]:
        return [
            "-frames:v",
            str(frames),
            "-r",
            fps_text,
            "-fps_mode",
            "cfr",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(keyint),
            "-keyint_min",
            str(keyint),
            "-bf",
            "3",
            "-refs",
            "1",
            "-x264-params",
            x264_params,
            "-force_key_frames",
            "0",
            "-video_track_timescale",
            str(video_timescale),
            "-movie_timescale",
            str(video_timescale),
            "-use_editlist",
            "1",
            "-movflags",
            "+faststart",
            "-brand",
            "mp42",
            str(path),
        ]

    preview_command = [ffmpeg, "-hide_banner", "-y"]
    if preview_kind == "image":
        preview_command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                fps_text,
                "-i",
                str(preview_source),
            ]
        )
    else:
        preview_command.extend(
            ["-stream_loop", "-1", "-i", str(preview_source)]
        )
    preview_command.extend(
        [
            "-filter_complex",
            f"[0:v]{preview_chain}",
            "-map",
            "[preview]",
            *video_output_options(preview_segment),
        ]
    )
    main_command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(main_video),
        "-filter_complex",
        f"[0:v]{main_chain}",
        "-map",
        "[main]",
        *video_output_options(main_segment),
    ]
    concat_command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
        "-video_track_timescale",
        str(video_timescale),
        "-movie_timescale",
        str(video_timescale),
        "-use_editlist",
        "1",
        "-movflags",
        "+faststart",
        "-brand",
        "mp42",
        str(joined_video),
    ]
    mux_command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(joined_video),
        "-i",
        str(main_video),
        "-filter_complex",
        f"[1:a]{audio_chain}",
        "-map",
        "0:v:0",
        "-map",
        "[audio]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        audio_bitrate,
        "-ar",
        str(spec["audio_sample_rate"]),
        "-ac",
        str(spec["audio_channels"]),
        "-map_metadata",
        "-1",
        "-metadata",
        "title=Hidden Preview Edit-List Video",
        "-metadata:s:v:0",
        "handler_name=VideoHandler",
        "-metadata:s:a:0",
        "handler_name=SoundHandler",
        "-video_track_timescale",
        str(video_timescale),
        "-movie_timescale",
        str(video_timescale),
        "-use_editlist",
        "1",
        "-movflags",
        "+faststart",
        "-brand",
        "mp42",
        str(intermediate),
    ]
    return {
        "stages": [
            {"name": "preview", "command": preview_command},
            {"name": "main", "command": main_command},
            {"name": "concat", "command": concat_command},
            {"name": "mux", "command": mux_command},
        ],
        "cleanup": [
            preview_segment,
            main_segment,
            joined_video,
            concat_list,
        ],
    }


def probe_input(
    runner: Runner, ffprobe: str, path: Path, *, count_frames: bool
) -> dict[str, Any]:
    args = []
    if count_frames:
        args.append("-count_frames")
    args.extend(["-show_streams", "-show_format"])
    return ffprobe_json(runner, ffprobe, path, args)


def probe_video_frames(
    runner: Runner,
    ffprobe: str,
    path: Path,
) -> dict[str, Any]:
    return ffprobe_json(
        runner,
        ffprobe,
        path,
        [
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            (
                "frame=pts,best_effort_timestamp,duration,"
                "pkt_duration"
            ),
        ],
    )


def count_output(
    runner: Runner,
    ffprobe: str,
    path: Path,
    *,
    ignore_editlist: bool,
) -> dict[str, Any]:
    args = []
    if ignore_editlist:
        args.extend(["-ignore_editlist", "1"])
    args.extend(
        [
            "-count_frames",
            "-show_streams",
            "-show_format",
        ]
    )
    return ffprobe_json(runner, ffprobe, path, args)


def verify_output(
    *,
    runner: Runner,
    ffmpeg: str,
    ffprobe: str,
    output: Path,
    artifacts: Path,
    spec: dict[str, Any],
    video_timescale: int,
    frame_ticks: int,
) -> dict[str, Any]:
    default_probe = count_output(
        runner, ffprobe, output, ignore_editlist=False
    )
    physical_probe = count_output(
        runner, ffprobe, output, ignore_editlist=True
    )
    (artifacts / "ffprobe_default.json").write_text(
        json.dumps(default_probe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifacts / "ffprobe_ignore_editlist.json").write_text(
        json.dumps(physical_probe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    boxes = full_box_audit(output)
    (artifacts / "container_audit.json").write_text(
        json.dumps(boxes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    visible_video = find_stream(default_probe, "video")
    visible_audio = find_stream(default_probe, "audio")
    physical_video = find_stream(physical_probe, "video")
    frames = spec["frame_count"]
    duration: Fraction = spec["duration"]
    video_track = boxes["tracks"]["vide"]
    ctts = video_track["ctts"]
    video_elst = video_track["elst"]
    expected_duration_ticks = frames * frame_ticks
    checks = {
        "public_visible_frame_count": (
            safe_int(visible_video.get("nb_read_frames")) == frames
        ),
        "physical_video_frame_count": (
            safe_int(physical_video.get("nb_read_frames")) == frames * 2
        ),
        "public_duration_matches_video_a": (
            abs(
                fraction_from_decimal(
                    default_probe["format"]["duration"]
                )
                - duration
            )
            <= Fraction(1, video_timescale)
        ),
        "public_fps_matches_video_a": (
            parse_fraction(str(visible_video["avg_frame_rate"]))
            == spec["fps"]
        ),
        "public_resolution_matches_video_a": (
            safe_int(visible_video.get("width")) == spec["width"]
            and safe_int(visible_video.get("height")) == spec["height"]
        ),
        "public_video_h264_yuv420p": (
            visible_video.get("codec_name") == "h264"
            and visible_video.get("pix_fmt") == "yuv420p"
        ),
        "public_audio_aac_lc": (
            visible_audio.get("codec_name") == "aac"
            and visible_audio.get("profile") == "LC"
        ),
        "public_audio_shape_matches_video_a": (
            safe_int(visible_audio.get("sample_rate"))
            == spec["audio_sample_rate"]
            and safe_int(visible_audio.get("channels"))
            == spec["audio_channels"]
        ),
        "video_first_stream": boxes["stream_order"] == ["vide", "soun"],
        "track_ids_1_2": (
            boxes["tracks"]["vide"]["track_id"] == 1
            and boxes["tracks"]["soun"]["track_id"] == 2
        ),
        "video_timescale": (
            video_track["mdhd_timescale"] == video_timescale
        ),
        "video_stts_single_fixed_step": (
            video_track["stts"]["entry_count"] == 1
            and video_track["stts"]["sample_count"] == frames * 2
            and video_track["stts"]["entries"][0]["sample_delta"]
            == frame_ticks
        ),
        "ctts_present_version_0": (
            ctts is not None and ctts["version"] == 0
        ),
        "ctts_offsets_nonnegative": (
            ctts is not None and ctts["offset_min"] >= 0
        ),
        "raw_first_composition_pts_zero": (
            boxes["raw_first_composition_pts"] == 0
        ),
        "video_elst_one_positive_entry": (
            video_elst is not None
            and video_elst["entry_count"] == 1
            and video_elst["entries"][0]["media_time"] > 0
            and video_elst["entries"][0]["segment_duration"]
            == expected_duration_ticks
        ),
        "movie_duration_exact": (
            boxes["movie_timescale"] == video_timescale
            and boxes["movie_duration"] == expected_duration_ticks
        ),
        "major_brand_mp42": boxes["ftyp"]["major_brand"] == "mp42",
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise RuntimeError(f"Output validation failed: {failures}")

    full_decode(
        runner, ffmpeg, output, ignore_editlist=False
    )
    full_decode(
        runner, ffmpeg, output, ignore_editlist=True
    )

    physical_indices = sorted(
        {
            0,
            frames // 2,
            frames - 1,
            frames,
            min(frames * 2 - 1, frames + 1),
            frames * 2 - 1,
        }
    )
    visible_indices = sorted({0, frames // 2, frames - 1})
    physical_images = extract_frames(
        runner,
        ffmpeg,
        output,
        artifacts / "physical_frames_ignore_editlist",
        physical_indices,
        ignore_editlist=True,
    )
    visible_images = extract_frames(
        runner,
        ffmpeg,
        output,
        artifacts / "public_visible_frames",
        visible_indices,
        ignore_editlist=False,
    )

    return {
        "checks": checks,
        "full_decode_default": "PASS",
        "full_decode_ignore_editlist": "PASS",
        "physical_verification_frames": [
            {
                "frame": index,
                "section": (
                    "hidden_preview" if index < frames else "main_video_a"
                ),
                "image": str(path.resolve()),
            }
            for index, path in zip(physical_indices, physical_images)
        ],
        "public_verification_frames": [
            {"frame": index, "image": str(path.resolve())}
            for index, path in zip(visible_indices, visible_images)
        ],
        "container": boxes,
    }


def write_preregistration(
    *,
    path: Path,
    csv_path: Path,
    main_video: Path,
    preview_source: Path,
    output: Path,
    preview_kind: str,
    spec: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    duration: Fraction = spec["duration"]
    fps: Fraction = spec["fps"]
    slot_count = math.ceil(float(duration))
    rows: list[dict[str, Any]] = []
    for second in range(slot_count):
        frame_index = min(
            spec["frame_count"] - 1, int(Fraction(second, 1) * fps)
        )
        rows.append(
            {
                "pv_second": second,
                "evidence_scope": "PRIMARY_PUBLIC_RANGE",
                "H_IGNORE_VIDEO_ELST_section": "hidden_preview_material_2",
                "H_IGNORE_VIDEO_ELST_physical_frame": frame_index,
                "H_APPLY_VIDEO_ELST_section": "public_main_video_a",
                "H_APPLY_VIDEO_ELST_visible_frame": frame_index,
            }
        )
    with csv_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    prereg = {
        "schema": "hidden-preview-video-preregistration-v1",
        "created_utc": utc_now(),
        "immutable_after_upload": True,
        "inputs": {
            "video_a": str(main_video.resolve()),
            "video_a_sha256": sha256_file(main_video),
            "preview_source": str(preview_source.resolve()),
            "preview_source_sha256": sha256_file(preview_source),
            "preview_kind": preview_kind,
        },
        "output": {
            "file": str(output.resolve()),
            "sha256": sha256_file(output),
            "public_duration_seconds": float(duration),
            "physical_video_duration_seconds": float(duration * 2),
            "fps": fraction_text(fps),
            "width": spec["width"],
            "height": spec["height"],
            "public_frames": spec["frame_count"],
            "physical_frames": spec["frame_count"] * 2,
            "video_elst_media_time": patch["video_elst_media_time"],
            "video_elst_media_time_frames": patch[
                "video_elst_media_time_frames"
            ],
        },
        "primary_hypothesis": (
            "If the platform thumbnail path ignores the video edit list, "
            "the public progress-bar range shows material 2 after its "
            "frame-rate, duration, and geometry conformance."
        ),
        "competing_hypothesis": (
            "If the platform applies or flattens the video edit list before "
            "thumbnail sampling, the public progress-bar range shows Video A."
        ),
        "important_limit": (
            "A platform may expose slots based on the doubled physical video "
            "track. Slots outside the public duration are exploratory and "
            "must not replace the primary public-range analysis."
        ),
        "predictions_csv": csv_path.name,
    }
    path.write_text(
        json.dumps(prereg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return prereg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create an MP4 whose public playback is Video A and whose hidden "
            "physical preroll is a conformed image or Video B."
        )
    )
    parser.add_argument("--main-video", required=True, type=Path)
    parser.add_argument("--preview-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help=(
            "Write probes, manifests, hashes, logs, and verification frames "
            "to this directory instead of beside the output."
        ),
    )
    parser.add_argument(
        "--preview-kind",
        choices=["auto", "image", "video"],
        default="auto",
    )
    parser.add_argument(
        "--fit",
        choices=["contain", "cover", "stretch"],
        help=(
            "Required when material 2 and Video A have different aspect "
            "ratios. contain adds bars; cover crops; stretch distorts."
        ),
    )
    parser.add_argument(
        "--timeline-policy",
        choices=sorted(TIMELINE_POLICIES),
        default="strict",
        help=(
            "strict rejects irregular Video A timestamps; "
            "preserve-duration conforms them to the nominal frame rate "
            "while preserving the source container duration."
        ),
    )
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--audio-bitrate", default="256k")
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    return parser


def build_hidden_preview(
    *,
    main_video: str | Path,
    preview_source: str | Path,
    output: str | Path,
    artifacts_dir: str | Path | None = None,
    preview_kind: str = "auto",
    fit: str | None = None,
    timeline_policy: str = "strict",
    preset: str = "medium",
    crf: int = 18,
    audio_bitrate: str = "256k",
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Build and fully validate one hidden-preview MP4."""
    progress_callback = progress or _noop_progress
    args = argparse.Namespace(
        main_video=Path(main_video),
        preview_source=Path(preview_source),
        output=Path(output),
        artifacts_dir=(
            Path(artifacts_dir) if artifacts_dir is not None else None
        ),
        preview_kind=preview_kind,
        fit=fit,
        timeline_policy=timeline_policy,
        preset=preset,
        crf=crf,
        audio_bitrate=audio_bitrate,
        ffmpeg=Path(ffmpeg) if ffmpeg is not None else None,
        ffprobe=Path(ffprobe) if ffprobe is not None else None,
    )
    progress_callback("preflight", "Checking inputs and media tools")
    main_video = args.main_video.resolve()
    preview_source = args.preview_source.resolve()
    output = args.output.resolve()
    if not main_video.is_file():
        raise FileNotFoundError(main_video)
    if not preview_source.is_file():
        raise FileNotFoundError(preview_source)
    if output.suffix.lower() != ".mp4":
        raise RuntimeError("Output must use the .mp4 extension")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = (
        args.artifacts_dir.resolve()
        if args.artifacts_dir is not None
        else output.parent / f"{output.stem}_artifacts"
    )
    if artifacts.exists():
        raise FileExistsError(
            f"Refusing to overwrite artifacts directory: {artifacts}"
        )
    artifacts.parent.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir()
    intermediate = (
        artifacts / f".{output.stem}.physical.tmp.mp4"
        if args.artifacts_dir is not None
        else output.parent / f".{output.stem}.physical.tmp.mp4"
    )
    if intermediate.exists():
        raise FileExistsError(intermediate)

    ffmpeg, ffprobe = resolve_media_tools(args.ffmpeg, args.ffprobe)
    runner = Runner(artifacts / "generation.log")
    runner.log(f"STARTED_UTC={utc_now()}")
    runner.log(f"MAIN_VIDEO={main_video}")
    runner.log(f"PREVIEW_SOURCE={preview_source}")
    runner.log(f"OUTPUT={output}")

    progress_callback("probe", "Inspecting Video A and preview source")
    main_probe = probe_input(
        runner, ffprobe, main_video, count_frames=True
    )
    main_frame_probe = probe_video_frames(
        runner,
        ffprobe,
        main_video,
    )
    preview_probe = probe_input(
        runner, ffprobe, preview_source, count_frames=False
    )
    (artifacts / "input_video_a_probe.json").write_text(
        json.dumps(main_probe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifacts / "input_video_a_frames.json").write_text(
        json.dumps(main_frame_probe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifacts / "input_preview_probe.json").write_text(
        json.dumps(preview_probe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    spec = main_video_spec(
        main_probe,
        main_frame_probe,
        timeline_policy=args.timeline_policy,
    )
    preview_kind = classify_preview(
        preview_source, args.preview_kind, preview_probe
    )
    preview_width, preview_height = source_geometry(preview_probe)
    different_aspect = aspect_differs(
        preview_width,
        preview_height,
        spec["width"],
        spec["height"],
    )
    if different_aspect and args.fit is None:
        # This is an expected clarification stop, not a failed build. Remove
        # the just-created preflight artifacts so the same output path can be
        # reused after the user chooses a fit mode.
        shutil.rmtree(artifacts)
        raise RuntimeError(
            "Material 2 and Video A have different aspect ratios. Ask the "
            "user to choose --fit contain, cover, or stretch."
        )
    fit = args.fit or "contain"
    video_timescale, frame_ticks = choose_timescale(spec["fps"])

    runner.log(
        "TARGET="
        + json.dumps(
            {
                "fps": fraction_text(spec["fps"]),
                "frames": spec["frame_count"],
                "duration_seconds": float(spec["duration"]),
                "width": spec["width"],
                "height": spec["height"],
                "preview_kind": preview_kind,
                "fit": fit,
                "video_timescale": video_timescale,
                "frame_ticks": frame_ticks,
                "timeline": spec["timeline"],
            },
            ensure_ascii=False,
        )
    )
    encode_plan = staged_encode_plan(
        ffmpeg=ffmpeg,
        main_video=main_video,
        preview_source=preview_source,
        preview_kind=preview_kind,
        intermediate=intermediate,
        artifacts=artifacts,
        spec=spec,
        fit=fit,
        preset=args.preset,
        crf=args.crf,
        audio_bitrate=args.audio_bitrate,
        video_timescale=video_timescale,
    )
    stage_messages = {
        "preview": "Encoding the hidden preview segment",
        "main": "Encoding the public Video A segment",
        "concat": "Joining the encoded video segments",
        "mux": "Adding Video A audio",
    }
    for stage in encode_plan["stages"]:
        stage_name = str(stage["name"])
        progress_callback(
            f"encode_{stage_name}",
            stage_messages[stage_name],
        )
        runner.run(stage["command"])
    for staged_path in encode_plan["cleanup"]:
        staged_path.unlink()
    progress_callback("patch", "Patching MP4 edit and timing boxes")
    patch = patch_container(
        intermediate,
        output,
        target_frames=spec["frame_count"],
        frame_ticks=frame_ticks,
    )
    intermediate.unlink()

    progress_callback("verify", "Validating both public and physical tracks")
    verification = verify_output(
        runner=runner,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        output=output,
        artifacts=artifacts,
        spec=spec,
        video_timescale=video_timescale,
        frame_ticks=frame_ticks,
    )
    prereg_path = artifacts / "preregistration.json"
    prereg_csv = artifacts / "preregistered_predictions.csv"
    prereg = write_preregistration(
        path=prereg_path,
        csv_path=prereg_csv,
        main_video=main_video,
        preview_source=preview_source,
        output=output,
        preview_kind=preview_kind,
        spec=spec,
        patch=patch,
    )
    progress_callback("report", "Writing validation manifest and checksums")
    result = {
        "schema": "hidden-preview-video-manifest-v1",
        "created_utc": utc_now(),
        "overall_status": "PASS",
        "status_scope": (
            "PASS covers local input conformance, container timing, public "
            "and physical frame counts, audio/video properties, full decode, "
            "verification-frame extraction, and hashes. It does not claim a "
            "platform-side thumbnail result."
        ),
        "inputs": {
            "video_a": str(main_video),
            "video_a_sha256": sha256_file(main_video),
            "preview_source": str(preview_source),
            "preview_source_sha256": sha256_file(preview_source),
            "preview_kind": preview_kind,
            "fit": fit,
        },
        "target_from_video_a": {
            "fps": fraction_text(spec["fps"]),
            "duration_seconds": float(spec["duration"]),
            "width": spec["width"],
            "height": spec["height"],
            "public_frames": spec["frame_count"],
            "physical_frames": spec["frame_count"] * 2,
            "source_frames": spec["source_frame_count"],
            "timeline": spec["timeline"],
            "audio_sample_rate": spec["audio_sample_rate"],
            "audio_channels": spec["audio_channels"],
        },
        "output": {
            "path": str(output),
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        },
        "media_tools": {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
        },
        "container_patch": patch,
        "verification": verification,
        "preregistration": {
            "path": str(prereg_path.resolve()),
            "sha256": sha256_file(prereg_path),
            "predictions_csv": str(prereg_csv.resolve()),
            "primary_hypothesis": prereg["primary_hypothesis"],
        },
    }
    manifest_path = artifacts / "manifest.json"
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifacts / "SHA256SUMS.txt").write_text(
        f"{result['output']['sha256']} *{output.name}\n"
        f"{result['preregistration']['sha256']} *{prereg_path.name}\n",
        encoding="ascii",
    )
    runner.log(f"FINISHED_UTC={utc_now()}")
    runner.log("OVERALL_STATUS=PASS")
    progress_callback("done", "Build and local validation passed")
    return result


def main() -> int:
    args = build_parser().parse_args()
    result = build_hidden_preview(
        main_video=args.main_video,
        preview_source=args.preview_source,
        output=args.output,
        artifacts_dir=args.artifacts_dir,
        preview_kind=args.preview_kind,
        fit=args.fit,
        timeline_policy=args.timeline_policy,
        preset=args.preset,
        crf=args.crf,
        audio_bitrate=args.audio_bitrate,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    patch = result["container_patch"]
    artifacts = (
        args.artifacts_dir.resolve()
        if args.artifacts_dir is not None
        else args.output.resolve().parent / f"{args.output.stem}_artifacts"
    )
    print(
        json.dumps(
            {
                "overall_status": result["overall_status"],
                "output": result["output"],
                "target_from_video_a": result["target_from_video_a"],
                "video_elst_media_time": patch[
                    "video_elst_media_time"
                ],
                "video_elst_media_time_frames": patch[
                    "video_elst_media_time_frames"
                ],
                "raw_first_composition_pts": patch[
                    "raw_first_composition_pts"
                ],
                "artifacts": str(artifacts),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
