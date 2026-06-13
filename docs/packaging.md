# 打包为单文件可执行程序

使用 [PyInstaller](https://pyinstaller.org/) 把 GUI 打包成单个可执行文件：

```bash
uv sync --extra build                       # 安装 pyinstaller
uv run python packaging/build_exe.py        # 生成 dist/resize-kit-gui[.exe]

# 可选参数
uv run python packaging/build_exe.py --onedir    # 单目录（启动更快、便于排错）
uv run python packaging/build_exe.py --console   # 保留控制台（调试）
uv run python packaging/build_exe.py --clean     # 先清理缓存
```

产物位于 `dist/`：Windows 为 `resize-kit-gui.exe`，Linux 为 `resize-kit-gui`，macOS 为 `resize-kit-gui.app`。

> 注意：ffmpeg / LibreOffice / Ghostscript 等外部工具**不会**被打包进 exe，需在目标机器上安装并加入 `PATH`。
