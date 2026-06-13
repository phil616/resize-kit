"""Common base for the atomic compressors (DESIGN.md §3.2).

Defines the :class:`AtomicCompressor` contract and a shared
:class:`CompressorOptions` bag. Each concrete compressor is constructed once
with a :class:`~resize_kit.core.adapters.registry.ToolRegistry` and a
:class:`~resize_kit.core.sizing.controller.SizeBandController`, then reused for
many files (it holds no per-file mutable state).
"""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..adapters.registry import ToolRegistry, default_registry
from ..media_type import FileFormat, MediaClass
from ..models import CompressionResult, CompressionTarget
from ..sizing.controller import SizeBandController

ProgressFn = Callable[[str], None]


@dataclass(slots=True)
class CompressorOptions:
    """Tunables shared by the atomic compressors.

    Defaults reflect the DESIGN.md stance: lossy first, compression-rate first.
    """

    # Image
    png_alpha_strategy: str = "quantize"  # "quantize" | "channel_split"
    jpeg_min_quality: int = 5
    jpeg_max_quality: int = 95
    # Video
    video_min_crf: int = 20
    video_max_crf: int = 40
    # Audio
    audio_min_bitrate_kbps: int = 24
    # Downscale behaviour (shared)
    downscale_factor: float = 0.8
    max_downscale_steps: int = 6
    min_image_dimension: int = 16


class AtomicCompressor(ABC):
    """Uniform interface for the three atomic abilities."""

    media_class: MediaClass = MediaClass.UNKNOWN

    def __init__(
        self,
        *,
        registry: Optional[ToolRegistry] = None,
        controller: Optional[SizeBandController] = None,
        options: Optional[CompressorOptions] = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.controller = controller or SizeBandController()
        self.options = options or CompressorOptions()

    def supports(self, media_class: MediaClass) -> bool:
        return media_class == self.media_class

    @abstractmethod
    def compress(
        self,
        input_path: Path,
        target: CompressionTarget,
        *,
        output_path: Optional[Path] = None,
        work: Optional[Path] = None,
        out_format: Optional[FileFormat] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> CompressionResult:
        """Compress ``input_path`` toward ``target`` (precise, single-file).

        Used for standalone media where exact size targeting matters; internally
        runs the :class:`SizeBandController`.

        Args:
            output_path: where to write the result. Defaults to a sibling temp.
            work: scratch directory for intermediate candidates.
            out_format: force a specific output format (containers require the
                embedded media to keep its original format). Defaults to the
                input's detected format.
            on_progress: optional callback receiving human-readable progress lines.
        """

    @abstractmethod
    def encode_quality(
        self,
        input_path: Path,
        quality: int,
        *,
        output_path: Path,
        work: Path,
        out_format: Optional[FileFormat] = None,
    ) -> Path:
        """Single-shot encode at a unified 1..100 quality knob (no size search).

        This is the primitive container handlers iterate over: ``quality`` spans
        *both* resolution and codec quality so that higher quality reliably means
        a larger file (monotonic), and it can never fail with an unreachable
        target the way :meth:`compress` can. Returns the written path.
        """

    # --- shared helpers ----------------------------------------------------------

    @staticmethod
    def _ensure_work(work: Optional[Path]) -> Path:
        if work is not None:
            work.mkdir(parents=True, exist_ok=True)
            return work
        return Path(tempfile.mkdtemp(prefix="rk_atomic_"))


def lerp(low: float, high: float, t: float) -> float:
    """Linear interpolation; ``t`` in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return low + (high - low) * t
