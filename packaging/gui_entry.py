"""PyInstaller entry point for the GUI.

PyInstaller analyses a *script*, not a package, so this entry uses absolute
imports (a relative ``from .app import main`` would fail outside a package
context). ``build_exe.py`` adds ``src`` to the analysis path so ``resize_kit``
is importable.
"""

from __future__ import annotations

import sys

from resize_kit.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
