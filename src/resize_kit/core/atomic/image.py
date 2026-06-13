"""ImageCompressor (Layer 1) — DESIGN.md §4.1.

Lossy-first, compression-rate-first. The single hard constraint is alpha: if the
source has a transparency channel it must survive compression.

Two alpha-preserving PNG backends are implemented:

* ``quantize`` (default, the DESIGN.md "better backend"): palette quantization
  via pngquant when present, else Pillow's FASTOCTREE quantizer — both keep
  alpha natively and compress far better.
* ``channel_split`` (the DESIGN.md mandated method): split RGB+A, bleed colors
  outward across transparent edges to kill JPEG halos, JPEG-roundtrip the RGB,
  then re-merge the *original* alpha and re-wrap as PNG.

The output format always equals the input format (container fidelity, §1.2);
quality and resolution are the convergence knobs driven by the
:class:`~resize_kit.core.sizing.controller.SizeBandController`.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageFilter

from ...logging_config import get_logger
from ..media_type import FileFormat, MediaClass, format_from_extension
from ..models import CompressionResult, CompressionTarget
from .base import AtomicCompressor, ProgressFn, lerp

log = get_logger(__name__)

# PIL save format names keyed by our FileFormat.
_PIL_FORMAT = {
    FileFormat.JPEG: "JPEG",
    FileFormat.PNG: "PNG",
    FileFormat.BMP: "BMP",
    FileFormat.GIF: "GIF",
    FileFormat.TIFF: "TIFF",
    FileFormat.WEBP: "WEBP",
}


class ImageCompressor(AtomicCompressor):
    media_class = MediaClass.IMAGE

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
        work = self._ensure_work(work)
        original_bytes = input_path.stat().st_size
        fmt = out_format or format_from_extension(input_path.suffix)
        if fmt not in _PIL_FORMAT:
            fmt = FileFormat.JPEG  # safe lossy default for unknown raster inputs
        if output_path is None:
            output_path = work / f"out.{fmt.value}"

        resolved = target.resolve(original_bytes)

        with Image.open(input_path) as im:
            im.load()
            source = im.convert("RGBA") if _has_alpha(im) else im.convert("RGB")
        has_alpha = source.mode == "RGBA"
        base_w, base_h = source.size

        # Mutable downscale state captured by the encode/downscale closures.
        state = {"scale": 1.0}
        opts = self.options

        def current_image() -> Image.Image:
            if state["scale"] >= 0.999:
                return source
            w = max(opts.min_image_dimension, int(base_w * state["scale"]))
            h = max(opts.min_image_dimension, int(base_h * state["scale"]))
            return source.resize((w, h), Image.LANCZOS)

        def encode(knob: int) -> Path:
            img = current_image()
            data = self._encode(img, fmt, knob, has_alpha)
            cand = work / f"cand_{knob}_{state['scale']:.3f}.{fmt.value}"
            cand.write_bytes(data)
            return cand

        def downscale() -> bool:
            new_scale = state["scale"] * opts.downscale_factor
            min_dim = opts.min_image_dimension
            if base_w * new_scale < min_dim or base_h * new_scale < min_dim:
                return False
            steps_used = round((1.0 - state["scale"]) / (1.0 - opts.downscale_factor))
            if steps_used >= opts.max_downscale_steps:
                return False
            state["scale"] = new_scale
            return True

        conv = self.controller.converge(
            target=resolved,
            encode=encode,
            knob_min=opts.jpeg_min_quality,
            knob_max=opts.jpeg_max_quality,
            fmt=fmt,
            downscale=downscale,
            on_progress=on_progress,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        conv.path.replace(output_path)

        note_bits = []
        if state["scale"] < 0.999:
            note_bits.append(f"downscaled to {state['scale']:.0%} ({int(base_w*state['scale'])}px)")
        if conv.note:
            note_bits.append(conv.note)
        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.IMAGE,
            file_format=fmt,
            operations=conv.operations,
            note="; ".join(note_bits) or None,
        )

    def encode_quality(
        self,
        input_path: Path,
        quality: int,
        *,
        output_path: Path,
        work: Path,
        out_format: Optional[FileFormat] = None,
    ) -> Path:
        quality = max(1, min(100, quality))
        fmt = out_format or format_from_extension(input_path.suffix)
        if fmt not in _PIL_FORMAT:
            fmt = FileFormat.JPEG
        with Image.open(input_path) as im:
            im.load()
            source = im.convert("RGBA") if _has_alpha(im) else im.convert("RGB")
        has_alpha = source.mode == "RGBA"
        # The unified knob spans resolution AND codec quality so size grows
        # monotonically with `quality` across its full range.
        t = quality / 100.0
        scale = lerp(0.30, 1.0, t)
        enc_q = int(round(lerp(15, 92, t)))
        w, h = source.size
        if scale < 0.999:
            nw = max(self.options.min_image_dimension, int(w * scale))
            nh = max(self.options.min_image_dimension, int(h * scale))
            source = source.resize((nw, nh), Image.LANCZOS)
        data = self._encode(source, fmt, enc_q, has_alpha)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return output_path

    # --- encoding ----------------------------------------------------------------

    def _encode(self, img: Image.Image, fmt: FileFormat, quality: int, has_alpha: bool) -> bytes:
        quality = max(1, min(100, quality))
        if fmt is FileFormat.JPEG:
            return _save(img.convert("RGB"), "JPEG", quality=quality, optimize=True)
        if fmt is FileFormat.WEBP:
            return _save(img, "WEBP", quality=quality, method=4)
        if fmt is FileFormat.PNG:
            return self._encode_png(img, quality, has_alpha)
        if fmt is FileFormat.GIF:
            colors = _quality_to_colors(quality)
            return _save(img.convert("RGBA").quantize(colors=colors), "GIF")
        if fmt in (FileFormat.BMP, FileFormat.TIFF):
            # Lossy degrade through JPEG, then re-wrap in the (lossless) target.
            degraded = _jpeg_roundtrip(img.convert("RGB"), quality)
            return _save(degraded, _PIL_FORMAT[fmt])
        return _save(img.convert("RGB"), "JPEG", quality=quality, optimize=True)

    def _encode_png(self, img: Image.Image, quality: int, has_alpha: bool) -> bytes:
        strategy = self.options.png_alpha_strategy
        if not has_alpha:
            # Opaque PNG: palette-quantize for a real size win.
            return self._encode_png_quantize(img.convert("RGB"), quality)
        if strategy == "channel_split":
            return self._encode_png_channel_split(img, quality)
        # default: quantize (keeps alpha natively)
        return self._encode_png_quantize(img, quality)

    def _encode_png_quantize(self, img: Image.Image, quality: int) -> bytes:
        colors = _quality_to_colors(quality)
        # pngquant first (best); fall back to Pillow's alpha-aware FASTOCTREE.
        pq = self.registry.pngquant
        if pq.is_available():
            tmp_in = BytesIO()
            img.save(tmp_in, "PNG", optimize=False)
            in_path = Path(self._scratch("pngq_in.png"))
            out_path = Path(self._scratch("pngq_out.png"))
            in_path.write_bytes(tmp_in.getvalue())
            if pq.quantize(in_path, out_path, quality_max=min(100, quality), colors=colors):
                return out_path.read_bytes()
        quantized = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
        return _save(quantized, "PNG", optimize=True)

    def _encode_png_channel_split(self, rgba: Image.Image, quality: int) -> bytes:
        """DESIGN.md §4.1.B — channel separation with transparent-edge color bleed."""
        rgba = rgba.convert("RGBA")
        r, g, b, a = rgba.split()
        bled_rgb = _bleed_edges(Image.merge("RGB", (r, g, b)), a)
        degraded = _jpeg_roundtrip(bled_rgb, quality)
        merged = Image.merge("RGBA", (*degraded.split(), a))
        return _save(merged, "PNG", optimize=True)

    def _scratch(self, name: str) -> str:
        import tempfile

        d = Path(tempfile.mkdtemp(prefix="rk_png_"))
        return str(d / name)


# --- module-level helpers -----------------------------------------------------


def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA"):
        return True
    if im.mode == "P" and "transparency" in im.info:
        return True
    return im.mode == "PA"


def _save(img: Image.Image, fmt: str, **params) -> bytes:
    buf = BytesIO()
    img.save(buf, fmt, **params)
    return buf.getvalue()


def _jpeg_roundtrip(rgb: Image.Image, quality: int) -> Image.Image:
    buf = BytesIO()
    rgb.save(buf, "JPEG", quality=max(1, min(100, quality)), optimize=True)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _quality_to_colors(quality: int) -> int:
    """Map a 1..100 quality knob to a 2..256 palette size (monotonic)."""
    quality = max(1, min(100, quality))
    return max(2, min(256, round(2 + (quality / 100.0) * 254)))


def _bleed_edges(rgb: Image.Image, alpha: Image.Image, iterations: int = 6) -> Image.Image:
    """Spread opaque colors outward into transparent regions to suppress halos.

    Iteratively dilates the opaque mask; each newly-covered ring is filled with a
    blurred copy of the current colors, so JPEG never has to invent colors at the
    alpha boundary.
    """
    mask = alpha.point(lambda v: 255 if v >= 16 else 0).convert("L")
    result = rgb
    cur_mask = mask
    for _ in range(iterations):
        if _is_full(cur_mask):
            break
        blurred = result.filter(ImageFilter.GaussianBlur(2))
        grown = cur_mask.filter(ImageFilter.MaxFilter(5))
        ring = ImageChops.subtract(grown, cur_mask)  # newly covered pixels
        result = Image.composite(blurred, result, ring)
        cur_mask = grown
    return result


def _is_full(mask: Image.Image) -> bool:
    extrema = mask.getextrema()
    return extrema[0] == 255
