"""Human-friendly byte-size parsing and formatting.

Used by the CLI/GUI to accept inputs like ``"150KB"`` or ``"1.5 MiB"`` and to
render sizes back for humans. Kept dependency-free and side-effect-free so it is
trivially unit-testable.
"""

from __future__ import annotations

import re

from .exceptions import ConfigurationError

# IEC (binary, 1024) and SI (decimal, 1000) units. We accept both spellings and
# treat the common ambiguous forms (KB, MB, GB) as binary (1024) because that is
# what users targeting upload limits almost always mean.
_BINARY_UNITS = {
    "": 1,
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "MIB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "GIB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
    "TIB": 1024**4,
}

_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]*)\s*$")


def parse_size(text: str | int | float) -> int:
    """Parse a human size string (or raw number) into an integer byte count.

    >>> parse_size("150KB")
    153600
    >>> parse_size("1.5 MiB")
    1572864
    >>> parse_size(2048)
    2048

    Raises:
        ConfigurationError: if the text cannot be parsed or is negative.
    """
    if isinstance(text, bool):  # bool is an int subclass; reject it explicitly.
        raise ConfigurationError(f"Invalid size value: {text!r}")
    if isinstance(text, (int, float)):
        value = int(text)
        if value < 0:
            raise ConfigurationError(f"Size must be non-negative, got {value}")
        return value

    match = _SIZE_RE.match(text)
    if not match:
        raise ConfigurationError(f"Cannot parse size: {text!r}")
    number, unit = match.groups()
    unit = unit.upper()
    if unit not in _BINARY_UNITS:
        raise ConfigurationError(
            f"Unknown size unit {unit!r} in {text!r}. "
            f"Use one of: B, KB/KiB, MB/MiB, GB/GiB."
        )
    value = float(number) * _BINARY_UNITS[unit]
    return int(round(value))


def format_size(num_bytes: int, *, precision: int = 1) -> str:
    """Render a byte count as a compact human string using binary units.

    >>> format_size(153600)
    '150.0 KiB'
    >>> format_size(0)
    '0 B'
    """
    if num_bytes < 0:
        return f"-{format_size(-num_bytes, precision=precision)}"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(num_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.{precision}f} {unit}"
    return f"{value:.{precision}f} PiB"


def format_ratio(original: int, final: int) -> str:
    """Return a percentage describing how much smaller ``final`` is than ``original``.

    A positive percentage means shrinkage; negative means the file grew.
    """
    if original <= 0:
        return "n/a"
    saved = (1.0 - final / original) * 100.0
    return f"{saved:+.1f}%"
