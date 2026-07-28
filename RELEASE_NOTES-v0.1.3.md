# Hidden Preview Builder v0.1.3

这是一个桌面端性能优化版本，输出结构和画质参数保持不变。

## 性能优化

- Video A 的逐帧时间轴检查同时统计准确帧数，移除一次完整输入扫描。
- 完整解码校验同时统计公开帧和物理帧，移除额外的
  `ffprobe -count_frames` 遍历。
- 临时视频段不再执行 `faststart`。
- concat demuxer 与 Video A 音频封装合并为一个阶段，不再创建
  joined-video 中间文件。
- MP4 容器使用 mmap 验证，只写入必要的小范围字段，然后移动为最终文件。
- 严格 CFR 的 Video A 跳过冗余 `fps` 和同尺寸 `scale` 滤镜。

## 实测验证

- 使用 145 秒、3840×2160、60fps 的真实工作流完成全流程验证。
- 总耗时由约 12 分 19 秒降至约 6 分 44 秒，缩短约 45%。
- 新旧成品均为公开 8722 帧、物理 17444 帧，SHA-256 完全一致。
- 编码内存稳定在约 4 GB。
- 单元、GUI、端到端集成测试和 full-portable EXE 自检全部通过。

## 使用提醒

实测2分钟4K视频+静态图片用时6分钟,主要取决于电脑配置,别塞一个超长视频把自己卡死了

普通用户请下载：

`HiddenPreviewBuilder-v0.1.3-windows-x64-full-portable.zip`

完整解压后运行 `HiddenPreviewBuilder.exe`。请保持 `ffmpeg.exe` 和
`ffprobe.exe` 与主程序位于同一目录。
