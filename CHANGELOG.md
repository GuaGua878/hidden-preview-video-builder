# Changelog

## [0.1.0] - 2026-07-27

- 首个公开版本。
- 提供中文 Tkinter GUI 和命令行入口。
- 支持图片或循环 Video B 作为隐藏物理预览段。
- 保留 Video A 的公开帧数、CFR、分辨率、时长和音频形状。
- 修补并验证 MP4 `ctts`、`elst`、`mvhd` 与视频 `tkhd`。
- 分别执行默认路径和忽略 edit list 路径的完整解码验证。
- 默认成功后清理临时产物，失败时保留诊断目录。
- 提供单文件 Windows x64 EXE 构建，以及唯一默认的 full-portable GitHub
  Release 包。
- full-portable 包随附 FFmpeg/ffprobe、GPL v3 全文、原始构建信息与源码
  入口；冻结版优先使用 EXE 同目录工具。
- full-portable 包根目录提供面向普通用户的中文 `使用说明.txt`。
- 修复异常 `avg_frame_rate` 分数导致 MP4 timescale 溢出的错误。
- 新增逐帧 PTS 检查，以及“保持公开时长并自动补帧”的时间线修正策略。
