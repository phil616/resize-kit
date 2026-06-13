"""Layer 0 — external tool adapters.

Each adapter wraps one external executable (ffmpeg, soffice, gs, pngquant)
behind a stable, typed Python interface so that the layers above never touch
command-line strings or argv quoting directly.
"""

from __future__ import annotations

from .ffmpeg import FFmpegAdapter
from .ghostscript import GhostscriptAdapter
from .libreoffice import LibreOfficeAdapter
from .pngquant import PngquantAdapter
from .registry import ToolRegistry, ToolStatus, default_registry

__all__ = [
    "FFmpegAdapter",
    "GhostscriptAdapter",
    "LibreOfficeAdapter",
    "PngquantAdapter",
    "ToolRegistry",
    "ToolStatus",
    "default_registry",
]
