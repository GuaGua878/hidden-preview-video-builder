from __future__ import annotations

import ctypes
import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import __publisher__, __version__
from .engine import resolve_media_tools
from .service import BuildFailure, BuildOptions, BuildOutcome, run_build


FIT_LABELS = {
    "保持完整，空白处补黑边": "contain",
    "铺满画面，裁掉超出部分": "cover",
    "直接拉伸到画面尺寸": "stretch",
}

STAGE_LABELS = {
    "preflight": "检查输入与工具",
    "probe": "分析视频参数",
    "encode": "编码隐藏段与公开段",
    "patch": "修补 MP4 时间结构",
    "verify": "完整解码并校验",
    "report": "生成本地验证报告",
    "done": "本地验证通过",
}


class HiddenPreviewApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=20)
        self.master = master
        self.running = False
        self.last_output: Path | None = None
        self.events: queue.Queue[
            tuple[str, object]
        ] = queue.Queue()
        desktop = Path.home() / "Desktop"
        default_output_dir = desktop if desktop.is_dir() else Path.home()

        self.main_video = tk.StringVar()
        self.preview_source = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(default_output_dir))
        self.fit_label = tk.StringVar(value="请选择画面适配方式")
        self.keep_artifacts = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="准备就绪")
        self.tool_status = tk.StringVar(value="正在查找 FFmpeg…")

        self._build_ui()
        self._refresh_media_tool_status()
        self.after(100, self._poll_events)
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid(sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(9, weight=1)

        title = ttk.Label(
            self,
            text="Hidden Preview Builder",
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w")
        subtitle = ttk.Label(
            self,
            text=(
                "公开播放 Video A；在物理视频轨前放入等长预览素材。"
                "输出文件固定为 fin.mp4。"
            ),
        )
        subtitle.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(2, 10),
        )

        guide = ttk.LabelFrame(self, text="简单说明", padding=(12, 8))
        guide.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(0, 10),
        )
        ttk.Label(
            guide,
            text=(
                "1. Video A 是正常播放内容；预览图片 / Video B 是隐藏预览。  "
                "2. 选择画面适配方式和输出文件夹。  "
                "3. 点击生成，显示 PASS 后使用 fin.mp4。"
            ),
            justify=tk.LEFT,
            wraplength=780,
        ).pack(fill=tk.X)

        self._path_row(
            row=3,
            label="Video A",
            variable=self.main_video,
            command=self._choose_main_video,
        )
        self._path_row(
            row=4,
            label="预览图片 / Video B",
            variable=self.preview_source,
            command=self._choose_preview_source,
        )
        self._path_row(
            row=5,
            label="输出文件夹",
            variable=self.output_dir,
            command=self._choose_output_dir,
        )

        ttk.Label(self, text="画面适配").grid(
            row=6, column=0, sticky="w", pady=7
        )
        self.fit_box = ttk.Combobox(
            self,
            textvariable=self.fit_label,
            values=list(FIT_LABELS),
            state="readonly",
        )
        self.fit_box.grid(
            row=6, column=1, columnspan=2, sticky="ew", pady=7
        )

        self.keep_box = ttk.Checkbutton(
            self,
            text="保留临时验证报告（默认成功后自动清理）",
            variable=self.keep_artifacts,
        )
        self.keep_box.grid(
            row=7, column=1, columnspan=2, sticky="w", pady=(4, 2)
        )
        ttk.Label(
            self,
            textvariable=self.tool_status,
            foreground="#555555",
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 10))

        self.log = scrolledtext.ScrolledText(
            self,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.log.grid(
            row=9,
            column=0,
            columnspan=3,
            sticky="nsew",
            pady=(0, 12),
        )

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )
        ttk.Label(self, textvariable=self.status).grid(
            row=11, column=0, columnspan=3, sticky="w"
        )

        button_frame = ttk.Frame(self)
        button_frame.grid(
            row=12, column=0, columnspan=3, sticky="e", pady=(12, 0)
        )
        ttk.Button(
            button_frame,
            text="使用说明",
            command=self._show_help,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.open_button = ttk.Button(
            button_frame,
            text="打开输出文件夹",
            command=self._open_output_folder,
            state=tk.DISABLED,
        )
        self.open_button.pack(side=tk.LEFT, padx=(0, 8))
        self.start_button = ttk.Button(
            button_frame,
            text="生成 fin.mp4",
            command=self._start_build,
        )
        self.start_button.pack(side=tk.LEFT)

        warning = ttk.Label(
            self,
            text=(
                "说明：平台是否采用隐藏预览取决于其是否忽略 MP4 edit list，"
                "本工具不保证平台缩略图结果。"
            ),
            foreground="#7a4b00",
            wraplength=760,
        )
        warning.grid(
            row=13,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(16, 0),
        )
        ttk.Label(
            self,
            text=f"发布人：{__publisher__}    版本：v{__version__}",
            foreground="#666666",
        ).grid(
            row=14,
            column=0,
            columnspan=3,
            sticky="e",
            pady=(10, 0),
        )

    def _path_row(
        self,
        *,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: object,
    ) -> None:
        ttk.Label(self, text=label).grid(
            row=row, column=0, sticky="w", pady=7
        )
        ttk.Entry(self, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(12, 8), pady=7
        )
        ttk.Button(self, text="浏览…", command=command).grid(
            row=row, column=2, sticky="ew", pady=7
        )

    def _choose_main_video(self) -> None:
        path = filedialog.askopenfilename(
            title="选择公开播放的 Video A",
            filetypes=[
                ("MP4 视频", "*.mp4"),
                ("视频文件", "*.mp4 *.mov *.mkv *.avi"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.main_video.set(path)

    def _choose_preview_source(self) -> None:
        path = filedialog.askopenfilename(
            title="选择隐藏预览图片或 Video B",
            filetypes=[
                (
                    "图片或视频",
                    "*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv",
                ),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.preview_source.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(
            title="选择 fin.mp4 输出文件夹",
            initialdir=self.output_dir.get() or None,
        )
        if path:
            self.output_dir.set(path)

    def _refresh_media_tool_status(self) -> None:
        try:
            ffmpeg, _ffprobe = resolve_media_tools()
            self.tool_status.set(f"FFmpeg：{Path(ffmpeg).parent}")
        except Exception as exc:
            self.tool_status.set(f"FFmpeg 未就绪：{exc}")

    def _show_help(self) -> None:
        messagebox.showinfo(
            "使用说明",
            (
                "1. Video A：最终正常播放的视频，必须是恒定帧率且只有一个音轨。\n"
                "2. 预览素材：选择一张图片或 Video B；短视频会自动循环。\n"
                "3. 画面适配：完整显示补黑边、铺满裁切或直接拉伸。\n"
                "4. 输出：选择没有 fin.mp4 的文件夹，程序不会覆盖旧文件。\n"
                "5. 结果：显示 PASS 后使用 fin.mp4；失败时按提示查看临时诊断目录。\n\n"
                "full-portable 发布包已附带 ffmpeg 和 ffprobe，请与主程序放在"
                "同一目录。平台是否采用隐藏预览取决于其是否忽略 MP4 edit "
                "list，本工具不保证平台结果。"
            ),
            parent=self.master,
        )

    def _append_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.start_button.configure(
            state=tk.DISABLED if running else tk.NORMAL
        )
        self.fit_box.configure(
            state=tk.DISABLED if running else "readonly"
        )
        self.keep_box.configure(
            state=tk.DISABLED if running else tk.NORMAL
        )
        if running:
            self.open_button.configure(state=tk.DISABLED)
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start_build(self) -> None:
        if self.running:
            return
        try:
            main_video = Path(self.main_video.get().strip())
            preview_source = Path(self.preview_source.get().strip())
            output_dir = Path(self.output_dir.get().strip())
            if not self.main_video.get().strip():
                raise ValueError("请选择 Video A。")
            if not self.preview_source.get().strip():
                raise ValueError("请选择预览图片或 Video B。")
            if not self.output_dir.get().strip():
                raise ValueError("请选择输出文件夹。")
            if self.fit_label.get() not in FIT_LABELS:
                raise ValueError("请选择一种画面适配方式。")
            output = output_dir / "fin.mp4"
            if output.exists():
                raise FileExistsError(
                    f"{output} 已存在。本工具不会覆盖，请先移动文件或选择其他文件夹。"
                )
            options = BuildOptions(
                main_video=main_video,
                preview_source=preview_source,
                output=output,
                fit=FIT_LABELS[self.fit_label.get()],
                keep_artifacts=self.keep_artifacts.get(),
            )
        except Exception as exc:
            messagebox.showerror("无法开始", str(exc), parent=self.master)
            return

        self.last_output = None
        self._set_running(True)
        self.status.set("正在开始…")
        self._append_log(f"Video A: {options.main_video}")
        self._append_log(f"预览素材: {options.preview_source}")
        self._append_log(f"输出: {options.output}")
        worker = threading.Thread(
            target=self._worker,
            args=(options,),
            daemon=True,
        )
        worker.start()

    def _worker(self, options: BuildOptions) -> None:
        def progress(stage: str, message: str) -> None:
            label = STAGE_LABELS.get(stage, message)
            self.events.put(("progress", label))

        try:
            outcome = run_build(options, progress=progress)
        except Exception as exc:
            self.events.put(("failure", exc))
            return
        self.events.put(("success", outcome))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self._on_progress(str(payload))
                elif event == "failure":
                    assert isinstance(payload, Exception)
                    self._on_failure(payload)
                elif event == "success":
                    assert isinstance(payload, BuildOutcome)
                    self._on_success(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _on_progress(self, label: str) -> None:
        self.status.set(label)
        self._append_log(label)

    def _on_success(self, outcome: BuildOutcome) -> None:
        self._set_running(False)
        self.last_output = outcome.output
        self.open_button.configure(state=tk.NORMAL)
        summary = outcome.as_dict()
        self.status.set("完成：本地结构与解码校验 PASS")
        self._append_log(json.dumps(summary, ensure_ascii=False, indent=2))
        messagebox.showinfo(
            "生成完成",
            (
                f"已生成：\n{outcome.output}\n\n"
                f"{outcome.width}x{outcome.height} · {outcome.fps} fps\n"
                f"公开帧 {outcome.public_frames} · "
                f"物理帧 {outcome.physical_frames}\n"
                f"SHA-256：{outcome.sha256}"
            ),
            parent=self.master,
        )

    def _on_failure(self, exc: Exception) -> None:
        self._set_running(False)
        self.status.set("失败；未保留不完整的 fin.mp4")
        self._append_log(f"ERROR: {exc}")
        if isinstance(exc, BuildFailure):
            self._append_log(f"诊断目录: {exc.artifacts_dir}")
        messagebox.showerror(
            "生成失败",
            str(exc),
            parent=self.master,
        )

    def _open_output_folder(self) -> None:
        if self.last_output is None:
            return
        folder = self.last_output.parent
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo(
                "输出文件夹",
                str(folder),
                parent=self.master,
            )

    def _on_close(self) -> None:
        if self.running:
            messagebox.showwarning(
                "任务仍在运行",
                "请等待当前编码与校验完成后再关闭。",
                parent=self.master,
            )
            return
        self.master.destroy()


def main() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.title("Hidden Preview Builder")
    root.geometry("860x790")
    root.minsize(720, 680)
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    HiddenPreviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
