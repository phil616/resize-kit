"""Format-legal padding — the "floor" and "inflate" mechanism (DESIGN.md §6.1, §7).

Each padder injects bytes that a conforming decoder *ignores*, so the visible /
decodable content is bit-for-bit identical while the file grows to a precise
size. The amount passed to every ``_pad_*`` function is the **total** number of
bytes the file should grow by, *including* the padding structure's own header
overhead — so callers can hit an exact target size.

Supported carriers (mirrors the DESIGN.md §6.1 table):

============  ======================================  ===============
Format        Carrier                                  Per-call cap
============  ======================================  ===============
JPEG          ``COM`` comment segments (chained)       unlimited
PNG           private ancillary ``rkPd`` chunk         ~2 GiB
MP4/MOV/M4A   top-level ``free`` box                   unlimited
MP3           ID3v2 tag padding area                   ~256 MiB
PDF           trailing comment after ``%%EOF``         unlimited
WAV           private ``rkPd`` RIFF sub-chunk          ~2 GiB
DOCX/PPTX/…   ZIP end-of-archive comment               65 535 B
============  ======================================  ===============

Formats without a safe carrier (ogg, mkv, …) report ``supports_padding == False``
so the size controller declines rather than risk corrupting them.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Callable, Optional

from ...logging_config import get_logger
from ..exceptions import ResizeKitError
from ..media_type import FileFormat

log = get_logger(__name__)


class PaddingError(ResizeKitError):
    """Raised when padding cannot be applied to a file (malformed structure)."""


# --- JPEG ---------------------------------------------------------------------

_JPEG_COM_MAX_PAYLOAD = 0xFFFF - 2  # length field counts itself (2 bytes)
_JPEG_SEG_OVERHEAD = 4  # FF FE + 2-byte length


def _jpeg_com_blob(total: int) -> bytes:
    """Return ``total`` bytes composed of one or more JPEG ``COM`` segments."""
    if total < _JPEG_SEG_OVERHEAD:
        total = _JPEG_SEG_OVERHEAD
    out = bytearray()
    remaining = total
    while remaining > 0:
        # Each segment occupies >= 4 bytes; never leave an un-representable 1..3
        # byte remainder for the next iteration.
        max_seg = _JPEG_COM_MAX_PAYLOAD + _JPEG_SEG_OVERHEAD
        if remaining <= max_seg:
            seg = remaining
        elif remaining - max_seg < _JPEG_SEG_OVERHEAD:
            seg = remaining - _JPEG_SEG_OVERHEAD
        else:
            seg = max_seg
        payload = seg - _JPEG_SEG_OVERHEAD
        out += b"\xff\xfe" + struct.pack(">H", payload + 2) + b"\x00" * payload
        remaining -= seg
    return bytes(out)


def _pad_jpeg(path: Path, add: int) -> int:
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise PaddingError("Not a JPEG (missing SOI marker).")
    blob = _jpeg_com_blob(add)
    # Insert COM segment(s) immediately after the SOI marker — spec-legal and
    # universally tolerated by decoders.
    path.write_bytes(data[:2] + blob + data[2:])
    return path.stat().st_size


# --- PNG ----------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_CHUNK_OVERHEAD = 12  # length(4) + type(4) + crc(4)
# Ancillary(lowercase r) + private(lowercase k) + reserved(UPPER P) + safe-to-copy(lowercase d)
_PNG_PAD_TYPE = b"rkPd"


def _pad_png(path: Path, add: int) -> int:
    data = path.read_bytes()
    if data[:8] != _PNG_SIG:
        raise PaddingError("Not a PNG (bad signature).")
    iend = data.rfind(b"IEND")
    if iend < 4:
        raise PaddingError("PNG has no IEND chunk.")
    insert_at = iend - 4  # start of IEND's 4-byte length field
    if add < _PNG_CHUNK_OVERHEAD:
        add = _PNG_CHUNK_OVERHEAD
    payload = add - _PNG_CHUNK_OVERHEAD
    body = _PNG_PAD_TYPE + b"\x00" * payload
    chunk = struct.pack(">I", payload) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    path.write_bytes(data[:insert_at] + chunk + data[insert_at:])
    return path.stat().st_size


# --- MP4 / MOV / M4A (ISO-BMFF) ----------------------------------------------

_MP4_BOX_OVERHEAD = 8  # size(4) + type(4)


def _pad_mp4(path: Path, add: int) -> int:
    if add < _MP4_BOX_OVERHEAD:
        add = _MP4_BOX_OVERHEAD
    payload = add - _MP4_BOX_OVERHEAD
    with path.open("ab") as fh:
        fh.write(struct.pack(">I", add) + b"free" + b"\x00" * payload)
    return path.stat().st_size


# --- MP3 (ID3v2 tag padding) --------------------------------------------------

_ID3_HEADER = 10


def _synchsafe(value: int) -> bytes:
    return bytes(
        (
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        )
    )


def _read_synchsafe(b: bytes) -> int:
    return ((b[0] & 0x7F) << 21) | ((b[1] & 0x7F) << 14) | ((b[2] & 0x7F) << 7) | (b[3] & 0x7F)


def _pad_mp3(path: Path, add: int) -> int:
    if add < _ID3_HEADER:
        add = _ID3_HEADER
    data = path.read_bytes()
    if data[:3] == b"ID3" and len(data) >= _ID3_HEADER:
        flags = data[5]
        has_footer = bool(flags & 0x10)
        if not has_footer:
            # Grow the existing tag's padding region in place.
            old_size = _read_synchsafe(data[6:10])
            extra = add  # all of `add` becomes padding bytes inside the tag body
            new_size = old_size + extra
            if new_size < (1 << 28):
                tag_end = _ID3_HEADER + old_size
                new = (
                    data[:6]
                    + _synchsafe(new_size)
                    + data[_ID3_HEADER:tag_end]
                    + b"\x00" * extra
                    + data[tag_end:]
                )
                path.write_bytes(new)
                return path.stat().st_size
    # No usable existing tag (or it has a footer): prepend a fresh padding tag.
    body = add - _ID3_HEADER
    header = b"ID3" + bytes([3, 0, 0]) + _synchsafe(body)
    path.write_bytes(header + b"\x00" * body + data)
    return path.stat().st_size


# --- PDF (trailing comment) ---------------------------------------------------

_PDF_OVERHEAD = 3  # b"\n%" + trailing b"\n"


def _pad_pdf(path: Path, add: int) -> int:
    if add < _PDF_OVERHEAD:
        add = _PDF_OVERHEAD
    filler = b"A" * (add - _PDF_OVERHEAD)
    with path.open("ab") as fh:
        fh.write(b"\n%" + filler + b"\n")
    return path.stat().st_size


# --- WAV (private RIFF sub-chunk) --------------------------------------------

_WAV_CHUNK_OVERHEAD = 8


def _pad_wav(path: Path, add: int) -> int:
    if add < _WAV_CHUNK_OVERHEAD:
        add = _WAV_CHUNK_OVERHEAD
    data = bytearray(path.read_bytes())
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise PaddingError("Not a RIFF/WAVE file.")
    payload = add - _WAV_CHUNK_OVERHEAD
    chunk = b"rkPd" + struct.pack("<I", payload) + b"\x00" * payload
    data += chunk
    # RIFF size field = total file size minus the 8-byte RIFF header.
    struct.pack_into("<I", data, 4, len(data) - 8)
    path.write_bytes(bytes(data))
    return path.stat().st_size


# --- ZIP (OOXML) end-of-archive comment --------------------------------------

_ZIP_EOCD_SIG = b"PK\x05\x06"
_ZIP_EOCD_FIXED = 22
_ZIP_COMMENT_MAX = 0xFFFF


def _pad_zip(path: Path, add: int) -> int:
    data = bytearray(path.read_bytes())
    eocd = data.rfind(_ZIP_EOCD_SIG)
    if eocd < 0:
        raise PaddingError("Not a ZIP archive (no End Of Central Directory).")
    base = eocd + _ZIP_EOCD_FIXED
    existing_comment = len(data) - base
    if existing_comment < 0:
        raise PaddingError("Corrupt ZIP EOCD record.")
    new_comment_len = min(existing_comment + add, _ZIP_COMMENT_MAX)
    # Rewrite comment length field and the comment payload.
    struct.pack_into("<H", data, eocd + 20, new_comment_len)
    tail = bytes(data[base : base + min(existing_comment, new_comment_len)])
    tail = tail + b"\x00" * (new_comment_len - len(tail))
    path.write_bytes(bytes(data[:base]) + tail)
    return path.stat().st_size


# --- registry -----------------------------------------------------------------

# fmt -> (padder, minimum-overhead, per-call cap or None for ~unlimited)
_PADDERS: dict[FileFormat, tuple[Callable[[Path, int], int], int, Optional[int]]] = {
    FileFormat.JPEG: (_pad_jpeg, _JPEG_SEG_OVERHEAD, None),
    FileFormat.PNG: (_pad_png, _PNG_CHUNK_OVERHEAD, (1 << 31) - 1),
    FileFormat.MP4: (_pad_mp4, _MP4_BOX_OVERHEAD, None),
    FileFormat.MOV: (_pad_mp4, _MP4_BOX_OVERHEAD, None),
    FileFormat.M4A: (_pad_mp4, _MP4_BOX_OVERHEAD, None),
    FileFormat.MP3: (_pad_mp3, _ID3_HEADER, (1 << 28) - 1),
    FileFormat.PDF: (_pad_pdf, _PDF_OVERHEAD, None),
    FileFormat.WAV: (_pad_wav, _WAV_CHUNK_OVERHEAD, (1 << 31) - 1),
    FileFormat.DOCX: (_pad_zip, 1, _ZIP_COMMENT_MAX),
    FileFormat.PPTX: (_pad_zip, 1, _ZIP_COMMENT_MAX),
    FileFormat.XLSX: (_pad_zip, 1, _ZIP_COMMENT_MAX),
}


def supports_padding(fmt: FileFormat) -> bool:
    """True if resize-kit has a format-legal padding carrier for ``fmt``."""
    return fmt in _PADDERS


def max_single_pad(fmt: FileFormat) -> Optional[int]:
    """Per-call padding cap in bytes, or None if effectively unlimited."""
    entry = _PADDERS.get(fmt)
    return entry[2] if entry else 0


def add_padding(path: Path, fmt: FileFormat, add_bytes: int) -> int:
    """Grow ``path`` by ``add_bytes`` (the structure overhead is included).

    Returns the new file size. When ``add_bytes`` is below the carrier's minimum
    overhead the file grows by that minimum instead (a few-byte overshoot the
    caller tolerates). Raises :class:`PaddingError` for unsupported formats.
    """
    if add_bytes <= 0:
        return path.stat().st_size
    entry = _PADDERS.get(fmt)
    if entry is None:
        raise PaddingError(f"No padding carrier for format {fmt.value!r}.")
    padder, _min_overhead, cap = entry
    if cap is not None and add_bytes > cap:
        add_bytes = cap
    return padder(path, add_bytes)


def pad_to_size(path: Path, fmt: FileFormat, target_bytes: int) -> int:
    """Grow ``path`` so its size becomes (as close as possible to) ``target_bytes``.

    No-op if the file already meets or exceeds the target. Returns final size.
    """
    current = path.stat().st_size
    need = target_bytes - current
    if need <= 0:
        return current
    return add_padding(path, fmt, need)
