from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hidden_preview_builder import __version__
from hidden_preview_builder.app import run_self_test


class AppTests(unittest.TestCase):
    def test_root_instructions_include_qq_performance_warning(self) -> None:
        instructions = (
            Path(__file__).resolve().parents[1] / "使用说明.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "实测2分钟4K视频+静态图片用时6分钟,"
            "主要取决于电脑配置,别塞一个超长视频把自己卡死了",
            instructions,
        )

    def test_self_test_report_records_resolved_media_tools(self) -> None:
        root = Mock()
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "self-test.json"
            with (
                patch(
                    "hidden_preview_builder.app.resolve_media_tools",
                    return_value=("C:/portable/ffmpeg.exe", "C:/portable/ffprobe.exe"),
                ),
                patch("hidden_preview_builder.app.tk.Tk", return_value=root),
                patch("hidden_preview_builder.app.HiddenPreviewApp"),
            ):
                run_self_test(report_path)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["publisher"], "教主")
            self.assertEqual(report["version"], __version__)
            self.assertEqual(
                Path(report["ffmpeg"]).name.lower(),
                "ffmpeg.exe",
            )
            self.assertEqual(
                Path(report["ffprobe"]).name.lower(),
                "ffprobe.exe",
            )
            root.withdraw.assert_called_once()
            root.update_idletasks.assert_called_once()
            root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
