# resize-kit

**企业级多格式有损压缩工具 · 精确目标体积控制**

resize-kit 可将图像、音频、视频、Office 文档（DOC/DOCX/PPT/PPTX）和 PDF 压缩到你
指定的目标——按比例、精确体积，或 `最小 ≤ 体积 ≤ 最大` 的区间——甚至能**无损地把文件
增大**到指定体积。它是设计文档 [`DESIGN.md`](./DESIGN.md) 的参考实现。

提供**命令行工具**（`resize-kit`）和 **PyQt5 桌面图形界面**（`resize-kit-gui`）。

> 版本：**v0.1.0** · 作者：phil616 · 仓库：<https://github.com/phil616/resize-kit>

---

## 功能亮点

- **四种目标模式** —— 按*比例*压缩、落入*体积区间*、命中*精确体积*（±容差），或*无损增大*到指定体积。
- **精确到字节。** 二分搜索把编码质量收敛到天花板之下，再用**格式合法填充**补到地板之上。
  `精确` 模式落在你设定的容差内（默认 ±1 KiB）。
- **绝不产出损坏文件。** 无法达到的目标会作为一等错误返回，并附带可达到的体积边界，而不是损坏的输出。
- **容器保真。** 内嵌媒体以**原文件名、原编码格式**回写，DOCX/PPTX 的关系引用与
  `[Content_Types].xml` 无需任何改动。
- **透明图像安全。** 始终保留 alpha 通道（默认调色板量化，亦可选通道分离法）。
- **无损增大。** 增大文件只注入解码器忽略的字节，像素 / 采样逐位不变。

---

## 架构

四层结构，依赖严格自上而下（见 `DESIGN.md` §2）：

```
 L3  调度门面            格式探测 · 隔离工作区 · 任务路由 · 清理
       │
 L2  复合格式处理器       OOXML(docx/pptx) · 遗留 Office(doc/ppt) · PDF
       │
 L1  原子压缩器          图像 · 音频 · 视频      ◄── 被每个 L2 处理器复用
       │
 L0  外部工具适配器       ffmpeg · LibreOffice · Ghostscript · pngquant
       └──────────── 尺寸控制器 SizeBandController + 填充（横切复用）────────────┘
```

尺寸控制器（二分搜天花板 + 填充补地板）与各格式的合法填充载体被**所有原子压缩器**
以及**复合处理器**共享——复合处理器通过搜索一个统一的"每资源质量旋钮"来收敛整篇文档。

源码结构：

```
src/resize_kit/
  core/
    adapters/   L0 —— ffmpeg、libreoffice、ghostscript、pngquant、工具注册表
    atomic/     L1 —— 图像、音频、视频压缩器
    handlers/   L2 —— ooxml、legacy_office、pdf
    sizing/     尺寸控制器 + 填充（横切）
    dispatcher.py, detect.py, workspace.py, models.py, …
  cli.py        命令行界面
  gui/          PyQt5 桌面应用
packaging/      PyInstaller 打包脚本（gui_entry.py, build_exe.py）
```

---

## 安装

