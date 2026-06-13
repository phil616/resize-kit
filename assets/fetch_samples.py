#!/usr/bin/env python3
"""Download public sample media and run resize-kit on them (integration demo).

This is NOT part of the pytest suite (which is hermetic and offline). It exists
to exercise the engine against *real-world* files from public sources, which is
useful for manual validation and as living documentation of expected behaviour.

Usage::

    python assets/fetch_samples.py            # download + compress everything
    python assets/fetch_samples.py --no-run   # download only

All network and tool failures are handled gracefully (the item is skipped).
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Make the package importable when run straight from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from resize_kit.core.dispatcher import Dispatcher, JobOptions  # noqa: E402
from resize_kit.core.exceptions import ResizeKitError  # noqa: E402
from resize_kit.core.models import CompressionTarget, PdfMode  # noqa: E402
from resize_kit.core.sizes import format_ratio, format_size  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

KB = 1024


@dataclass
class Sample:
    url: str
    filename: str
    target: CompressionTarget
    options: JobOptions
    label: str


SAMPLES = [
    Sample(
        "https://download.samplelib.com/jpeg/sample-clouds-400x300.jpg",
        "clouds.jpg",
        CompressionTarget.band(20 * KB, 30 * KB),
        JobOptions(),
        "JPEG -> size band [20–30 KiB]",
    ),
    Sample(
        "https://download.samplelib.com/png/sample-boat-400x300.png",
        "boat.png",
        CompressionTarget.ratio_of(0.3),
        JobOptions(),
        "PNG  -> ratio 0.3 (palette quantization)",
    ),
    Sample(
        "https://download.samplelib.com/mp3/sample-9s.mp3",
        "tone.mp3",
        CompressionTarget.band(40 * KB, 70 * KB),
        JobOptions(),
        "MP3  -> size band [40–70 KiB]",
    ),
    Sample(
        "https://download.samplelib.com/mp4/sample-5s.mp4",
        "clip.mp4",
        CompressionTarget.exact(800 * KB, exact_tolerance=60 * KB),
        JobOptions(),
        "MP4  -> exact 800 KiB (±60 KiB)",
    ),
    Sample(
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "dummy.pdf",
        CompressionTarget.inflate_to(80 * KB),
        JobOptions(pdf_mode=PdfMode.MULTIMEDIA),
        "PDF  -> inflate to 80 KiB (lossless; text-only PDF has no images to shrink)",
    ),
]


def download(sample: Sample) -> Path | None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SAMPLES_DIR / sample.filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        print(f"  downloading {sample.filename} …", flush=True)
        req = urllib.request.Request(sample.url, headers={"User-Agent": "resize-kit/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
            fh.write(resp.read())
        return dest
    except Exception as exc:  # noqa: BLE001 - demo script: report and skip
        print(f"    ! download failed: {exc}")
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-run", action="store_true", help="download only, do not compress")
    args = parser.parse_args(argv)

    print("resize-kit · public sample integration demo\n")
    results = []
    for sample in SAMPLES:
        print(f"• {sample.label}")
        src = download(sample)
        if src is None:
            continue
        if args.no_run:
            continue
        out = SAMPLES_DIR / f"compressed_{sample.filename}"
        try:
            dispatcher = Dispatcher(options=sample.options)
            res = dispatcher.compress(src, sample.target, out)
            print(
                f"    {format_size(res.original_bytes)} -> {format_size(res.final_bytes)}"
                f"  ({format_ratio(res.original_bytes, res.final_bytes)} saved)"
                f"  [{'landed' if res.landed_in_band else 'OUT OF BAND'}]"
            )
            results.append((sample.label, True))
        except ResizeKitError as exc:
            print(f"    ! {exc}")
            results.append((sample.label, False))
        print()

    ok = sum(1 for _, good in results if good)
    print(f"Done: {ok}/{len(results)} jobs landed in band.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
