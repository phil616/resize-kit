"""Core, GUI-agnostic compression engine for resize-kit.

Layering (see ``DESIGN.md`` §2), dependencies point downward only::

    dispatcher (L3)  ->  handlers (L2)  ->  atomic (L1)  ->  adapters (L0)
                                  \\__________ sizing (cross-cutting) _________/
"""

from __future__ import annotations
