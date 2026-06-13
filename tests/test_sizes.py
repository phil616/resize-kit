from __future__ import annotations

import pytest

from resize_kit.core.exceptions import ConfigurationError
from resize_kit.core.sizes import format_ratio, format_size, parse_size


@pytest.mark.parametrize(
    "text,expected",
    [
        ("150KB", 153600),
        ("150 KiB", 153600),
        ("1.5MiB", 1572864),
        ("2MB", 2 * 1024 * 1024),
        ("1024", 1024),
        ("0", 0),
        ("512B", 512),
        ("  3 GiB ", 3 * 1024**3),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_parse_size_numbers():
    assert parse_size(2048) == 2048
    assert parse_size(2048.0) == 2048


@pytest.mark.parametrize("bad", ["", "abc", "10 furlongs", "-5KB", "KB"])
def test_parse_size_rejects_garbage(bad):
    with pytest.raises(ConfigurationError):
        parse_size(bad)


def test_parse_size_rejects_bool():
    with pytest.raises(ConfigurationError):
        parse_size(True)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KiB"
    assert format_size(153600) == "150.0 KiB"
    assert format_size(1024 * 1024) == "1.0 MiB"


def test_format_ratio():
    assert format_ratio(100, 50) == "+50.0%"
    assert format_ratio(100, 200) == "-100.0%"
    assert format_ratio(0, 10) == "n/a"
