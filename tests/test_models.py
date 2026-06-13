from __future__ import annotations

import pytest

from resize_kit.core.exceptions import ConfigurationError
from resize_kit.core.models import CompressionTarget, TargetMode


def test_ratio_validation():
    with pytest.raises(ConfigurationError):
        CompressionTarget(mode=TargetMode.RATIO)
    with pytest.raises(ConfigurationError):
        CompressionTarget(mode=TargetMode.RATIO, ratio=1.5)
    t = CompressionTarget.ratio_of(0.5)
    assert t.ratio == 0.5


def test_band_validation():
    with pytest.raises(ConfigurationError):
        CompressionTarget(mode=TargetMode.SIZE_BAND)  # neither bound
    with pytest.raises(ConfigurationError):
        CompressionTarget.band(200, 100)  # min > max
    t = CompressionTarget.band(100, 200)
    assert t.in_band(150) and not t.in_band(99) and not t.in_band(201)


def test_band_open_bounds():
    ceiling = CompressionTarget.band(None, 200)
    assert ceiling.in_band(0) and ceiling.in_band(200) and not ceiling.in_band(201)
    floor = CompressionTarget.band(100, None)
    assert floor.in_band(100) and floor.in_band(10**9) and not floor.in_band(99)


def test_exact_sets_tolerance_band():
    t = CompressionTarget.exact(100_000, exact_tolerance=2000)
    assert t.min_bytes == 98_000 and t.max_bytes == 102_000
    assert t.in_band(100_000) and not t.in_band(103_000)


def test_inflate_floor():
    t = CompressionTarget.inflate_to(900_000)
    assert t.min_bytes == 900_000 and t.has_floor and not t.has_ceiling


def test_resolve_ratio_to_ceiling():
    t = CompressionTarget.ratio_of(0.5).resolve(1000)
    assert t.mode is TargetMode.SIZE_BAND
    assert t.max_bytes == 500 and t.min_bytes is None


def test_resolve_passthrough_for_absolute_modes():
    band = CompressionTarget.band(100, 200)
    assert band.resolve(999) is band
