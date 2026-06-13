"""Tool discovery & health reporting ("doctor").

A single :class:`ToolRegistry` is shared across the engine so adapters are
constructed once and their availability is reported coherently to the CLI
``doctor`` command and the GUI's status panel.

Required vs. optional is explicit: the engine still runs without Ghostscript or
pngquant (PDF/PNG have native fallbacks), but image/audio/video work needs
ffmpeg, and legacy DOC/PPT needs soffice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...logging_config import get_logger
from ..exceptions import ToolNotFoundError
from .ffmpeg import FFmpegAdapter
from .ghostscript import GhostscriptAdapter
from .libreoffice import LibreOfficeAdapter
from .pngquant import PngquantAdapter

log = get_logger(__name__)


@dataclass(slots=True)
class ToolStatus:
    name: str
    available: bool
    required: bool
    path: Optional[str]
    purpose: str

    @property
    def ok(self) -> bool:
        return self.available or not self.required


class ToolRegistry:
    """Lazily-constructed, shared registry of Layer 0 adapters."""

    def __init__(self) -> None:
        self.ffmpeg = FFmpegAdapter()
        self.libreoffice = LibreOfficeAdapter()
        self.ghostscript = GhostscriptAdapter()
        self.pngquant = PngquantAdapter()

    # --- health -------------------------------------------------------------------

    def statuses(self) -> list[ToolStatus]:
        return [
            ToolStatus(
                name="ffmpeg",
                available=self.ffmpeg.is_available(),
                required=True,
                path=self.ffmpeg.ffmpeg_path,
                purpose="Audio & video (re)compression",
            ),
            ToolStatus(
                name="soffice",
                available=self.libreoffice.is_available(),
                required=False,
                path=self.libreoffice.soffice_path,
                purpose="Legacy DOC/PPT <-> DOCX/PPTX conversion",
            ),
            ToolStatus(
                name="ghostscript",
                available=self.ghostscript.is_available(),
                required=False,
                path=self.ghostscript.gs_path,
                purpose="Optional PDF image downsampling backend",
            ),
            ToolStatus(
                name="pngquant",
                available=self.pngquant.is_available(),
                required=False,
                path=self.pngquant.pngquant_path,
                purpose="Optional superior PNG quantization backend",
            ),
        ]

    def require(self, name: str) -> None:
        """Raise :class:`ToolNotFoundError` if a named tool is required but absent."""
        for status in self.statuses():
            if status.name == name and not status.available:
                hint = _INSTALL_HINTS.get(name)
                raise ToolNotFoundError(name, hint=hint)

    def healthy(self) -> bool:
        return all(s.ok for s in self.statuses())


_INSTALL_HINTS = {
    "ffmpeg": "Install FFmpeg and ensure 'ffmpeg'/'ffprobe' are on PATH.",
    "soffice": "Install LibreOffice; the 'soffice' binary must be on PATH.",
    "ghostscript": "Install Ghostscript ('gs') for the optional PDF backend.",
    "pngquant": "Install pngquant for higher-quality PNG compression.",
}

# Process-wide shared instance. Adapters hold no mutable per-job state, so this
# is safe to share; per-job isolation happens in the workspace layer.
_DEFAULT: Optional[ToolRegistry] = None


def default_registry() -> ToolRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ToolRegistry()
    return _DEFAULT
