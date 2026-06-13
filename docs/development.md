# 开发

```bash
uv run pytest                      # 全部测试（缺少外部工具的用例会自动跳过）
uv run pytest -m "not external"    # 纯 Python 离线子集
python assets/fetch_samples.py     # 下载公开样本并对其运行压缩引擎
```

测试套件是自洽的：测试夹具在运行时即时生成（无需联网）。`assets/fetch_samples.py` 是针对真实公开文件的独立集成演示。

## 设计说明与已知限制

- **DOC/PPT 往返**经 LibreOffice 转换可能产生轻微排版漂移，且精确字节目标只能近似（OLE2 没有安全的填充载体）。需要精确、保结构输出时请用 `--keep-ooxml`。
- **容器体积搜索**每一步都会重新编码全部内嵌媒体，因此媒体很多的大文档耗时较长（设计上无并发）。
- 安装了 **pngquant** 时优先用它处理 PNG；否则使用 Pillow 的保 alpha 量化器。
- ZIP 的地板填充受 64 KiB 归档注释上限约束。

## 版本号体系

遵循[语义化版本](https://semver.org/lang/zh-CN/) `主版本.次版本.修订号`：

- **修订号**（PATCH）：向后兼容的缺陷修复。
- **次版本**（MINOR）：向后兼容的新功能。
- **主版本**（MAJOR）：当公开 API / 行为正式稳定时升至 `1.0.0`。

当前版本 **v0.1.0**（首个功能完整版本）。版本号统一定义在 `src/resize_kit/version.py`，同时驱动 CLI 的 `--version`、GUI 底部信息栏与打包元数据。
