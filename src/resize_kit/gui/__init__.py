"""PyQt5 desktop front-end for resize-kit.

The GUI is a thin shell over :class:`resize_kit.core.dispatcher.Dispatcher`: it
collects a target + options from the form, runs the (potentially long) job on a
background thread, and streams progress back to the UI. No compression logic
lives here.
"""

from __future__ import annotations
