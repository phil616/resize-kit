#!/usr/bin/env python3
"""将 resize-kit GUI 打包成单个可执行文件（PyInstaller）。

用法
----
    # 安装打包依赖后运行（推荐）
    uv sync --extra build
    uv run python packaging/build_exe.py

    # 可选参数
    python packaging/build_exe.py --onedir    # 打包成单目录（启动更快，便于排错）
    python packaging/build_exe.py --console    # 保留控制台窗口（调试用）
    python packaging/build_exe.py --clean      # 先清理 PyInstaller 缓存

产物
----
    Windows : dist/resize-kit-gui.exe
    Linux   : dist/resize-kit-gui
    macOS   : dist/resize-kit-gui.app（--windowed 时）

说明：ffmpeg / LibreOffice / Ghostscript 等外部工具**不会**被打包进 exe，
需在目标机器上单独安装并加入 PATH（运行后可在界面顶部或 `resize-kit doctor` 查看）。
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ENTRY = Path(__file__).resolve().parent / "gui_entry.py"
APP_NAME = "resize-kit-gui"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a single-file resize-kit GUI executable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--onedir", action="store_true",
                        help="one-folder build instead of one-file")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window (debugging)")
    parser.add_argument("--clean", action="store_true",
                        help="clean PyInstaller caches before building")
    args = parser.parse_args(argv)

    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "PyInstaller 未安装。请先运行：  uv sync --extra build",
            file=sys.stderr,
        )
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(ENTRY),
        "--name", APP_NAME,
        "--noconfirm",
        "--paths", str(SRC),
        # 这两个包含二进制扩展/数据文件，显式收集以避免运行期缺失。
        "--collect-all", "pikepdf",
        "--collect-all", "pymupdf",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
    ]
    cmd.append("--onedir" if args.onedir else "--onefile")
    cmd.append("--console" if args.console else "--windowed")
    if args.clean:
        cmd.append("--clean")

    print("运行：", " ".join(cmd), "\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\n❌ 打包失败。", file=sys.stderr)
        return result.returncode

    suffix = ".exe" if sys.platform == "win32" else ""
    exe = ROOT / "dist" / (APP_NAME + suffix)
    print(f"\n✅ 打包完成：{exe}")
    print("提示：ffmpeg / LibreOffice / Ghostscript 等外部工具未打包，")
    print("      请在目标机器上安装并加入 PATH。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
