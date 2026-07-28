from __future__ import annotations

import tkinter as tk
import unittest

from hidden_preview_builder.gui import HiddenPreviewApp


def widget_texts(widget: tk.Misc) -> list[str]:
    texts: list[str] = []
    try:
        value = widget.cget("text")
    except tk.TclError:
        value = ""
    if value:
        texts.append(str(value))
    for child in widget.winfo_children():
        texts.extend(widget_texts(child))
    return texts


class GuiTests(unittest.TestCase):
    def test_main_window_exposes_instructions_and_publisher(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk is unavailable: {exc}") from exc
        root.withdraw()
        try:
            HiddenPreviewApp(root)
            root.update_idletasks()
            text = "\n".join(widget_texts(root))
            self.assertIn("简单说明", text)
            self.assertIn("Video A 是正常播放内容", text)
            self.assertIn("使用说明", text)
            self.assertIn("发布人：教主", text)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
