"""Shared base for container handlers.

Holds the three atomic compressors (created once, reused for every embedded
asset) and the per-asset compression helper that enforces the DESIGN.md §8
resilience rule: a single broken/unsupported asset is logged and skipped, never
aborting the whole document.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ...logging_config import get_logger
from ..adapters.registry import ToolRegistry, default_registry
from ..atomic.audio import AudioCompressor
from ..atomic.base import AtomicCompressor, CompressorOptions
from ..atomic.image import ImageCompressor
from ..atomic.video import VideoCompressor
from ..detect import detect_media_class
from ..exceptions import ResizeKitError
from ..media_type import FileFormat, MediaClass
from ..models import AssetResult, CompressionResult, CompressionTarget
from ..sizing.controller import SizeBandController

log = get_logger(__name__)

ProgressFn = Callable[[str], None]


@dataclass(slots=True)
class HandlerOptions:
    """Container-level tunables."""

    compressor_options: CompressorOptions = None  # type: ignore[assignment]
    # Container-level size convergence is more expensive (re-encodes every asset
    # per step), so it uses a tighter iteration budget than the atomic level.
    container_max_iterations: int = 9

    def __post_init__(self) -> None:
        if self.compressor_options is None:
            self.compressor_options = CompressorOptions()


class ContainerHandler(ABC):
    def __init__(
        self,
        *,
        registry: Optional[ToolRegistry] = None,
        options: Optional[HandlerOptions] = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.options = options or HandlerOptions()
        copts = self.options.compressor_options
        self._compressors: dict[MediaClass, AtomicCompressor] = {
            MediaClass.IMAGE: ImageCompressor(registry=self.registry, options=copts),
            MediaClass.AUDIO: AudioCompressor(registry=self.registry, options=copts),
            MediaClass.VIDEO: VideoCompressor(registry=self.registry, options=copts),
        }

    @abstractmethod
    def supports(self, fmt: FileFormat) -> bool: ...

    @abstractmethod
    def handle(
        self,
        input_path: Path,
        target: CompressionTarget,
        *,
        output_path: Path,
        work: Path,
        on_progress: Optional[ProgressFn] = None,
        **options,
    ) -> CompressionResult:
        """Compress a container, returning a :class:`CompressionResult`."""

    # --- shared per-asset compression -------------------------------------------

    def _compressor_for(self, media_path: Path) -> Optional[AtomicCompressor]:
        mc = detect_media_class(media_path)
        return self._compressors.get(mc)

    def _compress_asset(
        self,
        src: Path,
        dst: Path,
        quality: int,
        work: Path,
        *,
        out_format=None,
    ) -> AssetResult:
        """Encode one embedded asset ``src`` -> ``dst`` at a unified quality knob.

        Uses the monotonic, never-failing
        :meth:`~resize_kit.core.atomic.base.AtomicCompressor.encode_quality`
        primitive so container-level size search stays well-behaved. On any
        failure (or if the re-encode would be larger) the original bytes are
        copied through and the asset is marked accordingly — never fatal
        (DESIGN.md §8).
        """
        original = src.stat().st_size
        comp = self._compressor_for(src)
        if comp is None:
            _copy(src, dst)
            return AssetResult(
                name=src.name,
                media_class=MediaClass.UNKNOWN,
                original_bytes=original,
                final_bytes=original,
                status="skipped",
                note="No atomic compressor for this media type.",
            )
        try:
            comp.encode_quality(src, quality, output_path=dst, work=work, out_format=out_format)
            final = dst.stat().st_size
            if final >= original:
                _copy(src, dst)
                return AssetResult(
                    name=src.name,
                    media_class=comp.media_class,
                    original_bytes=original,
                    final_bytes=original,
                    status="unchanged",
                    note="Re-encode would not have been smaller.",
                )
            return AssetResult(
                name=src.name,
                media_class=comp.media_class,
                original_bytes=original,
                final_bytes=final,
                status="compressed",
            )
        except ResizeKitError as exc:
            log.warning("skip asset %s: %s", src.name, exc)
            _copy(src, dst)
            return AssetResult(
                name=src.name,
                media_class=comp.media_class,
                original_bytes=original,
                final_bytes=original,
                status="failed",
                note=str(exc),
            )

    def _new_controller(self) -> SizeBandController:
        return SizeBandController(max_iterations=self.options.container_max_iterations)


def _copy(src: Path, dst: Path) -> None:
    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
