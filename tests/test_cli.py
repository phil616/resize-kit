from __future__ import annotations

from PIL import Image

from resize_kit.cli import main


def test_cli_probe(make_jpeg, capsys):
    rc = main(["probe", str(make_jpeg())])
    out = capsys.readouterr().out
    assert rc == 0 and "Format:      jpeg" in out


def test_cli_doctor(capsys):
    main(["doctor"])
    out = capsys.readouterr().out
    assert "ffmpeg" in out


def test_cli_compress_band(make_jpeg, tmp_path, capsys):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    rc = main(["compress", str(src), "--max", "60KB", "--min", "40KB", "-o", str(out)])
    assert rc == 0
    assert 40 * 1024 <= out.stat().st_size <= 60 * 1024


def test_cli_compress_ratio(make_jpeg, tmp_path):
    src = make_jpeg(w=800, h=600)
    out = tmp_path / "out.jpg"
    rc = main(["compress", str(src), "--ratio", "0.3", "-o", str(out)])
    assert rc == 0 and out.stat().st_size <= src.stat().st_size * 0.3


def test_cli_inflate_lossless(make_jpeg, tmp_path):
    src = make_jpeg(w=300, h=300, quality=80)
    out = tmp_path / "big.jpg"
    rc = main(["inflate", str(src), "--to", "400KB", "-o", str(out)])
    assert rc == 0
    assert abs(out.stat().st_size - 400 * 1024) <= 1024
    assert Image.open(src).tobytes() == Image.open(out).tobytes()


def test_cli_unreachable_returns_code_2(make_jpeg, tmp_path):
    src = make_jpeg(w=64, h=64)
    out = tmp_path / "out.jpg"
    # 10 bytes is impossible for any real JPEG -> unreachable.
    rc = main(["compress", str(src), "--max", "10", "--no-downscale", "-o", str(out)])
    assert rc == 2
