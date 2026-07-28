# GitHub 发布步骤

发布人：教主

当前版本：v0.1.0

## 1. 最终检查

```powershell
.\package-release.ps1
git status --short
```

若 FFmpeg 不在 PATH，改用：

```powershell
.\package-release.ps1 -FFmpegDir "D:\path\to\ffmpeg\bin"
```

确认测试、EXE 自检、full-portable 同目录工具解析、Windows 文件属性和
release manifest 全部通过。打包脚本只接受同时包含 `ffmpeg.exe` 与
`ffprobe.exe` 的目录，并要求当前构建为启用 `libx264` 的 GPL v3 静态构建。

## 2. 提交源码

在 GitHub 新建空的公开仓库，不要勾选自动创建 README、LICENSE 或
`.gitignore`。随后在本项目中配置该仓库为 `origin`，检查目标地址无误后提交
并推送 `main`。

提交与 tag 建议：

```powershell
git add .
git commit -m "Release v0.1.0"
git tag -a v0.1.0 -m "Hidden Preview Builder v0.1.0"
git push -u origin main
git push origin v0.1.0
```

执行前请先确认 Git 的邮箱、远程仓库地址和 GitHub 账号均正确。

## 3. 创建 GitHub Release

1. 选择 tag `v0.1.0`。
2. 标题填写 `Hidden Preview Builder v0.1.0`。
3. 正文复制 `RELEASE_NOTES-v0.1.0.md`。
4. 上传唯一的默认程序包
   `release\HiddenPreviewBuilder-v0.1.0-windows-x64-full-portable.zip`。
5. 同时上传对应 `.sha256.txt` 和 `.manifest.json`。
6. 不生成或上传 slim 版本。
7. 发布前确认 ZIP 根目录包含 EXE、`ffmpeg.exe` 和 `ffprobe.exe`，且
   `third-party\ffmpeg\` 中包含 GPL v3 全文、原始构建说明和源码入口。
8. 确认包内没有真实测试媒体、本机绝对路径或自检临时报告。

GitHub 自动生成的 Source code ZIP/TAR 即为源码包，不要把 `.venv`、`build`、
`dist` 或 `release` 目录提交到仓库。
