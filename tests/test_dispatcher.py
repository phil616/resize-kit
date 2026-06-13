from __future__ import annotations

from PIL import Image

from resize_kit.core.dispatcher import Dispatcher
from resize_kit.core.models import CompressionTarget


def test_compress_image_band(make_jpeg, tmp_path):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    res = Dispatcher().compress(src, CompressionTarget.band(40 * 1024, 60 * 1024), out)
    assert 40 * 1024 <= res.final_bytes <= 60 * 1024 and res.landed_in_band
    assert out.exists()


def test_inflate_is_lossless(make_jpeg, tmp_path):
    src = make_jpeg(w=400, h=300, quality=80)
    out = tmp_path / "big.jpg"
    res = Dispatcher().inflate(src, 300 * 1024, out)
    assert abs(res.final_bytes - 300 * 1024) <= 1024
    assert Image.open(src).tobytes() == Image.open(out).tobytes()  # pixels unchanged


def test_already_in_band_is_noop(make_jpeg, tmp_path):
    src = make_jpeg(w=200, h=200)
    size = src.stat().st_size
    out = tmp_path / "out.jpg"
    # A band that already contains the original size -> copy through, no re-encode.
    res = Dispatcher().compress(src, CompressionTarget.band(size - 100, size + 50_000), out)
    assert res.landed_in_band
    assert out.read_bytes() == src.read_bytes()


def test_exact_target_below_original(make_jpeg, tmp_path):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    res = Dispatcher().compress(src, CompressionTarget.exact(50 * 1024), out)
    assert abs(res.final_bytes - 50 * 1024) <= 1024


def test_probe(make_jpeg):
    info = Dispatcher().probe(make_jpeg())
    assert info["format"] == "jpeg" and info["media_class"] == "image"
    assert info["pad_supported"] is True
