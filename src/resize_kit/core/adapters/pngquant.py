"""pngquant adapter (Layer 0) — optional superior PNG backend.

DESIGN.md §4.1 names palette quantization (pngquant) as the *preferred* PNG
backend when available: it natively preserves alpha and compresses far better
than the channel-separation fallback. This adapter is entirely optional; the
ImageCompressor checks :meth:`is_available` and falls back if absent (as on this
build host, where pngquant is not installed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from .process import run, which

log = get_logger(__name__)


class PngquantAdapter:
    def __init__(self, pngquant_path: Optional[str] = None) -> None:
        self.pngquant_path = pngquant_path or which("pngquant") or "pngquant"

    def is_available(self) -> bool:
        return which(self.pngquant_path) is not None or Path(self.pngquant_path).exists()

    def quantize(
        self,
        input_path: Path,
        output_path: Path,
        *,
        quality_min: int = 0,
        quality_max: int = 80,
        speed: int = 3,
        colors: int = 256,
        timeout: float = 120,
    ) -> bool:
        """Quantize a PNG to a palette. Returns True on success.

        pngquant exits 99 when it cannot meet ``quality_min``; we treat that as a
        soft failure (caller falls back) rather than an exception.
        """
        cmd = [
            self.pngquant_path,
            "--force",
            "--strip",
            f"--speed={speed}",
            f"--quality={quality_min}-{quality_max}",
            str(colors),
            "--output",
            str(output_path),
            str(input_path),
        ]
        result = run(cmd, tool="pngquant", timeout=timeout, check=False)
        if result.returncode == 0 and output_path.exists():
            return True
        log.debug("pngquant could not meet quality target (exit=%s)", result.returncode)
        return False
