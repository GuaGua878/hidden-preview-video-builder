from __future__ import annotations

import os
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from hidden_preview_builder.engine import (
    aspect_differs,
    choose_timescale,
    main_video_spec,
    resolve_media_tools,
    scale_filter,
)
from hidden_preview_builder.service import _is_strict_child


class EngineUnitTests(unittest.TestCase):
    @staticmethod
    def irregular_timeline_fixture() -> tuple[dict, dict]:
        probe = {
            "streams": [
                {
                    "codec_type": "video",
                    "r_frame_rate": "30/1",
                    "avg_frame_rate": "360000/12001",
                    "time_base": "1/90000",
                    "nb_frames": "4",
                    "nb_read_frames": "4",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "codec_type": "audio",
                    "sample_rate": "48000",
                    "channels": 2,
                },
            ],
            "format": {"duration": "0.266667"},
        }
        frames = {
            "frames": [
                {"pts": 0, "duration": 3000},
                {"pts": 3000, "duration": 3000},
                {"pts": 6000, "duration": 3000},
                # Five nominal frame intervals after the preceding frame.
                {"pts": 21000, "duration": 3000},
            ]
        }
        return probe, frames

    def test_choose_timescale_for_integer_fps(self) -> None:
        self.assertEqual(choose_timescale(Fraction(30, 1)), (30000, 1000))

    def test_choose_timescale_for_ntsc_fps(self) -> None:
        self.assertEqual(
            choose_timescale(Fraction(30000, 1001)),
            (30000, 1001),
        )

    def test_aspect_ratio_tolerance(self) -> None:
        self.assertFalse(aspect_differs(1920, 1080, 3840, 2160))
        self.assertTrue(aspect_differs(1080, 1920, 1920, 1080))

    def test_scale_modes_are_explicit(self) -> None:
        self.assertIn("pad=1920:1080", scale_filter(1920, 1080, "contain"))
        self.assertIn("crop=1920:1080", scale_filter(1920, 1080, "cover"))
        self.assertEqual(
            scale_filter(1920, 1080, "stretch"),
            "scale=1920:1080:flags=lanczos:out_range=tv",
        )

    def test_strict_timeline_policy_rejects_pts_gap(self) -> None:
        probe, frames = self.irregular_timeline_fixture()
        with self.assertRaisesRegex(RuntimeError, "variable-frame-rate"):
            main_video_spec(
                probe,
                frames,
                timeline_policy="strict",
            )

    def test_preserve_duration_policy_normalizes_pts_gap(self) -> None:
        probe, frames = self.irregular_timeline_fixture()

        spec = main_video_spec(
            probe,
            frames,
            timeline_policy="preserve-duration",
        )

        self.assertEqual(spec["fps"], Fraction(30, 1))
        self.assertEqual(spec["source_frame_count"], 4)
        self.assertEqual(spec["frame_count"], 8)
        self.assertEqual(spec["duration"], Fraction(4, 15))
        self.assertTrue(spec["timeline"]["normalized"])
        self.assertEqual(spec["timeline"]["pts_discontinuities"], 1)
        self.assertEqual(spec["timeline"]["missing_frame_slots"], 4)
        self.assertEqual(choose_timescale(spec["fps"]), (30000, 1000))

    def test_resolver_skips_directory_with_lone_ffmpeg(self) -> None:
        ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            incomplete = root / "incomplete"
            complete = root / "complete"
            incomplete.mkdir()
            complete.mkdir()
            (incomplete / ffmpeg_name).touch()
            (complete / ffmpeg_name).touch()
            (complete / ffprobe_name).touch()
            with patch.dict(
                os.environ,
                {
                    "PATH": os.pathsep.join(
                        [str(incomplete), str(complete)]
                    )
                },
                clear=True,
            ):
                ffmpeg, ffprobe = resolve_media_tools()
            self.assertEqual(Path(ffmpeg).parent, complete.resolve())
            self.assertEqual(Path(ffprobe).parent, complete.resolve())

    def test_frozen_app_prefers_side_by_side_tools(self) -> None:
        ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portable = root / "portable"
            configured = root / "configured"
            portable.mkdir()
            configured.mkdir()
            for directory in (portable, configured):
                (directory / ffmpeg_name).touch()
                (directory / ffprobe_name).touch()
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(
                    sys,
                    "executable",
                    str(portable / "HiddenPreviewBuilder.exe"),
                ),
                patch.dict(
                    os.environ,
                    {
                        "HIDDEN_PREVIEW_FFMPEG_DIR": str(configured),
                        "PATH": "",
                    },
                    clear=True,
                ),
            ):
                ffmpeg, ffprobe = resolve_media_tools()
            self.assertEqual(Path(ffmpeg).parent, portable.resolve())
            self.assertEqual(Path(ffprobe).parent, portable.resolve())

    def test_temp_cleanup_guard_accepts_only_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            child = root / "workflow4-test"
            child.mkdir()
            self.assertTrue(_is_strict_child(child, root))
            self.assertFalse(_is_strict_child(root, root))
            self.assertFalse(_is_strict_child(root.parent, root))


if __name__ == "__main__":
    unittest.main()
