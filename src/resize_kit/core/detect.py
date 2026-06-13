"""Format detection — magic bytes first, extension as the tie-breaker.

Content sniffing is authoritative for the unambiguous signatures (JPEG, PNG,
PDF, …). ZIP and OLE2 containers need a second look at their innards to tell
docx/pptx/xlsx and doc/ppt/xls apart; for the legacy OLE2 binaries — which share
one magic number — we fall back to the file extension.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .exceptions import DetectionError
from .media_type import FileFormat, MediaClass, format_from_extension


def detect_format(path: Path) -> FileFormat:
    """Best-effort concrete format for ``path``."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise DetectionError(f"Not a readable file: {path}")
    try:
        with path.open("rb") as fh:
            head = fh.read(64)
    except OSError as exc:  # pragma: no cover - permission/IO edge
        raise DetectionError(f"Cannot read {path}: {exc}") from exc

    sig = _from_signature(head, path)
    if sig is not FileFormat.UNKNOWN:
        return sig
    # Fall back to extension for formats without a clear leading signature
    # (most audio/video containers, legacy OLE2 doc vs ppt, …).
    return format_from_extension(path.suffix)


def detect_media_class(path: Path) -> MediaClass:
    return detect_format(path).media_class


def _from_signature(head: bytes, path: Path) -> FileFormat:
    if head[:3] == b"\xff\xd8\xff":
        return FileFormat.JPEG
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return FileFormat.PNG
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return FileFormat.GIF
    if head[:2] == b"BM":
        return FileFormat.BMP
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return FileFormat.TIFF
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FileFormat.WEBP
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return FileFormat.WAV
    if head[:4] == b"%PDF":
        return FileFormat.PDF
    if head[:4] == b"fLaC":
        return FileFormat.FLAC
    if head[:4] == b"OggS":
        # Could be ogg-vorbis or opus; extension disambiguates the encoder.
        return format_from_extension(path.suffix) if path.suffix else FileFormat.OGG
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return FileFormat.MP3
    if head[4:8] == b"ftyp":
        return _from_ftyp(head, path)
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML -> Matroska / WebM
        return format_from_extension(path.suffix) if path.suffix else FileFormat.MKV
    if head[:4] == b"PK\x03\x04":
        return _from_zip(path)
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE2 compound document
        return _from_ole(path)
    return FileFormat.UNKNOWN


def _from_ftyp(head: bytes, path: Path) -> FileFormat:
    brand = head[8:12]
    if brand[:3] == b"qt ":
        return FileFormat.MOV
    if brand[:4] in (b"M4A ", b"M4B "):
        return FileFormat.M4A
    # isom/mp42/avc1/dash/etc -> mp4 family; trust extension if it says m4a/mov.
    ext_fmt = format_from_extension(path.suffix)
    if ext_fmt in (FileFormat.M4A, FileFormat.MOV):
        return ext_fmt
    return FileFormat.MP4


def _from_zip(path: Path) -> FileFormat:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return FileFormat.UNKNOWN
    if any(n.startswith("word/") for n in names):
        return FileFormat.DOCX
    if any(n.startswith("ppt/") for n in names):
        return FileFormat.PPTX
    if any(n.startswith("xl/") for n in names):
        return FileFormat.XLSX
    # A generic zip with OOXML content types but unusual layout.
    if "[Content_Types].xml" in names:
        return FileFormat.DOCX
    return FileFormat.UNKNOWN


def _from_ole(path: Path) -> FileFormat:
    # Distinguishing DOC vs PPT vs XLS from the OLE2 directory is brittle; the
    # extension is the pragmatic and reliable signal here.
    ext_fmt = format_from_extension(path.suffix)
    if ext_fmt in (FileFormat.DOC, FileFormat.PPT):
        return ext_fmt
    return FileFormat.DOC
