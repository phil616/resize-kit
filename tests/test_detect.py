from __future__ import annotations

import pytest

from resize_kit.core.detect import detect_format, detect_media_class
from resize_kit.core.exceptions import DetectionError
from resize_kit.core.media_type import FileFormat, MediaClass, format_from_extension


def test_detect_image_by_signature(make_jpeg, make_png_alpha):
    assert detect_format(make_jpeg()) is FileFormat.JPEG
    assert detect_format(make_png_alpha()) is FileFormat.PNG
    assert detect_media_class(make_jpeg()) is MediaClass.IMAGE


def test_detect_docx_by_zip_contents(make_docx):
    assert detect_format(make_docx()) is FileFormat.DOCX
    assert detect_media_class(make_docx()) is MediaClass.OOXML


def test_detect_pdf(make_pdf):
    assert detect_format(make_pdf()) is FileFormat.PDF


def test_signature_beats_wrong_extension(make_jpeg, tmp_path):
    # A JPEG that lies about being a .png is still detected as JPEG by content.
    jpeg = make_jpeg()
    liar = tmp_path / "actually.png"
    liar.write_bytes(jpeg.read_bytes())
    assert detect_format(liar) is FileFormat.JPEG


def test_missing_file_raises():
    with pytest.raises(DetectionError):
        detect_format("/no/such/file.xyz")


def test_extension_aliases():
    assert format_from_extension(".jpg") is FileFormat.JPEG
    assert format_from_extension("JPEG") is FileFormat.JPEG
    assert format_from_extension(".tif") is FileFormat.TIFF
    assert format_from_extension(".unknownext") is FileFormat.UNKNOWN


def test_detect_by_magic_bytes(tmp_path):
    cases = {
        "a.gif": b"GIF89a" + b"\x00" * 16,
        "a.bmp": b"BM" + b"\x00" * 16,
        "a.mp3": b"ID3\x03\x00\x00\x00\x00\x00\x00",
        "a.pdf": b"%PDF-1.7\n",
    }
    expect = {
        "a.gif": FileFormat.GIF,
        "a.bmp": FileFormat.BMP,
        "a.mp3": FileFormat.MP3,
        "a.pdf": FileFormat.PDF,
    }
    for name, payload in cases.items():
        p = tmp_path / name
        p.write_bytes(payload)
        assert detect_format(p) is expect[name]


def test_detect_mp4_ftyp(tmp_path):
    p = tmp_path / "a.mp4"
    p.write_bytes(bytes([0, 0, 0, 0x18]) + b"ftyp" + b"isom" + b"\x00" * 16)
    assert detect_format(p) is FileFormat.MP4


def test_detect_wav_riff(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 8)
    assert detect_format(p) is FileFormat.WAV
