# 安装

resize-kit 使用 [uv](https://docs.astral.sh/uv/)，可在 **Windows、macOS、Linux** 上运行。提交的 `uv.lock` 是跨平台通用锁文件，会自动为各平台选择正确的 wheel。

```bash
uv sync --extra dev          # 创建 .venv 并安装全部依赖（含开发工具）
uv run resize-kit doctor     # 检查外部工具是否就绪
```

## 外部工具

| 工具 | 是否必需 | 用途 |
|---|---|---|
| **ffmpeg** | 必需 | 音频与视频的（重）压缩与探测 |
| **LibreOffice**（`soffice`） | 可选 | 遗留 DOC/PPT ↔ DOCX/PPTX 转换 |
| **Ghostscript**（`gs`） | 可选 | PDF 图像降采样的备选后端 |
| **pngquant** | 可选 | 更优的 PNG 调色板量化 |

`resize-kit doctor` 会报告各工具是否可用。图像 / PDF 处理无需可选工具（有原生回退）；音视频需要 ffmpeg；遗留 DOC/PPT 需要 LibreOffice。

> **Windows 提示**：请单独安装上述外部工具并确保它们在 `PATH` 中：**ffmpeg/ffprobe**、**LibreOffice**（`soffice.exe`）、**Ghostscript**（`gswin64c.exe`，会被自动识别）。