resize-kit 使用 [uv](https://docs.astral.sh/uv/)，可在 **Windows、macOS、Linux** 上运行。
提交的 `uv.lock` 是跨平台通用锁文件，会自动为各平台选择正确的 wheel（例如 Windows 兼容的
`PyQt5-Qt5`），因此同一条命令到处可用：

```bash
uv sync --extra dev          # 创建 .venv 并安装全部依赖（含开发工具）
uv run resize-kit doctor     # 检查外部工具是否就绪
```

### 外部工具

| 工具          | 是否必需 | 用途                                            |
|---------------|:--------:|-------------------------------------------------|
| **ffmpeg**    | 必需     | 音频与视频的（重）压缩与探测                      |
| **LibreOffice**（`soffice`） | 可选 | 遗留 DOC/PPT ↔ DOCX/PPTX 转换           |
| **Ghostscript**（`gs`） | 可选 | PDF 图像降采样的备选后端                    |
| **pngquant**  | 可选     | 更优的 PNG 调色板量化                            |

`resize-kit doctor` 会报告各工具是否可用。图像 / PDF 处理无需可选工具（有原生回退）；
音视频需要 ffmpeg；遗留 DOC/PPT 需要 LibreOffice。

> **Windows 提示**：请单独安装上述外部工具并确保它们在 `PATH` 中：**ffmpeg/ffprobe**、
> **LibreOffice**（`soffice.exe`）、**Ghostscript**（`gswin64c.exe`，会被自动识别）。

---

## 命令行用法

```bash
# 把照片压进 150–200 KiB 区间
resize-kit compress photo.jpg --min 150KB --max 200KB -o photo.small.jpg

# 压缩到原始大小的一半
resize-kit compress slides.pptx --ratio 0.5

# 命中精确体积（±50 KiB 容差），用于满足上传限制
resize-kit compress clip.mp4 --exact 8MB --tolerance 50KB

# 把扫描版 PDF 整页栅格化以获得最大压缩
resize-kit compress scan.pdf --max 1MB --pdf-mode rasterize

# 在不改动任何像素的前提下，把图像增大到正好 900 KiB
resize-kit inflate icon.png --to 900KB

# 查看 resize-kit 的识别结果
resize-kit probe movie.mkv
resize-kit doctor
```

体积单位支持 `B`、`KB`/`KiB`、`MB`/`MiB`、`GB`/`GiB`（KB == KiB == 1024）。

**退出码：** `0` 落入区间 · `2` 目标不可达 · `3` 已完成但超出区间 · `1` 出错。

### 主要选项

| 选项              | 含义                                                       |
|-------------------|------------------------------------------------------------|
| `--ratio R`       | 压缩到原始大小的比例 `R`（0–1）                             |
| `--max / --min`   | 体积区间上 / 下界（任一可省略）                             |
| `--exact S`       | 精确目标体积，配合 `--tolerance` 使用                       |
| `--inflate S`     | 通过无损填充把文件增大到体积 `S`                            |
| `--pdf-mode`      | `multimedia`（保留文字/矢量）或 `rasterize`（仅图像）       |
| `--png-alpha`     | 透明 PNG 后端：`quantize`（默认）或 `channel_split`         |
| `--keep-ooxml`    | DOC/PPT 直接输出 DOCX/PPTX（更稳妥、可精确控制体积）        |
| `--no-downscale`  | 禁止降分辨率 / 降采样率                                     |
| `--no-pad`        | 禁止通过填充达到下界                                        |

---

## 图形界面（GUI）

```bash
uv run resize-kit-gui
```

界面为**中文**。选择文件（拖拽或浏览），选择目标模式，调整选项，点击**开始压缩**。
任务在后台线程运行并实时显示进度；结果区展示压缩前后体积、容器内逐资源明细，以及日志。
窗口底部显示版本号、作者与仓库链接。

---

## 打包为单文件可执行程序

使用 [PyInstaller](https://pyinstaller.org/) 把 GUI 打包成单个可执行文件：

```bash
uv sync --extra build                       # 安装 pyinstaller
uv run python packaging/build_exe.py        # 生成 dist/resize-kit-gui[.exe]

# 可选参数
uv run python packaging/build_exe.py --onedir    # 单目录（启动更快、便于排错）
uv run python packaging/build_exe.py --console    # 保留控制台（调试）
uv run python packaging/build_exe.py --clean      # 先清理缓存
```

产物位于 `dist/`：Windows 为 `resize-kit-gui.exe`，Linux 为 `resize-kit-gui`，
macOS 为 `resize-kit-gui.app`。

> 注意：ffmpeg / LibreOffice / Ghostscript 等外部工具**不会**被打包进 exe，
> 需在目标机器上安装并加入 `PATH`。

---

## 精确体积控制原理（DESIGN.md §6）

```
目标：min ≤ 体积 ≤ max
  1. 在质量旋钮上二分，找到体积 ≤ max 的最高质量点          （天花板）
  2. 若该点体积 ≥ min  → 完成
     否则               → 用格式合法填充补到下界             （地板）
  3. 若最大压缩后仍 > max 且允许降分辨率 → 降一档后重试
     否则 → 报告"区间不可达"并附可达到的体积边界
```

**填充载体**（解码器忽略的字节）——精确到字节：

| 格式          | 载体                                     |
|---------------|------------------------------------------|
| JPEG          | `COM` 注释段（可串联多段）               |
| PNG           | 私有辅助 chunk `rkPd`                     |
| MP4/MOV/M4A   | 顶层 `free` box                          |
| MP3           | ID3v2 标签填充区                         |
| WAV           | 私有 RIFF 子块                           |
| PDF           | `%%EOF` 之后的注释                        |
| DOCX/PPTX/XLSX| ZIP 末尾归档注释                          |

`inflate`（DESIGN.md §7）使用同一套机制：可见内容不变，仅增大字节数。

---

## 支持的格式

| 输入                | 处理路径                                                   |
|---------------------|------------------------------------------------------------|
| JPEG/PNG/BMP/GIF/TIFF/WEBP | 有损重编码；保留 alpha 通道                          |
| MP3/AAC/M4A/OGG/OPUS/FLAC/WAV | ffmpeg，编码格式不变，码率/质量旋钮              |
| MP4/MKV/MOV/WEBM/AVI | ffmpeg，容器不变，CRF 旋钮                                |
| DOCX/PPTX/XLSX      | 解压 → 压缩媒体 → 重新打包（零结构变更）                    |
| DOC/PPT             | LibreOffice → DOCX/PPTX → 压缩 → 转回原格式                 |
| PDF                 | 多媒体模式（保留文字/矢量）**或** 栅格化模式（仅图像）      |

---

## 版本号体系

遵循[语义化版本](https://semver.org/lang/zh-CN/) `主版本.次版本.修订号`：

- **修订号**（PATCH）：向后兼容的缺陷修复。
- **次版本**（MINOR）：向后兼容的新功能。
- **主版本**（MAJOR）：当公开 API / 行为正式稳定时升至 `1.0.0`。

当前版本 **v0.1.0**（首个功能完整版本）。版本号统一定义在 `src/resize_kit/version.py`，
同时驱动 CLI 的 `--version`、GUI 底部信息栏与打包元数据。

---

## 开发

```bash
uv run pytest                      # 全部测试（缺少外部工具的用例会自动跳过）
uv run pytest -m "not external"    # 纯 Python 离线子集
python assets/fetch_samples.py     # 下载公开样本并对其运行压缩引擎
```

测试套件是自洽的：测试夹具在运行时即时生成（无需联网）。
`assets/fetch_samples.py` 是针对真实公开文件的独立集成演示。

---

## 设计说明与已知限制

- **DOC/PPT 往返**经 LibreOffice 转换可能产生轻微排版漂移，且精确字节目标只能近似
  （OLE2 没有安全的填充载体）。需要精确、保结构输出时请用 `--keep-ooxml`。
- **容器体积搜索**每一步都会重新编码全部内嵌媒体，因此媒体很多的大文档耗时较长（设计上无并发）。
- 安装了 **pngquant** 时优先用它处理 PNG；否则使用 Pillow 的保 alpha 量化器。
- ZIP 的地板填充受 64 KiB 归档注释上限约束。

完整设计原理见 [`DESIGN.md`](./DESIGN.md)。
