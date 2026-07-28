# Hidden Preview Video Builder

**发布人：教主　当前版本：v0.1.3**

一个面向 Windows 的实验性 MP4 工具：正常播放时只显示 Video A，同时在
物理视频轨前放置一段等长的图片或 Video B，用于研究进度条缩略图生成器是否
忽略 MP4 edit list。

项目来自本地 `ae-video-workflow` 的流程 4，但运行时不依赖 After Effects。
它提供一个简单的 Tkinter 图形界面，也保留可自动化的命令行入口。

## 它如何工作

物理视频轨：

```text
[适配到 Video A 的预览素材] + [Video A]
```

工具把视频 edit list 的公开起点设置到第二段，因此兼容 edit list 的播放器
只会播放 Video A。若某个平台的缩略图路径忽略 edit list，它可能采样前面的
预览素材；若平台应用或展平 edit list，它仍会采样 Video A。

**本工具只能验证本地 MP4 结构和解码结果，不能保证任何平台的缩略图行为。**

## 功能

- 图片或 Video B 均可作为隐藏预览；短视频自动循环，长视频自动裁切。
- 以 Video A 的名义帧率生成稳定 CFR；可严格拒绝异常时间戳，也可保持
  容器公开时长并自动补齐缺帧。
- 预览素材按修正后的 CFR、帧数、分辨率和时长适配。
- 三种画面适配：完整显示并补黑边、铺满并裁切、直接拉伸。
- 公开音轨只使用 Video A 的音频，并转为 AAC-LC。
- 修补并审计 `ctts`、`elst`、`mvhd` 和视频 `tkhd`。
- 分别按“应用 edit list”和“忽略 edit list”做完整解码与帧数验证。
- 成功后输出目录只留下 `fin.mp4`；诊断文件位于系统临时目录。
- 已存在的输出永不覆盖，失败时删除本次创建的不完整 MP4。
- 所有媒体处理都在本机完成，程序不上传文件。

## 运行 EXE

1. 下载 `HiddenPreviewBuilder-v0.1.3-windows-x64-full-portable.zip`。
2. 完整解压 ZIP，不要单独移动或删除其中的 `ffmpeg.exe`、`ffprobe.exe`。
3. 打开 `HiddenPreviewBuilder.exe`。
4. 选择 Video A、预览图片或 Video B、输出文件夹、画面适配方式和时间线
   处理方式。GUI 默认使用“保留公开时长，缺帧自动补帧”。
5. 点击“生成 fin.mp4”。

full-portable 包已附带同一构建的 FFmpeg 与 ffprobe，不需要另行安装。冻结版
程序优先使用 EXE 同目录中的这一对工具，因此不会意外调用 PATH 中的旧版本。

> 实测2分钟4K视频+静态图片用时6分钟,主要取决于电脑配置,别塞一个超长视频把自己卡死了

## 输入限制

Video A 必须：

- 恰好包含一个视频轨和一个音频轨；
- 能提供有效的名义帧率与逐帧时间戳；推荐模式会把缺帧或不连续时间戳转换为
  稳定 CFR 并保持容器公开时长，严格模式则直接停止；
- 宽和高均为偶数，以便输出 `yuv420p`；
- 使用程序和 FFmpeg 能读取的容器与编码。

输出文件名固定为 `fin.mp4`。程序不会覆盖已有文件。不同宽高比的素材必须明确
选择 `contain`、`cover` 或 `stretch`；图形界面会始终传入所选模式。

## 从源码运行

要求 Python 3.10+，运行时除 Python 标准库与 FFmpeg 外没有 Python 依赖。
从源码运行时需要自行准备同一目录中的 `ffmpeg` 与 `ffprobe`，可加入 `PATH`
或通过 `HIDDEN_PREVIEW_FFMPEG_DIR` 指定。

```powershell
.\run-dev.ps1
```

命令行安装与调用：

```powershell
python -m pip install -e .

hidden-preview-builder `
  --main-video "D:\media\video-a.mp4" `
  --preview-source "D:\media\preview.png" `
  --output "D:\output\fin.mp4" `
  --fit contain `
  --timeline-policy preserve-duration
```

`--keep-artifacts` 会把验证帧、manifest、容器审计和日志保留在系统临时目录。
失败时这些诊断文件始终保留，错误信息会给出绝对路径。

## 构建 Windows EXE

```powershell
.\build.ps1
```

脚本会：

1. 在项目内创建 `.venv`；
2. 安装 PyInstaller；
3. 运行单元测试和短视频集成测试；
4. 构建单文件窗口程序；
5. 执行打包后的自检。

产物：

```text
dist\HiddenPreviewBuilder.exe
```

`build.ps1` 只构建主程序 EXE；默认 GitHub 发布物则是下述 full-portable
ZIP。FFmpeg 与 ffprobe 作为独立文件放在 EXE 旁边，并不嵌入主程序。项目代码
仍采用 MIT License，随包 FFmpeg 构建单独采用 GPL v3，许可、构建配置与源码
入口位于 ZIP 的 `third-party\ffmpeg\`。本地 PyInstaller 产物默认没有代码
签名，Windows 可能显示未知发布者警告；正式发布者应使用自己的代码签名证书
签署 release。

生成可直接上传到 GitHub Release 的压缩包：

```powershell
pwsh -File .\package-release.ps1
```

产物位于 `release\`。唯一的默认程序包是
`HiddenPreviewBuilder-v0.1.3-windows-x64-full-portable.zip`，不再生成
slim 版本。ZIP 内含主程序、`ffmpeg.exe`、`ffprobe.exe`、简明说明、MIT
License、GPL v3 全文、FFmpeg 原始构建说明与源码入口。普通用户解压后先看
根目录的 `使用说明.txt`；旁边还会生成 ZIP 的 SHA-256 文件和发布 manifest。
若 FFmpeg 不在 PATH，可执行
`pwsh -File .\package-release.ps1 -FFmpegDir "D:\path\to\ffmpeg\bin"`。
发布打包要求 PowerShell 7，以确保 UTF-8 中文元数据和文件名不被旧版
Windows PowerShell 错误解码。
完整发布步骤见 [PUBLISHING.md](PUBLISHING.md)。

## 本地验证范围

成功状态 `PASS` 会检查：

- 正常 CFR 输入的公开帧数等于 Video A；修正异常时间线时，公开帧数按
  `容器公开时长 × 名义 fps` 取整，物理帧数始终为公开帧数两倍；
- fps、分辨率、公开时长和音频形状与 Video A 一致；
- 视频为 H.264 High / `yuv420p`，音频为 AAC-LC；
- 视频轨排在音频轨之前，track ID 为 1 / 2；
- 固定步长 `stts`、非负 `ctts` v0、原始首个 composition PTS 为 0；
- 单一正向视频 edit list，公开 movie / track duration 精确；
- 默认解码与 `-ignore_editlist 1` 解码都能完整完成；
- 关键物理帧和公开帧能够提取，并生成 SHA-256。

`PASS` 不包含平台侧上传或缩略图结果。

## 开源与贡献

项目代码采用 [MIT License](LICENSE)。请阅读
[CONTRIBUTING.md](CONTRIBUTING.md) 后提交改动。请只处理你有权使用的媒体，
并遵守目标平台的服务条款。
