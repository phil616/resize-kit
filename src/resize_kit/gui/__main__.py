"""Entry point for ``resize-kit-gui`` and ``python -m resize_kit.gui``."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
