"""PDF handler (Layer 2) — DESIGN.md §5.3.

Two modes:

* **MULTIMEDIA** (structure-preserving): every embedded raster image XObject is
  extracted, recompressed by the Layer 1 :class:`ImageCompressor` (format kept),
  and written back via ``Page.replace_image``. Vectors, text, forms and links
  are untouched.
* **RASTERIZE** (maximum compression): each page is rendered to a bitmap at a
  resolution chosen by the size search, JPEG-encoded, and reassembled into a new
  image-only PDF. All vector/text/interactive content is intentionally dropped.

Both modes drive the size band with the shared controller (knob = per-image
ratio for multimedia, render DPI for rasterize) and pad the PDF floor with a
trailing-comment carrier.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from ...logging_config import get_logger
from ..media_type import FileFormat, MediaClass
from ..models import AssetResult, CompressionResult, CompressionTarget, PdfMode
from .base import ContainerHandler, ProgressFn

log = get_logger(__name__)

_COMPRESSIBLE_IMG_EXT = {"jpeg", "jpg", "png"}
_MIN_IMG_PIXELS = 64 * 64
_RASTER_DPI_MIN = 24
_RASTER_DPI_MAX = 200
_RASTER_JPEG_QUALITY = 82


class PdfHandler(ContainerHandler):
    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.PDF

    def handle(
        self,
        input_path: Path,
        target: CompressionTarget,
        *,
        output_path: Path,
        work: Path,
        on_progress: Optional[ProgressFn] = None,
        pdf_mode: PdfMode = PdfMode.MULTIMEDIA,
        **options,
    ) -> CompressionResult:
        work.mkdir(parents=True, exist_ok=True)
        if isinstance(pdf_mode, str):
            pdf_mode = PdfMode(pdf_mode)
        if pdf_mode is PdfMode.RASTERIZE:
            return self._handle_rasterize(input_path, target, output_path, work, on_progress)
        return self._handle_multimedia(input_path, target, output_path, work, on_progress)

    # --- multimedia (structure preserving) --------------------------------------

    def _handle_multimedia(
        self,
        input_path: Path,
        target: CompressionTarget,
        output_path: Path,
        work: Path,
        on_progress: Optional[ProgressFn],
    ) -> CompressionResult:
        original_bytes = input_path.stat().st_size
        resolved = target.resolve(original_bytes)
        image_comp = self._compressors[MediaClass.IMAGE]
        results_by_path: dict[Path, list[AssetResult]] = {}

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        def build(quality: int) -> Path:
            doc = fitz.open(input_path)
            try:
                xref_page = _collect_image_xrefs(doc)
                emit(f"recompressing {len(xref_page)} image(s) at quality {quality}")
                assets: list[AssetResult] = []
                step_work = work / f"step_{quality}"
                step_work.mkdir(parents=True, exist_ok=True)
                for xref, pno in xref_page.items():
                    assets.append(
                        self._recompress_xref(
                            doc, xref, pno, quality, image_comp, step_work
                        )
                    )
                cand = work / f"cand_{quality}.pdf"
                doc.save(cand, garbage=4, deflate=True, clean=True)
            finally:
                doc.close()
            results_by_path[cand] = assets
            return cand

        controller = self._new_controller()
        conv = controller.converge(
            target=resolved,
            encode=build,
            knob_min=1,
            knob_max=100,
            fmt=FileFormat.PDF,
            on_progress=on_progress,
        )
        conv.path.replace(output_path)
        children = results_by_path.get(conv.path, [])
        compressed = sum(1 for a in children if a.status == "compressed")
        note = f"multimedia mode: {compressed}/{len(children)} images recompressed (vectors/text kept)"
        if conv.note:
            note += f"; {conv.note}"
        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.PDF,
            file_format=FileFormat.PDF,
            operations=conv.operations,
            note=note,
            children=children,
        )

    def _recompress_xref(
        self,
        doc: "fitz.Document",
        xref: int,
        pno: int,
        quality: int,
        image_comp,
        work: Path,
    ) -> AssetResult:
        name = f"xref{xref}"
        try:
            info = doc.extract_image(xref)
        except Exception as exc:  # noqa: BLE001 - PyMuPDF raises broad errors
            return AssetResult(name, MediaClass.IMAGE, 0, 0, "failed", str(exc))
        if not info or not info.get("image"):
            return AssetResult(name, MediaClass.IMAGE, 0, 0, "skipped", "not extractable")
        ext = (info.get("ext") or "").lower()
        data = info["image"]
        original = len(data)
        if ext not in _COMPRESSIBLE_IMG_EXT:
            return AssetResult(name, MediaClass.IMAGE, original, original, "skipped", f"ext {ext}")
        if info.get("width", 0) * info.get("height", 0) < _MIN_IMG_PIXELS:
            return AssetResult(name, MediaClass.IMAGE, original, original, "skipped", "tiny image")

        fmt = FileFormat.JPEG if ext in ("jpeg", "jpg") else FileFormat.PNG
        src = work / f"{name}.{fmt.value}"
        dst = work / f"{name}_out.{fmt.value}"
        src.write_bytes(data)
        try:
            image_comp.encode_quality(src, quality, output_path=dst, work=work, out_format=fmt)
        except Exception as exc:  # noqa: BLE001
            return AssetResult(name, MediaClass.IMAGE, original, original, "failed", str(exc))
        final = dst.stat().st_size
        if final >= original:
            return AssetResult(name, MediaClass.IMAGE, original, original, "unchanged", None)
        try:
            doc[pno].replace_image(xref, stream=dst.read_bytes())
        except Exception as exc:  # noqa: BLE001
            return AssetResult(name, MediaClass.IMAGE, original, original, "failed", f"replace: {exc}")
        return AssetResult(name, MediaClass.IMAGE, original, final, "compressed", None)

    # --- rasterize (image-only) -------------------------------------------------

    def _handle_rasterize(
        self,
        input_path: Path,
        target: CompressionTarget,
        output_path: Path,
        work: Path,
        on_progress: Optional[ProgressFn],
    ) -> CompressionResult:
        original_bytes = input_path.stat().st_size
        resolved = target.resolve(original_bytes)

        def emit(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        def build(dpi: int) -> Path:
            emit(f"rasterizing pages at {dpi} DPI")
            zoom = dpi / 72.0
            src = fitz.open(input_path)
            out = fitz.open()
            try:
                matrix = fitz.Matrix(zoom, zoom)
                for page in src:
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    jpeg = _pixmap_to_jpeg(pix, _RASTER_JPEG_QUALITY)
                    rect = page.rect
                    newpage = out.new_page(width=rect.width, height=rect.height)
                    newpage.insert_image(newpage.rect, stream=jpeg)
                cand = work / f"cand_{dpi}.pdf"
                out.save(cand, garbage=4, deflate=True)
            finally:
                out.close()
                src.close()
            return cand

        controller = self._new_controller()
        conv = controller.converge(
            target=resolved,
            encode=build,
            knob_min=_RASTER_DPI_MIN,
            knob_max=_RASTER_DPI_MAX,
            fmt=FileFormat.PDF,
            on_progress=on_progress,
        )
        conv.path.replace(output_path)
        note = "rasterize mode: pages flattened to images (vectors/text/forms discarded)"
        if conv.note:
            note += f"; {conv.note}"
        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.PDF,
            file_format=FileFormat.PDF,
            operations=conv.operations,
            note=note,
        )


# --- helpers ------------------------------------------------------------------


def _collect_image_xrefs(doc: "fitz.Document") -> dict[int, int]:
    """Map each image xref to the first page index that references it."""
    mapping: dict[int, int] = {}
    for pno in range(doc.page_count):
        for img in doc[pno].get_images(full=True):
            xref = img[0]
            if xref not in mapping:
                mapping[xref] = pno
    return mapping


def _pixmap_to_jpeg(pix: "fitz.Pixmap", quality: int) -> bytes:
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
