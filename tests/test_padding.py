from __future__ import annotations

import wave
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from resize_kit.core.media_type import FileFormat
from resize_kit.core.sizing import padding as P


def _png(tmp, mode="RGBA", size=(32, 32)):
    p = tmp / "x.png"
    Image.new(mode, size, (10, 20, 30, 128)[: len(mode)]).save(p, "PNG")
    return p


def test_jpeg_exact_pad_and_decodes(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (64, 64), (200, 50, 50)).save(p, "JPEG")
    before = p.stat().st_size
    P.add_padding(p, FileFormat.JPEG, 5000)
    assert p.stat().st_size == before + 5000
    Image.open(p).load()  # still decodes


def test_jpeg_multisegment_large_pad(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (16, 16)).save(p, "JPEG")
    before = p.stat().st_size
    P.add_padding(p, FileFormat.JPEG, 200_000)  # forces multiple COM segments
    assert p.stat().st_size == before + 200_000
    Image.open(p).load()


def test_png_pad_preserves_alpha(tmp_path):
    p = _png(tmp_path)
    before = p.stat().st_size
    P.add_padding(p, FileFormat.PNG, 10_000)
    assert p.stat().st_size == before + 10_000
    out = Image.open(p)
    out.load()
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 128


def test_pad_to_size_is_idempotent_when_large_enough(tmp_path):
    p = _png(tmp_path)
    P.pad_to_size(p, FileFormat.PNG, 20_000)
    assert p.stat().st_size == 20_000
    # Asking for a smaller-or-equal target is a no-op.
    P.pad_to_size(p, FileFormat.PNG, 10_000)
    assert p.stat().st_size == 20_000


def test_zip_comment_pad_keeps_archive_valid(tmp_path):
    p = tmp_path / "x.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", "<x/>")
    before = p.stat().st_size
    P.add_padding(p, FileFormat.DOCX, 5000)
    assert p.stat().st_size == before + 5000
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        assert z.namelist() == ["word/document.xml"]
        assert len(z.comment) == 5000


def test_wav_pad_keeps_frames(tmp_path):
    p = tmp_path / "x.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    before = p.stat().st_size
    P.add_padding(p, FileFormat.WAV, 4000)
    assert p.stat().st_size == before + 4000
    with wave.open(str(p), "rb") as w:
        assert w.getnframes() == 8000


def test_mp3_prepends_tag_when_none(tmp_path):
    # Raw MPEG frame sync, no ID3 tag -> a fresh padding tag is prepended.
    p = tmp_path / "x.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 200)
    before = p.stat().st_size
    P.add_padding(p, FileFormat.MP3, 5000)
    data = p.read_bytes()
    assert p.stat().st_size == before + 5000
    assert data[:3] == b"ID3"


def test_mp3_extends_existing_tag(tmp_path):
    p = tmp_path / "x.mp3"
    body = b"\x00" * 20
    header = b"ID3" + bytes([3, 0, 0]) + P._synchsafe(len(body))
    p.write_bytes(header + body + b"\xff\xfb\x90\x00" + b"\x00" * 100)
    before = p.stat().st_size
    P.add_padding(p, FileFormat.MP3, 4000)
    data = p.read_bytes()
    assert p.stat().st_size == before + 4000
    assert data[:3] == b"ID3"
    # The synchsafe size in the (single, original) tag header grew by 4000.
    assert P._read_synchsafe(data[6:10]) == 20 + 4000


def test_mp4_free_box(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes(bytes([0, 0, 0, 0x18]) + b"ftyp" + b"isom" + b"\x00" * 16)
    before = p.stat().st_size
    P.add_padding(p, FileFormat.MP4, 9000)
    data = p.read_bytes()
    assert p.stat().st_size == before + 9000
    assert data[before + 4 : before + 8] == b"free"


def test_pdf_trailing_comment(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\nstartxref\n0\n%%EOF")
    before = p.stat().st_size
    P.add_padding(p, FileFormat.PDF, 3000)
    data = p.read_bytes()
    assert p.stat().st_size == before + 3000
    assert data[:5] == b"%PDF-"


def test_unsupported_format_reports_no_carrier():
    assert not P.supports_padding(FileFormat.OGG)
    with pytest.raises(P.PaddingError):
        P.add_padding(Path("/nonexistent"), FileFormat.OGG, 100)
