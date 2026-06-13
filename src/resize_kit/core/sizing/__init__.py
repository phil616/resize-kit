"""Cross-cutting size-targeting machinery (DESIGN.md §6 / §7).

* :mod:`padding` injects decoder-ignored, format-legal bytes — the *floor* and
  the *inflate* mechanism.
* :mod:`controller` runs the binary-search-then-pad convergence used by every
  atomic compressor and by container handlers.
"""

from __future__ import annotations

from .controller import ConvergeResult, SizeBandController
from .padding import (
    PaddingError,
    add_padding,
    max_single_pad,
    pad_to_size,
    supports_padding,
)

__all__ = [
    "ConvergeResult",
    "SizeBandController",
    "PaddingError",
    "add_padding",
    "max_single_pad",
    "pad_to_size",
    "supports_padding",
]
