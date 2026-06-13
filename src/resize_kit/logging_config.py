"""Centralized logging configuration.

The library itself never calls ``logging.basicConfig`` at import time — that is
the application's prerogative. Instead the CLI/GUI call :func:`configure_logging`
once at startup. Library modules just do ``logging.getLogger(__name__)``.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def configure_logging(level: str = "info", *, stream=None) -> None:
    """Install a single stream handler with a concise, timestamped format.

    Idempotent: calling it more than once only adjusts the level.
    """
    global _CONFIGURED
    root = logging.getLogger("resize_kit")
    log_level = _LEVELS.get(level.lower(), logging.INFO)
    root.setLevel(log_level)

    if not _CONFIGURED:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    else:
        for handler in root.handlers:
            handler.setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child logger under the ``resize_kit`` root."""
    return logging.getLogger(name)
