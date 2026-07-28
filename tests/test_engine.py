from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock, patch

from hidden_preview_builder.engine import (
    aspect_differs,
    choose_timescale,
    full_decode,
    main_video_spec,
    probe_output,
    resolve_media_tools,
    scale_filter,
    staged_encode_plan,
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

    def test_frame_probe_is_the_authoritative_input_frame_count(self) -> None:
        probe, frames = self.irregular_timeline_fixture()
        video = probe["streams"][0]
        video.pop("nb_frames")
        video.pop("nb_read_frames")
        probe["format"]["duration"] = "0.133333"
        frames["frames"][-1] = {"pts": 9000, "duration": 3000}

        spec = main_video_spec(probe, frames, timeline_policy="strict")

        self.assertEqual(spec["source_frame_count"], 4)
        self.assertEqual(spec["frame_count"], 4)

    def test_full_decode_returns_count_from_the_same_decode_pass(self) -> None:
        class FakeRunner:
            command: list[str] | None = None

            def run(
                self,
                command: list[str],
                *,
                capture_stdout: bool = False,
                check: bool = True,
            ) -> subprocess.CompletedProcess[bytes]:
                self.command = command
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        b"frame=1\nprogress=continue\n"
                        b"frame=12\nprogress=end\n"
                    ),
                    stderr=b"",
                )

        runner = FakeRunner()
        count = full_decode(
            runner,  # type: ignore[arg-type]
            "ffmpeg",
            Path("fin.mp4"),
            ignore_editlist=False,
        )

        self.assertEqual(count, 12)
        assert runner.command is not None
        self.assertIn("-progress", runner.command)
        self.assertIn("pipe:1", runner.command)
        self.assertIn("0:a:0", runner.command)

    def test_output_metadata_probe_does_not_decode_to_count_frames(
        self,
    ) -> None:
        with patch(
            "hidden_preview_builder.engine.ffprobe_json",
            return_value={"streams": [], "format": {}},
        ) as ffprobe_json_mock:
            probe_output(
                Mock(),
                "ffprobe",
                Path("fin.mp4"),
                ignore_editlist=True,
            )

        arguments = ffprobe_json_mock.call_args.args[3]
        self.assertIn("-ignore_editlist", arguments)
        self.assertNotIn("-count_frames", arguments)

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
            ), patch(
                "hidden_preview_builder.engine.shutil.which",
                side_effect=AssertionError(
                    "Resolver must not use implicit current-directory lookup"
                ),
            ):
                ffmpeg, ffprobe = resolve_media_tools()
            self.assertEqual(Path(ffmpeg).parent, complete.resolve())
            self.assertEqual(Path(ffprobe).parent, complete.resolve())

    def test_staged_encode_plan_avoids_filter_concat(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            plan = staged_encode_plan(
                ffmpeg="ffmpeg",
                main_video=root / "main.mp4",
                preview_source=root / "preview.mp4",
                preview_kind="video",
                intermediate=artifacts / ".fin.physical.tmp.mp4",
                artifacts=artifacts,
                spec={
                    "fps": Fraction(60, 1),
                    "frame_count": 120,
                    "duration": Fraction(2, 1),
                    "width": 3840,
                    "height": 2160,
                    "audio_sample_rate": 48000,
                    "audio_channels": 2,
                    "timeline": {"normalized": False},
                },
                fit="contain",
                preset="medium",
                crf=18,
                audio_bitrate="256k",
                video_timescale=60000,
            )

            self.assertEqual(
                [stage["name"] for stage in plan["stages"]],
                ["preview", "main", "mux"],
            )
            command_text = "\n".join(
                subprocess.list2cmdline(stage["command"])
                for stage in plan["stages"]
            )
            self.assertNotIn("concat=n=2", command_text)
            self.assertIn("-f concat", command_text)
            self.assertIn("-c:v copy", command_text)
            self.assertNotIn(".fin.joined-video.tmp.mp4", command_text)
            self.assertTrue(
                (artifacts / ".fin.video-concat.txt").is_file()
            )
            preview_command = plan["stages"][0]["command"]
            main_command = plan["stages"][1]["command"]
            mux_command = plan["stages"][2]["command"]
            self.assertNotIn("+faststart", preview_command)
            self.assertNotIn("+faststart", main_command)
            self.assertIn("+faststart", mux_command)
            main_filter = main_command[
                main_command.index("-filter_complex") + 1
            ]
            self.assertNotIn("fps=", main_filter)
            self.assertNotIn("scale=", main_filter)

    def test_normalized_main_keeps_fps_and_scale_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            plan = staged_encode_plan(
                ffmpeg="ffmpeg",
                main_video=root / "main.mp4",
                preview_source=root / "preview.mp4",
                preview_kind="video",
                intermediate=artifacts / ".fin.physical.tmp.mp4",
                artifacts=artifacts,
                spec={
                    "fps": Fraction(30, 1),
                    "frame_count": 30,
                    "duration": Fraction(1, 1),
                    "width": 1920,
                    "height": 1080,
                    "audio_sample_rate": 48000,
                    "audio_channels": 2,
                    "timeline": {"normalized": True},
                },
                fit="contain",
                preset="medium",
                crf=18,
                audio_bitrate="256k",
                video_timescale=30000,
            )

            main_command = plan["stages"][1]["command"]
            main_filter = main_command[
                main_command.index("-filter_complex") + 1
            ]
            self.assertIn("fps=30/1", main_filter)
            self.assertIn("scale=1920:1080", main_filter)

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
