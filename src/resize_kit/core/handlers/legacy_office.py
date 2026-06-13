"""Legacy Office handler (Layer 2) — DOC / PPT (DESIGN.md §5.2).

OLE2 binaries are normalized to OOXML via LibreOffice, compressed by the
:class:`~resize_kit.core.handlers.ooxml.OOXMLHandler`, then converted back. The
round-trip can introduce minor layout drift, so this handler always annotates
the result and supports a ``keep_ooxml`` escape hatch (the §5.2 "safer output"
option) that returns the DOCX/PPTX instead of converting back.

Exact size bands are best-effort for legacy output: the DOC/PPT re-serialization
size is not under our byte control and OLE2 has no safe padding carrier, so the
``landed_in_band`` flag reflects the *actual* converted file and a note explains
any miss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..media_type import FileFormat, MediaClass
from ..models import CompressionResult, CompressionTarget
from .base import ContainerHandler, ProgressFn
from .ooxml import OOXMLHandler

log = get_logger(__name__)

_LEGACY_TO_OOXML = {
    FileFormat.DOC: "docx",
    FileFormat.PPT: "pptx",
}


class LegacyOfficeHandler(ContainerHandler):
    def supports(self, fmt: FileFormat) -> bool:
        return fmt in _LEGACY_TO_OOXML

    def handle(
        self,
        input_path: Path,
        target: CompressionTarget,
        *,
        output_path: Path,
        work: Path,
        on_progress: Optional[ProgressFn] = None,
        fmt: Optional[FileFormat] = None,
        keep_ooxml: bool = False,
        **options,
    ) -> CompressionResult:
        self.registry.require("soffice")
        work.mkdir(parents=True, exist_ok=True)
        original_bytes = input_path.stat().st_size
        fmt = fmt or _detect_legacy(input_path)
        ooxml_ext = _LEGACY_TO_OOXML[fmt]
        profile = work / "lo_profile"

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        # 1) normalize DOC/PPT -> DOCX/PPTX
        emit(f"normalizing {fmt.value} -> {ooxml_ext} via LibreOffice")
        normalized = self.registry.libreoffice.convert(
            input_path, ooxml_ext, work / "normalized", profile_dir=profile
        )

        # 2) compress the OOXML toward the requested target
        ooxml_out = work / f"compressed.{ooxml_ext}"
        sub = OOXMLHandler(registry=self.registry, options=self.options)
        sub_result = sub.handle(
            normalized,
            target,
            output_path=ooxml_out,
            work=work / "ooxml",
            on_progress=on_progress,
        )

        if keep_ooxml:
            ooxml_out.replace(output_path)
            sub_result.output_path = str(output_path)
            sub_result.note = (sub_result.note or "") + " | kept as OOXML (no DOC/PPT round-trip)"
            return sub_result

        # 3) denormalize OOXML -> DOC/PPT
        emit(f"converting back {ooxml_ext} -> {fmt.value}")
        legacy_out = self.registry.libreoffice.convert(
            ooxml_out, fmt.value, work / "denormalized", profile_dir=profile
        )
        legacy_out.replace(output_path)

        final_bytes = output_path.stat().st_size
        landed = target.resolve(original_bytes).in_band(final_bytes)
        note = (
            f"Legacy round-trip via LibreOffice (minor layout drift possible). "
            f"{sub_result.note or ''}"
        )
        if not landed:
            note += (
                " | NOTE: exact size band is approximate for DOC/PPT — "
                "consider the 'keep OOXML' option for precise control."
            )
        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=final_bytes,
            landed_in_band=landed,
            media_class=MediaClass.LEGACY_OFFICE,
            file_format=fmt,
            operations=["normalize", *sub_result.operations, "denormalize"],
            note=note.strip(),
            children=sub_result.children,
        )


def _detect_legacy(path: Path) -> FileFormat:
    from ..detect import detect_format

    fmt = detect_format(path)
    return fmt if fmt in _LEGACY_TO_OOXML else FileFormat.DOC
