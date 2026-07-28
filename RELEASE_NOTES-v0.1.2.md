# Hidden Preview Builder v0.1.2

这是一个 4K 长视频稳定性修复版本。

## 主要修复

- 隐藏预览段和公开视频 A 现在分别编码，再通过 concat demuxer 无损拼接，
  最后单独封装 Video A 音频。
- 移除会同时缓存两段 4K 视频的滤镜 concat，避免内存持续增长、系统内存
  耗尽或长视频处理中途失败。
- FFmpeg 自动查找只接受同一明确目录中的 `ffmpeg` 与 `ffprobe`，不会再被
  当前目录里残留的旧版 `ffmpeg.exe` 干扰。
- GUI 分别显示隐藏段、A 段、拼接和音频封装阶段，长任务进度更清楚。
- 发布脚本固定使用 PowerShell 7，避免旧版 Windows PowerShell 错误解码
  UTF-8 中文发布者元数据和随包中文文件名。

## 验证

- 单元测试、GUI 测试和 FFmpeg 端到端集成测试全部通过。
- 使用 145 秒、3840×2160、60fps 的实际工作流完成全流程验证。
- 实测编码内存稳定在约 4 GB，不再出现旧版约 15–25 GB 的持续增长。
- 默认 edit list 解码与忽略 edit list 的物理轨道解码均通过；公开 8722 帧，
  物理 17444 帧，音频保持 AAC-LC、48 kHz、立体声。
- full-portable EXE 自检会确认优先使用压缩包同目录的 FFmpeg/ffprobe。

普通用户请下载：

`HiddenPreviewBuilder-v0.1.2-windows-x64-full-portable.zip`

完整解压后运行 `HiddenPreviewBuilder.exe`。随包 FFmpeg/ffprobe 采用 GPL v3，
许可与源码入口位于 `third-party\ffmpeg\`。
