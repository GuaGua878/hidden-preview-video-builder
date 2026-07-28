# Contributing

感谢参与 Hidden Preview Video Builder。

## 开发环境

- Windows 10/11
- Python 3.10+
- 同一目录中的 ffmpeg 与 ffprobe，且 FFmpeg 含 `libx264` 和 AAC 编码器

从源码启动：

```powershell
.\run-dev.ps1
```

运行测试：

```powershell
Push-Location .\src
python -m unittest discover -s ..\tests -v
Pop-Location
```

构建完整 EXE：

```powershell
.\build.ps1
```

## 改动要求

- 保持输出文件名为 `fin.mp4`，且不得静默覆盖已有输出。
- 辅助文件必须写入系统临时目录，成功后默认安全清理。
- 不要把 FFmpeg 二进制、真实媒体、绝对本机路径或验证输出提交到仓库。
- 不要将 Workflow 2 的 NVENC 参数带入本项目；容器修补依赖当前
  `libx264` 产生的时间结构。
- 新行为需要覆盖单元测试；容器或编码路径改动必须通过短视频集成测试。
- 文档不得承诺任何平台一定使用隐藏预览。

提交 issue 时，请附上错误文本、FFmpeg 版本、Video A 的公开参数，以及程序
报告的临时诊断目录结构。真实媒体仅在你确认有权分享时提供。
