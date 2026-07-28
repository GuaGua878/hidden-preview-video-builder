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
    resolve_media_tools,
    scale_filter,
)
from hidden_preview_builder.service import _is_strict_child


class EngineUnitTests(unittest.TestCase):
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
