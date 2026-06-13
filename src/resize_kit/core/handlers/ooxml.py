"""OOXML handler (Layer 2) — DOCX / PPTX / XLSX (DESIGN.md §5.1).

OOXML is a ZIP whose media live under ``*/media/``. We unzip once to a pristine
tree, then converge on the size target by binary-searching a single *per-asset
compression ratio* applied to every embedded image/audio/video, re-packing the
ZIP at each step. Because compressed assets are written back **under their
original names and formats**, the ``_rels`` references and ``[Content_Types].xml``
never need editing — zero structural change (the key fidelity guarantee of §5.1).

The container floor (for SIZE_BAND/EXACT) is met by ZIP end-of-archive comment
padding via the shared :mod:`~resize_kit.core.sizing.padding` carrier.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..detect import detect_format, detect_media_class
from ..media_type import FileFormat, MediaClass, format_from_extension
from ..models import AssetResult, CompressionResult, CompressionTarget
from .base import ContainerHandler, ProgressFn

log = get_logger(__name__)

_OOXML_FORMATS = {FileFormat.DOCX, FileFormat.PPTX, FileFormat.XLSX}


class OOXMLHandler(ContainerHandler):
    def supports(self, fmt: FileFormat) -> bool:
        return fmt in _OOXML_FORMATS

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
        work.mkdir(parents=True, exist_ok=True)
        original_bytes = input_path.stat().st_size
        fmt = detect_format(input_path)

        pristine = work / "pristine"
        _extract(input_path, pristine)
        media = _scan_media(pristine)

        if not media:
            _copy_through(input_path, output_path)
            return CompressionResult(
                output_path=str(output_path),
                original_bytes=original_bytes,
                final_bytes=output_path.stat().st_size,
                landed_in_band=target.resolve(original_bytes).in_band(original_bytes),
                media_class=MediaClass.OOXML,
                file_format=fmt,
                operations=["no compressible media found"],
                note="Document contains no images/audio/video to compress.",
            )

        resolved = target.resolve(original_bytes)
        results_by_path: dict[Path, list[AssetResult]] = {}

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        def build(quality: int) -> Path:
            emit(f"packing at asset quality {quality} ({len(media)} assets)")
            replacements: dict[str, Path] = {}
            asset_results: list[AssetResult] = []
            step_work = work / f"step_{quality}"
            step_work.mkdir(parents=True, exist_ok=True)
            for rel, src in media:
                ext = Path(rel).suffix or ".bin"
                dst = step_work / "media" / (rel.replace("/", "__"))
                ar = self._compress_asset(
                    src,
                    dst,
                    quality,
                    step_work / "scratch",
                    out_format=format_from_extension(ext),
                )
                asset_results.append(ar)
                replacements[rel] = dst
            cand = work / f"cand_{quality}{input_path.suffix or '.' + fmt.value}"
            _repack(pristine, replacements, cand)
            results_by_path[cand] = asset_results
            return cand

        controller = self._new_controller()
        conv = controller.converge(
            target=resolved,
            encode=build,
            knob_min=1,
            knob_max=100,
            fmt=fmt,
            on_progress=on_progress,
        )

        conv.path.replace(output_path)
        children = results_by_path.get(conv.path, [])
        compressed = sum(1 for a in children if a.status == "compressed")
        note = f"{compressed}/{len(children)} embedded assets recompressed"
        if conv.note:
            note = f"{note}; {conv.note}"

        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.OOXML,
            file_format=fmt,
            operations=conv.operations,
            note=note,
            children=children,
        )


# --- helpers ------------------------------------------------------------------


def _extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


def _scan_media(root: Path) -> list[tuple[str, Path]]:
    """Return [(arcname, path)] for every embedded image/audio/video asset."""
    media: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if detect_media_class(path) in (MediaClass.IMAGE, MediaClass.AUDIO, MediaClass.VIDEO):
            arcname = path.relative_to(root).as_posix()
            media.append((arcname, path))
    return media


def _repack(pristine: Path, replacements: dict[str, Path], out_zip: Path) -> None:
    """Re-zip ``pristine``, substituting ``replacements[arcname]`` where present."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in pristine.rglob("*") if p.is_file())
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(pristine).as_posix()
            source = replacements.get(arcname, path)
            # Already-compressed media gains nothing from deflate; store it.
            compress_type = (
                zipfile.ZIP_STORED if arcname in replacements else zipfile.ZIP_DEFLATED
            )
            zf.write(source, arcname, compress_type=compress_type)


def _copy_through(src: Path, dst: Path) -> None:
    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
