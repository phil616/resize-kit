"""Layer 1 — atomic compressors (image / audio / video).

These three "atomic abilities" are the only components that actually shrink
pixels/samples; every composite handler (Office, PDF) reuses them rather than
re-implementing media compression (DESIGN.md §1.1).
"""

from __future__ import annotations

from .audio import AudioCompressor
from .base import AtomicCompressor, CompressorOptions
from .image import ImageCompressor
from .video import VideoCompressor

__all__ = [
    "AtomicCompressor",
    "CompressorOptions",
    "AudioCompressor",
    "ImageCompressor",
    "VideoCompressor",
]
