"""resize-kit — enterprise multi-format lossy compressor with precise size targeting.

The public surface deliberately stays small. Most callers want either the
high-level :class:`resize_kit.core.dispatcher.Dispatcher` (one entry point for
every supported format) or the data models in :mod:`resize_kit.core.models`.
"""

from __future__ import annotations

from .version import (
    __author__,
    __author_email__,
    __repository__,
    __version__,
    __version_tag__,
)

__all__ = [
    "__version__",
    "__version_tag__",
    "__author__",
    "__author_email__",
    "__repository__",
]
