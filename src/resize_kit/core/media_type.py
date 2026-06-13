"""Media / container type taxonomy and the format <-> type mapping.

This is the vocabulary the whole engine speaks: detection produces a
:class:`FileFormat`, dispatch routes on its :class:`MediaClass`, and the atomic
compressors advertise which :class:`MediaClass` values they support.
"""

from __future__ import annotations

from enum import Enum


class MediaClass(str, Enum):
    """Coarse routing category for a file."""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    OOXML = "ooxml"  # docx / pptx (native zip-based Office)
    LEGACY_OFFICE = "legacy_office"  # doc / ppt (OLE2 binary)
    PDF = "pdf"
    UNKNOWN = "unknown"


class FileFormat(str, Enum):
    """Concrete file format. ``value`` is the canonical lowercase extension."""

    # Images
    JPEG = "jpeg"
    PNG = "png"
    BMP = "bmp"
    GIF = "gif"
    TIFF = "tiff"
    WEBP = "webp"
    # Audio
    MP3 = "mp3"
    AAC = "aac"
    M4A = "m4a"
    OGG = "ogg"
    OPUS = "opus"
    FLAC = "flac"
    WAV = "wav"
    # Video
    MP4 = "mp4"
    MKV = "mkv"
    MOV = "mov"
    WEBM = "webm"
    AVI = "avi"
    # Office
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    DOC = "doc"
    PPT = "ppt"
    # Documents
    PDF = "pdf"
    UNKNOWN = "unknown"

    @property
    def media_class(self) -> MediaClass:
        return _FORMAT_TO_CLASS.get(self, MediaClass.UNKNOWN)


_FORMAT_TO_CLASS: dict[FileFormat, MediaClass] = {
    FileFormat.JPEG: MediaClass.IMAGE,
    FileFormat.PNG: MediaClass.IMAGE,
    FileFormat.BMP: MediaClass.IMAGE,
    FileFormat.GIF: MediaClass.IMAGE,
    FileFormat.TIFF: MediaClass.IMAGE,
    FileFormat.WEBP: MediaClass.IMAGE,
    FileFormat.MP3: MediaClass.AUDIO,
    FileFormat.AAC: MediaClass.AUDIO,
    FileFormat.M4A: MediaClass.AUDIO,
    FileFormat.OGG: MediaClass.AUDIO,
    FileFormat.OPUS: MediaClass.AUDIO,
    FileFormat.FLAC: MediaClass.AUDIO,
    FileFormat.WAV: MediaClass.AUDIO,
    FileFormat.MP4: MediaClass.VIDEO,
    FileFormat.MKV: MediaClass.VIDEO,
    FileFormat.MOV: MediaClass.VIDEO,
    FileFormat.WEBM: MediaClass.VIDEO,
    FileFormat.AVI: MediaClass.VIDEO,
    FileFormat.DOCX: MediaClass.OOXML,
    FileFormat.PPTX: MediaClass.OOXML,
    FileFormat.XLSX: MediaClass.OOXML,
    FileFormat.DOC: MediaClass.LEGACY_OFFICE,
    FileFormat.PPT: MediaClass.LEGACY_OFFICE,
    FileFormat.PDF: MediaClass.PDF,
}

# Extension aliases that are not 1:1 with the enum's canonical value.
_EXTENSION_ALIASES: dict[str, FileFormat] = {
    "jpg": FileFormat.JPEG,
    "jpeg": FileFormat.JPEG,
    "jpe": FileFormat.JPEG,
    "jfif": FileFormat.JPEG,
    "tif": FileFormat.TIFF,
    "tiff": FileFormat.TIFF,
    "htm": FileFormat.UNKNOWN,
}


def format_from_extension(ext: str) -> FileFormat:
    """Map a filename extension (with or without leading dot) to a FileFormat."""
    ext = ext.lower().lstrip(".")
    if ext in _EXTENSION_ALIASES:
        return _EXTENSION_ALIASES[ext]
    try:
        return FileFormat(ext)
    except ValueError:
        return FileFormat.UNKNOWN
