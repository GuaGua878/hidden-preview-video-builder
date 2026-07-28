# Third-party notices

Hidden Preview Video Builder 的源码与程序自身采用 MIT License。

## FFmpeg

本仓库不提交 FFmpeg 二进制，但项目生成的默认 full-portable release 包会
在主程序旁附带 `ffmpeg.exe` 与 `ffprobe.exe`。v0.1.0 使用的构建信息为：

- 构建：`2025-03-31-git-35c091f4b7-essentials_build-www.gyan.dev`
- 许可证：GPL v3
- 对应 FFmpeg 源码：
  <https://github.com/FFmpeg/FFmpeg/commit/35c091f4b7>
- 构建发布方：<https://www.gyan.dev/ffmpeg/builds/>

ZIP 内的 `third-party/ffmpeg/LICENSE-GPLv3.txt` 是随原构建提供的 GPL v3
全文，`README-build.txt` 是原始构建说明和配置，`SOURCE.txt` 汇总了来源
入口。该构建启用了 `--enable-gpl`、`--enable-version3`、静态链接和
`libx264`，因此随包二进制按 GPL v3 分发。

FFmpeg 及其可选组件适用各自许可证。本项目的 MIT License 只覆盖本项目代码，
不覆盖 `ffmpeg.exe`、`ffprobe.exe` 或其组成部分。二次分发者仍应审查其实际
采用的 FFmpeg 构建及对应源码义务；不要从 full-portable 包中删除许可证、
原始构建说明或源码入口。

## PyInstaller

Windows EXE 使用 PyInstaller 构建。PyInstaller 的 bootloader 与构建产物
适用 PyInstaller 项目公布的许可条款；构建依赖版本记录在
`requirements-dev.txt`。
