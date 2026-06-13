from __future__ import annotations

import subprocess

import pytest

from resize_kit.core.atomic.audio import AudioCompressor
from resize_kit.core.atomic.video import VideoCompressor
from resize_kit.core.models import CompressionTarget

from .conftest import requires_ffmpeg

pytestmark = [pytest.mark.external, requires_ffmpeg]


def _probe_ok(path):
    return subprocess.run(["ffprobe", "-v", "error", str(path)]).returncode == 0


def test_audio_band(make_mp3, tmp_path):
    src = make_mp3(duration=5, bitrate="256k")
    out = tmp_path / "out.mp3"
    res = AudioCompressor().compress(
        src, CompressionTarget.band(30 * 1024, 60 * 1024), output_path=out
    )
    assert 30 * 1024 <= res.final_bytes <= 60 * 1024 and res.landed_in_band
    assert _probe_ok(out)


def test_audio_encode_quality_monotonic(make_mp3, tmp_path):
    src = make_mp3(duration=5, bitrate="256k")
    ac = AudioCompressor()
    sizes = [
        ac.encode_quality(src, q, output_path=tmp_path / f"q{q}.mp3", work=tmp_path / "w").stat().st_size
        for q in (10, 50, 90)
    ]
    assert sizes == sorted(sizes)


def test_video_ratio(make_mp4, tmp_path):
    src = make_mp4()
    out = tmp_path / "out.mp4"
    res = VideoCompressor().compress(src, CompressionTarget.ratio_of(0.5), output_path=out)
    assert res.final_bytes <= src.stat().st_size
    assert _probe_ok(out)
