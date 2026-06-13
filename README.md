# resize-kit

**企业级多格式有损压缩工具 · 精确目标体积控制**

resize-kit 可将图像、音频、视频、Office 文档（DOC/DOCX/PPT/PPTX）和 PDF 压缩到你指定的目标——按比例、精确体积，或 `最小 ≤ 体积 ≤ 最大` 的区间——甚至能**无损地把文件增大**到指定体积。

提供**命令行工具**（`resize-kit`）和 **PyQt5 桌面图形界面**（`resize-kit-gui`）。

> 版本：**v0.1.0** · 作者：phil616 · 仓库：<https://github.com/phil616/resize-kit>

---

## 快速开始

```bash
uv sync --extra dev
uv run resize-kit doctor     # 检查外部工具
uv run resize-kit compress photo.jpg --min 150KB --max 200KB -o out.jpg
```

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/installation.md`](docs/installation.md) | 安装与外部工具配置 |
| [`docs/usage-cli.md`](docs/usage-cli.md) | 命令行用法与选项 |
| [`docs/usage-gui.md`](docs/usage-gui.md) | 图形界面使用 |
| [`docs/architecture.md`](docs/architecture.md) | 四层架构与源码结构 |
| [`docs/design.md`](docs/design.md) | 精确体积控制原理与填充载体 |
| [`docs/supported-formats.md`](docs/supported-formats.md) | 支持的格式 |
| [`docs/packaging.md`](docs/packaging.md) | 打包为单文件可执行程序 |
| [`docs/development.md`](docs/development.md) | 开发、测试与版本号 |
| [`DESIGN.md`](./DESIGN.md) | 完整技术设计文档 |
