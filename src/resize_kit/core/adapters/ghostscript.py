"""Ghostscript adapter (Layer 0) — optional PDF image downsampling backend.

PyMuPDF/pikepdf handle the bulk of PDF work; Ghostscript is offered as an
alternative whole-document image-downsampling pass (DESIGN.md §5.3 / §9.2). It
is optional: if ``gs`` is absent the PDF handler simply uses its native path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from .process import run, which

log = get_logger(__name__)

# Ghostscript PDFSETTINGS presets, coarsest -> finest.
PDF_PRESETS = {
    "screen": "/screen",  # 72 dpi, smallest
    "ebook": "/ebook",  # 150 dpi
    "printer": "/printer",  # 300 dpi
    "prepress": "/prepress",  # 300 dpi, color preserving
}


class GhostscriptAdapter:
    def __init__(self, gs_path: Optional[str] = None) -> None:
        self.gs_path = gs_path or which("gs") or which("gswin64c") or "gs"

    def is_available(self) -> bool:
        return which(self.gs_path) is not None or Path(self.gs_path).exists()

    def downsample_pdf(
        self,
        input_path: Path,
        output_path: Path,
        *,
        preset: str = "ebook",
        color_dpi: Optional[int] = None,
        timeout: float = 600,
    ) -> None:
        """Re-distill a PDF, downsampling raster images. Vectors/text preserved."""
        cmd = [
            self.gs_path,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.5",
            f"-dPDFSETTINGS={PDF_PRESETS.get(preset, '/ebook')}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dDetectDuplicateImages=true",
        ]
        if color_dpi:
            cmd += [
                "-dDownsampleColorImages=true",
                "-dColorImageResolution=%d" % color_dpi,
                "-dDownsampleGrayImages=true",
                "-dGrayImageResolution=%d" % color_dpi,
            ]
        cmd += [f"-sOutputFile={output_path}", str(input_path)]
        run(cmd, tool="gs", timeout=timeout)
