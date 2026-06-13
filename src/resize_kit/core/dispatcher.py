"""Dispatcher (Layer 3) — the single public entry point (DESIGN.md §2).

Responsibilities:

1. **Detect** the input format / media class.
2. **Short-circuit for fidelity**: INFLATE, "already in band", and "below the
   floor but under the ceiling" are all satisfied by padding the *original*
   bytes — no lossy re-encode, so pixels/samples stay bit-identical (§7).
3. **Route** anything that actually needs shrinking to the right Layer 1 atomic
   compressor or Layer 2 container handler.
4. **Isolate & clean up** each job in its own temp workspace and place the final
   output atomically.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..logging_config import get_logger
from .adapters.registry import ToolRegistry, default_registry
from .atomic.audio import AudioCompressor
from .atomic.base import AtomicCompressor, CompressorOptions
from .atomic.image import ImageCompressor
from .atomic.video import VideoCompressor
from .detect import detect_format
from .exceptions import ConfigurationError, UnsupportedFormatError
from .handlers.base import HandlerOptions
from .handlers.legacy_office import LegacyOfficeHandler
from .handlers.ooxml import OOXMLHandler
from .handlers.pdf import PdfHandler
from .media_type import FileFormat, MediaClass
from .models import CompressionResult, CompressionTarget, PdfMode, TargetMode
from .sizing import padding as padding_mod
from .workspace import TempWorkspace, atomic_place

log = get_logger(__name__)

ProgressFn = Callable[[str], None]


@dataclass(slots=True)
class JobOptions:
    """Everything that tunes a job but is not the size target itself."""

    pdf_mode: PdfMode = PdfMode.MULTIMEDIA
    keep_ooxml: bool = False
    compressor_options: CompressorOptions = field(default_factory=CompressorOptions)
    container_max_iterations: int = 9
    workspace_base: Optional[Path] = None


class Dispatcher:
    """Format-aware façade over the whole compression engine."""

    def __init__(
        self,
        *,
        registry: Optional[ToolRegistry] = None,
        options: Optional[JobOptions] = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.options = options or JobOptions()
        copts = self.options.compressor_options
        hopts = HandlerOptions(
            compressor_options=copts,
            container_max_iterations=self.options.container_max_iterations,
        )
        self._atomic: dict[MediaClass, AtomicCompressor] = {
            MediaClass.IMAGE: ImageCompressor(registry=self.registry, options=copts),
            MediaClass.AUDIO: AudioCompressor(registry=self.registry, options=copts),
            MediaClass.VIDEO: VideoCompressor(registry=self.registry, options=copts),
        }
        self._ooxml = OOXMLHandler(registry=self.registry, options=hopts)
        self._legacy = LegacyOfficeHandler(registry=self.registry, options=hopts)
        self._pdf = PdfHandler(registry=self.registry, options=hopts)

    # --- public API --------------------------------------------------------------

    def compress(
        self,
        input_path: Path | str,
        target: CompressionTarget,
        output_path: Optional[Path | str] = None,
        *,
        on_progress: Optional[ProgressFn] = None,
    ) -> CompressionResult:
        """Compress (or inflate) ``input_path`` toward ``target``."""
        input_path = Path(input_path)
        if not input_path.is_file():
            raise ConfigurationError(f"Input is not a file: {input_path}")

        fmt = detect_format(input_path)
        media_class = fmt.media_class
        output_path = self._resolve_output(input_path, fmt, output_path)
        original_bytes = input_path.stat().st_size

        log.info(
            "job: %s (%s/%s) %s -> %s",
            input_path.name,
            fmt.value,
            media_class.value,
            target.mode.value,
            output_path.name,
        )

        with TempWorkspace(base_dir=self.options.workspace_base) as ws:
            # 1) Fidelity short-circuit: anything reachable by padding the
            #    original bytes is done losslessly.
            shortcut = self._maybe_pad_only(
                input_path, fmt, target, original_bytes, ws, output_path
            )
            if shortcut is not None:
                return shortcut

            # 2) Real shrink: route to the right component, writing into the
            #    workspace, then place the result atomically.
            staged = ws.path / f"result{output_path.suffix or '.' + fmt.value}"
            result = self._route(
                input_path, fmt, media_class, target, staged, ws, on_progress
            )
            atomic_place(Path(result.output_path), output_path)
            result.output_path = str(output_path)
            return result

    def inflate(
        self,
        input_path: Path | str,
        target_bytes: int,
        output_path: Optional[Path | str] = None,
        *,
        on_progress: Optional[ProgressFn] = None,
    ) -> CompressionResult:
        """Grow a file to ``target_bytes`` via format-legal padding (DESIGN.md §7)."""
        return self.compress(
            input_path,
            CompressionTarget.inflate_to(target_bytes),
            output_path,
            on_progress=on_progress,
        )

    def probe(self, input_path: Path | str) -> dict:
        """Return detection metadata for ``input_path`` (used by CLI ``probe``)."""
        input_path = Path(input_path)
        fmt = detect_format(input_path)
        info = {
            "path": str(input_path),
            "size_bytes": input_path.stat().st_size,
            "format": fmt.value,
            "media_class": fmt.media_class.value,
            "pad_supported": padding_mod.supports_padding(fmt),
        }
        if fmt.media_class in (MediaClass.AUDIO, MediaClass.VIDEO) and self.registry.ffmpeg.is_available():
            try:
                media = self.registry.ffmpeg.probe(input_path)
                info["duration_s"] = round(media.duration, 2)
                info["overall_bitrate"] = media.overall_bit_rate
                info["streams"] = [
                    {"type": s.codec_type, "codec": s.codec_name} for s in media.streams
                ]
            except Exception as exc:  # noqa: BLE001 - probe is best-effort
                info["probe_error"] = str(exc)
        return info

    # --- routing -----------------------------------------------------------------

    def _route(
        self,
        input_path: Path,
        fmt: FileFormat,
        media_class: MediaClass,
        target: CompressionTarget,
        staged: Path,
        ws: TempWorkspace,
        on_progress: Optional[ProgressFn],
    ) -> CompressionResult:
        if media_class in self._atomic:
            return self._atomic[media_class].compress(
                input_path, target, output_path=staged, work=ws.subdir("atomic"),
                out_format=fmt, on_progress=on_progress,
            )
        if media_class is MediaClass.OOXML:
            return self._ooxml.handle(
                input_path, target, output_path=staged, work=ws.subdir("ooxml"),
                on_progress=on_progress,
            )
        if media_class is MediaClass.LEGACY_OFFICE:
            return self._legacy.handle(
                input_path, target, output_path=staged, work=ws.subdir("legacy"),
                on_progress=on_progress, fmt=fmt, keep_ooxml=self.options.keep_ooxml,
            )
        if media_class is MediaClass.PDF:
            return self._pdf.handle(
                input_path, target, output_path=staged, work=ws.subdir("pdf"),
                on_progress=on_progress, pdf_mode=self.options.pdf_mode,
            )
        raise UnsupportedFormatError(
            f"No handler for format {fmt.value!r} (media class {media_class.value})."
        )

    # --- fidelity-preserving short circuit --------------------------------------

    def _maybe_pad_only(
        self,
        input_path: Path,
        fmt: FileFormat,
        target: CompressionTarget,
        original_bytes: int,
        ws: TempWorkspace,
        output_path: Path,
    ) -> Optional[CompressionResult]:
        """Handle cases where no lossy re-encode is needed.

        Returns a result if the job is satisfiable by copying (and optionally
        padding) the original bytes; otherwise None (caller proceeds to shrink).
        """
        resolved = target.resolve(original_bytes)

        # Already within the requested band -> nothing to do.
        if target.mode is not TargetMode.INFLATE and resolved.in_band(original_bytes):
            return self._place_copy(
                input_path, output_path, fmt, original_bytes, original_bytes,
                landed=True, note="Original already satisfies the target.",
            )

        # Would need to shrink (over the ceiling) -> not a padding job.
        over_ceiling = resolved.has_ceiling and original_bytes > (resolved.max_bytes or 0)
        if over_ceiling:
            return None

        # Under the ceiling but below the floor (or pure INFLATE/floor) -> pad
        # the ORIGINAL bytes, preserving fidelity exactly.
        floor = resolved.min_bytes
        if floor is None or original_bytes >= floor:
            return None  # nothing to lift; let routing handle (e.g. RATIO)

        staged = ws.path / f"padded{output_path.suffix or '.' + fmt.value}"
        shutil.copyfile(input_path, staged)
        if not target.allow_pad:
            return self._place_copy(
                input_path, output_path, fmt, original_bytes, original_bytes,
                landed=False, note="Below floor but padding is disabled.",
            )
        if not padding_mod.supports_padding(fmt):
            return self._place_copy(
                input_path, output_path, fmt, original_bytes, original_bytes,
                landed=False,
                note=f"Below floor and no format-legal padding carrier for {fmt.value!r}.",
            )

        pad_target = self._pad_target(target, resolved)
        final = padding_mod.pad_to_size(staged, fmt, pad_target)
        atomic_place(staged, output_path)
        landed = resolved.in_band(final) if target.mode is not TargetMode.INFLATE else final >= floor
        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=final,
            landed_in_band=landed,
            media_class=fmt.media_class,
            file_format=fmt,
            operations=[f"copied original + padded +{final - original_bytes} B"],
            note="Lossless: original content unchanged, padded to target size.",
        )

    @staticmethod
    def _pad_target(target: CompressionTarget, resolved: CompressionTarget) -> int:
        if target.mode is TargetMode.EXACT and resolved.min_bytes and resolved.max_bytes:
            return (resolved.min_bytes + resolved.max_bytes) // 2
        return resolved.min_bytes or 0

    def _place_copy(
        self,
        src: Path,
        dst: Path,
        fmt: FileFormat,
        original_bytes: int,
        final_bytes: int,
        *,
        landed: bool,
        note: str,
    ) -> CompressionResult:
        tmp = dst.parent / f".rk_copy_{dst.name}"
        shutil.copyfile(src, tmp)
        atomic_place(tmp, dst)
        return CompressionResult(
            output_path=str(dst),
            original_bytes=original_bytes,
            final_bytes=final_bytes,
            landed_in_band=landed,
            media_class=fmt.media_class,
            file_format=fmt,
            operations=["copied original (no re-encode)"],
            note=note,
        )

    # --- helpers -----------------------------------------------------------------

    def _resolve_output(
        self, input_path: Path, fmt: FileFormat, output_path: Optional[Path | str]
    ) -> Path:
        if output_path is not None:
            return Path(output_path)
        suffix = input_path.suffix
        if self.options.keep_ooxml and fmt is FileFormat.DOC:
            suffix = ".docx"
        elif self.options.keep_ooxml and fmt is FileFormat.PPT:
            suffix = ".pptx"
        return input_path.with_name(f"{input_path.stem}.rk{suffix}")
