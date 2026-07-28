# Hidden Preview Builder v0.1.0

发布人：教主

首个 Windows x64 实验版本。它将图片或 Video B 适配成与 Video A 等长的
物理预览段，并通过 MP4 edit list 让正常播放从 Video A 开始。

## 下载

默认且唯一的程序包是
`HiddenPreviewBuilder-v0.1.0-windows-x64-full-portable.zip`。完整解压后
直接运行 `HiddenPreviewBuilder.exe`。

包内已附带 `ffmpeg.exe` 与 `ffprobe.exe`，无需另外安装。请保留它们与主
程序在同一目录。随包 FFmpeg 为 GPL v3 构建，许可、原始构建说明和源码入口
位于 `third-party\ffmpeg\`；项目代码本身采用 MIT License。具体用法见
压缩包根目录的 `使用说明.txt` 和 `QUICKSTART.zh-CN.md`。

## 验证

- Windows 单文件 GUI 自检通过。
- 10 项测试通过，包含便携工具优先级、自检报告、GUI 说明/发布人检查与真实
  H.264/AAC 短视频端到端容器验证。
- 解压后的 EXE 已确认实际解析同目录的 FFmpeg/ffprobe。
- 发布包附带 SHA-256 文件。

## 限制

本地 `PASS` 只证明 MP4 结构、公开/物理帧数和双路径解码符合预期，不保证
任何平台的进度条缩略图一定采用隐藏预览。当前 EXE 未做数字签名，Windows
可能显示“未知发布者”。
