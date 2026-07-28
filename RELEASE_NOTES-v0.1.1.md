# Hidden Preview Builder v0.1.1

这是一个时间线兼容性修复版本。

## 主要修复

- 修复异常 `avg_frame_rate` 分数导致 MP4 timescale 过大并在分析阶段失败的
  问题。
- 新增逐帧 PTS 检查，可识别时间戳跳变、异常帧时长和缺失帧位。
- 新增“保留公开时长，缺帧自动补帧”策略，并设为 GUI 推荐默认值。
- 保留严格模式，遇到不规则时间线时可选择直接停止。
- 在 manifest 和界面结果中记录源帧数、目标帧数与时间线修正信息。

## 验证

- 12 项单元与 FFmpeg 集成测试全部通过。
- 已使用触发旧版 timescale 溢出的实际输入复现并验证修复。
- full-portable EXE 自检通过，且确认优先使用同目录的 FFmpeg/ffprobe。

普通用户请下载：

`HiddenPreviewBuilder-v0.1.1-windows-x64-full-portable.zip`

完整解压后运行 `HiddenPreviewBuilder.exe`。随包 FFmpeg/ffprobe 采用 GPL v3，
许可与源码入口位于 `third-party\ffmpeg\`。
