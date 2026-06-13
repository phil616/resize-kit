"""Layer 2 — composite/container format handlers.

Each handler unwraps a container, delegates its embedded media to the Layer 1
atomic compressors, and re-wraps — never re-implementing media compression.
"""

from __future__ import annotations

from .base import ContainerHandler, HandlerOptions
from .legacy_office import LegacyOfficeHandler
from .ooxml import OOXMLHandler
from .pdf import PdfHandler

__all__ = [
    "ContainerHandler",
    "HandlerOptions",
    "LegacyOfficeHandler",
    "OOXMLHandler",
    "PdfHandler",
]
