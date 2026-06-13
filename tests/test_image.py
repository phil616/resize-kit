from __future__ import annotations

from PIL import Image

from resize_kit.core.atomic.base import CompressorOptions
from resize_kit.core.atomic.image import ImageCompressor
from resize_kit.core.models import CompressionTarget


def test_jpeg_lands_in_band(make_jpeg, tmp_path):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    res = ImageCompressor().compress(
        src, CompressionTarget.band(40 * 1024, 60 * 1024), output_path=out
    )
    assert 40 * 1024 <= res.final_bytes <= 60 * 1024 and res.landed_in_band
    Image.open(out).load()


def test_ratio_shrinks(make_jpeg, tmp_path):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    res = ImageCompressor().compress(src, CompressionTarget.ratio_of(0.3), output_path=out)
    assert res.final_bytes <= src.stat().st_size * 0.3


def test_channel_split_preserves_transparency(make_png_alpha, tmp_path):
    src = make_png_alpha()
    out = tmp_path / "out.png"
    # Generous ceiling so no downscale: full-res alpha is preserved exactly.
    ic = ImageCompressor(options=CompressorOptions(png_alpha_strategy="channel_split"))
    ic.compress(src, CompressionTarget.band(None, 5 * 1024 * 1024), output_path=out)
    img = Image.open(out)
    img.load()
    assert img.mode == "RGBA"
    assert img.size == Image.open(src).size
    assert img.getpixel((1, 1))[3] == 0  # transparent corner stays transparent


def test_quantize_backend_keeps_alpha(make_png_alpha, tmp_path):
    src = make_png_alpha()
    out = tmp_path / "out.png"
    ImageCompressor().compress(
        src, CompressionTarget.band(None, 5 * 1024 * 1024), output_path=out
    )
    img = Image.open(out)
    img.load()
    assert img.convert("RGBA").getpixel((1, 1))[3] == 0


def test_encode_quality_is_monotonic(make_jpeg, tmp_path):
    src = make_jpeg(w=600, h=400)
    ic = ImageCompressor()
    sizes = []
    for q in (10, 40, 70, 95):
        p = ic.encode_quality(src, q, output_path=tmp_path / f"q{q}.jpg", work=tmp_path / "w")
        sizes.append(p.stat().st_size)
    assert sizes == sorted(sizes)  # higher quality => larger (non-decreasing)
