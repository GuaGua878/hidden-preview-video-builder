import json
import sys
import tkinter as tk
from pathlib import Path

from hidden_preview_builder import __publisher__, __version__
from hidden_preview_builder.engine import resolve_media_tools
from hidden_preview_builder.gui import HiddenPreviewApp, main


def run_self_test(report_path: Path | None = None) -> None:
    ffmpeg, ffprobe = resolve_media_tools()
    root = tk.Tk()
    root.withdraw()
    try:
        HiddenPreviewApp(root)
        root.update_idletasks()
    finally:
        root.destroy()

    if report_path is not None:
        report = {
            "status": "PASS",
            "publisher": __publisher__,
            "version": __version__,
            "ffmpeg": str(Path(ffmpeg).resolve()),
            "ffprobe": str(Path(ffprobe).resolve()),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def run() -> None:
    if "--self-test-report" in sys.argv:
        index = sys.argv.index("--self-test-report")
        try:
            report_path = Path(sys.argv[index + 1]).expanduser().resolve()
        except IndexError as exc:
            raise SystemExit("--self-test-report requires a file path") from exc
        run_self_test(report_path)
        return
    if "--self-test" in sys.argv:
        run_self_test()
        return
    main()


if __name__ == "__main__":
    run()
