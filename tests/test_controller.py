from __future__ import annotations

import pytest

from resize_kit.core.exceptions import UnreachableTargetError
from resize_kit.core.media_type import FileFormat
from resize_kit.core.models import CompressionTarget
from resize_kit.core.sizing.controller import SizeBandController


@pytest.fixture
def linear_encoder(tmp_path):
    """encode(knob) writes knob*1000 zero bytes; size grows linearly with knob."""
    calls = []

    def encode(knob):
        calls.append(knob)
        p = tmp_path / f"c_{knob}.pdf"  # .pdf so the PDF padder applies
        p.write_bytes(b"\x00" * (knob * 1000))
        return p

    encode.calls = calls
    return encode


def test_band_via_binary_search(linear_encoder):
    ctrl = SizeBandController()
    res = ctrl.converge(
        target=CompressionTarget.band(45_000, 55_000),
        encode=linear_encoder, knob_min=1, knob_max=100, fmt=FileFormat.PDF,
    )
    assert 45_000 <= res.size <= 55_000 and res.landed_in_band


def test_ceiling_only(linear_encoder):
    ctrl = SizeBandController()
    res = ctrl.converge(
        target=CompressionTarget.band(None, 30_000),
        encode=linear_encoder, knob_min=1, knob_max=100, fmt=FileFormat.PDF,
    )
    assert res.size <= 30_000 and res.landed_in_band


def test_floor_reached_by_padding(linear_encoder):
    ctrl = SizeBandController()
    # Max knob 50 -> 50_000 bytes; floor 70_000 must come from padding.
    res = ctrl.converge(
        target=CompressionTarget.band(70_000, 75_000),
        encode=linear_encoder, knob_min=1, knob_max=50, fmt=FileFormat.PDF,
    )
    assert 70_000 <= res.size <= 75_000 and res.landed_in_band
    assert any("pad" in op for op in res.operations)


def test_unreachable_raises_with_bounds(linear_encoder):
    ctrl = SizeBandController()
    with pytest.raises(UnreachableTargetError) as ei:
        ctrl.converge(
            target=CompressionTarget.band(None, 5_000),
            encode=linear_encoder, knob_min=10, knob_max=100, fmt=FileFormat.PDF,
        )
    assert ei.value.min_achievable == 10_000


def test_downscale_rescues_ceiling(tmp_path):
    scale = {"f": 1.0}

    def encode(knob):
        p = tmp_path / f"e_{knob}_{scale['f']}.pdf"
        p.write_bytes(b"\x00" * int(knob * 1000 * scale["f"]))
        return p

    def downscale():
        if scale["f"] <= 0.25:
            return False
        scale["f"] *= 0.5
        return True

    ctrl = SizeBandController()
    res = ctrl.converge(
        target=CompressionTarget.band(None, 5_000),
        encode=encode, knob_min=10, knob_max=100, fmt=FileFormat.PDF, downscale=downscale,
    )
    assert res.size <= 5_000 and res.landed_in_band
    assert scale["f"] < 1.0


def test_pad_disabled_reports_below_floor(linear_encoder):
    ctrl = SizeBandController()
    res = ctrl.converge(
        target=CompressionTarget(mode="size_band", min_bytes=70_000, max_bytes=75_000,
                                 allow_pad=False),
        encode=linear_encoder, knob_min=1, knob_max=50, fmt=FileFormat.PDF,
    )
    assert not res.landed_in_band
    assert res.note and "padding disabled" in res.note
