# Changelog

## [0.1.3] - 2026-07-28

- Video A 的逐帧时间轴检查同时作为权威帧数来源，移除一次完整输入扫描。
- 输出完整解码同时统计公开帧和物理帧，移除两次 `ffprobe -count_frames`
  完整遍历。
- 临时视频段不再执行 `faststart`；concat demuxer 与 Video A 音频封装合并
  为一次 FFmpeg 运行，不再生成 joined-video 中间文件。
- MP4 容器改用 mmap 验证并只写入四个小范围补丁，随后移动为最终输出，
  不再完整复制数百 MB 文件。
- 严格 CFR 的 Video A 跳过冗余 `fps` 和同尺寸 `scale` 滤镜。
- 真实 4K 工作流总耗时由约 12 分 19 秒降至约 6 分 44 秒，输出与旧版
  SHA-256 完全一致。
- 用户说明增加长视频性能提醒。

## [0.1.2] - 2026-07-28

- 将隐藏预览段和公开视频 A 改为分段编码，再无损拼接并单独封装音频，
  避免长时 4K 素材被滤镜 concat 整段缓存造成的巨量内存占用。
- FFmpeg 自动解析改为只遍历明确的 PATH 目录，不再受当前工作目录中旧版
  `ffmpeg.exe` 干扰，并继续要求 `ffmpeg` 与 `ffprobe` 成对存在。
- GUI 显示预览段编码、A 段编码、拼接和音频封装的独立进度阶段。
- 新增分段编码结构与工具解析回归测试。
- 发布打包脚本明确要求 PowerShell 7，防止 Windows PowerShell 5.1 损坏
  UTF-8 中文发布者元数据与随包文件名。

## [0.1.1] - 2026-07-27

- 修复异常 `avg_frame_rate` 分数导致 MP4 timescale 溢出的错误。
- 新增逐帧 PTS 检查，可识别时间戳跳变、时长异常和缺失帧位。
- 新增严格模式和“保持公开时长并自动补帧”两种时间线策略。
- GUI 默认使用推荐的自动修正策略，并在结果中显示源帧与缺帧信息。

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
