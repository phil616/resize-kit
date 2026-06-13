# 架构

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

尺寸控制器（二分搜天花板 + 填充补地板）与各格式的合法填充载体被**所有原子压缩器**以及**复合处理器**共享——复合处理器通过搜索一个统一的"每资源质量旋钮"来收敛整篇文档。

## 源码结构

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

## 设计原则

1. **分层与原子化**：图像、音频、视频压缩是三个"原子能力"，被所有复合格式（Office、PDF）复用，绝不重复实现。
2. **格式保真（容器层面）**：嵌入到容器内的媒体，压缩前后保持原编码格式不变（mp3 仍是 mp3、mp4 仍是 mp4、png 仍是 png），从而不破坏文档对资源的引用结构。
3. **目标可控**：支持"精确大小区间"（如 150KB ≤ size ≤ 200KB），既能向下压，也能向上补，最终落在区间内。
4. **归一化优先**：遗留专有二进制格式（DOC/PPT）先归一化为对应的 OOXML（DOCX/PPTX）再处理，处理完再转回。
5. **可失败、可回退**：任何无法满足目标的任务都返回明确的"不可行原因"，而不是产出损坏文件。

完整设计文档见 [`DESIGN.md`](../DESIGN.md)。
