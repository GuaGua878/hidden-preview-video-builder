from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hidden_preview_builder.engine import resolve_media_tools
from hidden_preview_builder.service import BuildOptions, run_build


class WorkflowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.ffmpeg, cls.ffprobe = resolve_media_tools()
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        encoders = subprocess.run(
            [cls.ffmpeg, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if "libx264" not in encoders.stdout:
            raise unittest.SkipTest("FFmpeg does not include libx264")

    def _run_ffmpeg(self, arguments: list[str]) -> None:
        result = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-y", *arguments],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            self.fail(result.stderr[-4000:])

    def test_builds_and_validates_short_synthetic_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main_video = root / "main.mp4"
            preview_video = root / "preview.mp4"
            output_dir = root / "output"
            output_dir.mkdir()
            output = output_dir / "fin.mp4"
            app_temp = root / "app-temp"
            app_temp.mkdir()

            self._run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=96x64:rate=6:duration=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:sample_rate=48000:duration=1",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    main_video,
                ]
            )
            self._run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:size=96x64:rate=6:duration=1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    preview_video,
                ]
            )

            with (
                patch(
                    "hidden_preview_builder.service.tempfile.gettempdir",
                    return_value=str(app_temp),
                ),
                patch.object(
                    Path,
                    "read_bytes",
                    side_effect=AssertionError(
                        "MP4 patching must not copy the complete file"
                    ),
                ),
                patch.object(
                    Path,
                    "write_bytes",
                    side_effect=AssertionError(
                        "MP4 patching must write only validated fields"
                    ),
                ),
            ):
                outcome = run_build(
                    BuildOptions(
                        main_video=main_video,
                        preview_source=preview_video,
                        output=output,
                        fit="contain",
                        preset="veryfast",
                        crf=28,
                        ffmpeg=Path(self.ffmpeg),
                        ffprobe=Path(self.ffprobe),
                    )
                )

            self.assertEqual(outcome.public_frames, 6)
            self.assertEqual(outcome.physical_frames, 12)
            self.assertEqual(outcome.fps, "6/1")
            self.assertEqual((outcome.width, outcome.height), (96, 64))
            self.assertEqual(outcome.audio_codec, "AAC-LC")
            self.assertIsNone(outcome.artifacts_dir)
            self.assertEqual(
                [item.name for item in output_dir.iterdir()],
                ["fin.mp4"],
            )
            self.assertFalse(
                any(
                    item.name.startswith("workflow4-")
                    for item in (
                        app_temp / "hidden-preview-video-builder"
                    ).iterdir()
                )
            )


if __name__ == "__main__":
    unittest.main()
