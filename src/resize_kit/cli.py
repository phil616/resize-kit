"""Command-line interface for resize-kit.

Subcommands:

* ``compress`` — shrink (or size-target) any supported file.
* ``inflate``  — grow a file to a target size with lossless padding.
* ``probe``    — show what resize-kit detects about a file.
* ``doctor``   — report external-tool availability.

Exit codes: 0 = success (landed in band), 3 = finished but outside the band,
2 = target unreachable, 1 = error, 130 = interrupted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .core.adapters.registry import default_registry
from .core.atomic.base import CompressorOptions
from .core.dispatcher import Dispatcher, JobOptions
from .core.exceptions import ResizeKitError, UnreachableTargetError
from .core.models import (
    CompressionResult,
    CompressionTarget,
    PdfMode,
    TargetMode,
)
from .core.sizes import format_ratio, format_size, parse_size
from .logging_config import configure_logging
from .version import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNREACHABLE = 2
EXIT_OUT_OF_BAND = 3
EXIT_INTERRUPTED = 130


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_ERROR

    configure_logging("debug" if getattr(args, "verbose", 0) >= 2 else
                      "info" if getattr(args, "verbose", 0) == 1 else "warning")

    try:
        return args.func(args)
    except UnreachableTargetError as exc:
        _err(f"Target unreachable: {exc}")
        return EXIT_UNREACHABLE
    except ResizeKitError as exc:
        _err(f"Error: {exc}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("Interrupted.")
        return EXIT_INTERRUPTED


# --- argument parsing ---------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resize-kit",
        description="Multi-format lossy compressor with precise size targeting.",
    )
    p.add_argument("--version", action="version", version=f"resize-kit {__version__}")
    sub = p.add_subparsers(dest="command")

    # compress
    c = sub.add_parser("compress", help="Compress / size-target a file.")
    c.add_argument("input", type=Path)
    c.add_argument("-o", "--output", type=Path, default=None)
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--ratio", type=float, help="Shrink to this fraction, e.g. 0.5")
    g.add_argument("--max", dest="max_size", type=str, help="Upper size bound, e.g. 200KB")
    g.add_argument("--exact", type=str, help="Exact target size (±tolerance)")
    g.add_argument("--inflate", type=str, help="Grow to this size (lossless padding)")
    c.add_argument("--min", dest="min_size", type=str, default=None,
                   help="Lower size bound (use with --max for a band)")
    c.add_argument("--pdf-mode", choices=[m.value for m in PdfMode],
                   default=PdfMode.MULTIMEDIA.value)
    c.add_argument("--png-alpha", choices=["quantize", "channel_split"], default="quantize",
                   help="Backend for transparent PNGs (default: quantize)")
    c.add_argument("--keep-ooxml", action="store_true",
                   help="For DOC/PPT: output DOCX/PPTX instead of converting back")
    c.add_argument("--no-downscale", action="store_true",
                   help="Disallow resolution/sample-rate reduction")
    c.add_argument("--no-pad", action="store_true",
                   help="Disallow padding to reach the lower bound")
    c.add_argument("--tolerance", type=str, default=None,
                   help="EXACT-mode tolerance, e.g. 2KB (default 1KB)")
    c.add_argument("-v", "--verbose", action="count", default=0)
    c.set_defaults(func=_cmd_compress)

    # inflate
    i = sub.add_parser("inflate", help="Grow a file to a target size (lossless).")
    i.add_argument("input", type=Path)
    i.add_argument("--to", dest="to_size", type=str, required=True)
    i.add_argument("-o", "--output", type=Path, default=None)
    i.add_argument("-v", "--verbose", action="count", default=0)
    i.set_defaults(func=_cmd_inflate)

    # probe
    pr = sub.add_parser("probe", help="Show detected format / media info.")
    pr.add_argument("input", type=Path)
    pr.add_argument("-v", "--verbose", action="count", default=0)
    pr.set_defaults(func=_cmd_probe)

    # doctor
    do = sub.add_parser("doctor", help="Check external tool availability.")
    do.add_argument("-v", "--verbose", action="count", default=0)
    do.set_defaults(func=_cmd_doctor)

    return p


# --- command implementations --------------------------------------------------


def _cmd_compress(args: argparse.Namespace) -> int:
    target = _build_target(args)
    options = JobOptions(
        pdf_mode=PdfMode(args.pdf_mode),
        keep_ooxml=args.keep_ooxml,
        compressor_options=CompressorOptions(png_alpha_strategy=args.png_alpha),
    )
    dispatcher = Dispatcher(options=options)
    result = dispatcher.compress(
        args.input, target, args.output, on_progress=_progress(args.verbose)
    )
    _print_result(result)
    return EXIT_OK if result.landed_in_band else EXIT_OUT_OF_BAND


def _cmd_inflate(args: argparse.Namespace) -> int:
    dispatcher = Dispatcher()
    result = dispatcher.inflate(
        args.input, parse_size(args.to_size), args.output, on_progress=_progress(args.verbose)
    )
    _print_result(result)
    return EXIT_OK if result.landed_in_band else EXIT_OUT_OF_BAND


def _cmd_probe(args: argparse.Namespace) -> int:
    info = Dispatcher().probe(args.input)
    print(f"File:        {info['path']}")
    print(f"Size:        {format_size(info['size_bytes'])} ({info['size_bytes']} B)")
    print(f"Format:      {info['format']}")
    print(f"Media class: {info['media_class']}")
    print(f"Paddable:    {'yes' if info['pad_supported'] else 'no'}")
    if "duration_s" in info:
        print(f"Duration:    {info['duration_s']} s")
    if info.get("overall_bitrate"):
        print(f"Bitrate:     {info['overall_bitrate'] // 1000} kbps")
    for s in info.get("streams", []):
        print(f"  stream:    {s['type']} / {s['codec']}")
    if "probe_error" in info:
        print(f"  (probe note: {info['probe_error']})")
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    registry = default_registry()
    print(f"resize-kit {__version__} — external tool check\n")
    all_required_ok = True
    for status in registry.statuses():
        mark = "OK " if status.available else ("MISSING" if status.required else "absent")
        req = "required" if status.required else "optional"
        print(f"  [{mark:>7}] {status.name:<12} ({req}) — {status.purpose}")
        if status.available:
            print(f"             path: {status.path}")
        if status.required and not status.available:
            all_required_ok = False
    print()
    if all_required_ok:
        print("All required tools are available.")
        return EXIT_OK
    print("Some required tools are missing; image/audio/video jobs may fail.")
    return EXIT_ERROR


# --- helpers ------------------------------------------------------------------


def _build_target(args: argparse.Namespace) -> CompressionTarget:
    common = {
        "allow_downscale": not args.no_downscale,
        "allow_pad": not args.no_pad,
    }
    if args.ratio is not None:
        return CompressionTarget(mode=TargetMode.RATIO, ratio=args.ratio, **common)
    if args.inflate is not None:
        return CompressionTarget.inflate_to(parse_size(args.inflate), **common)
    if args.exact is not None:
        tol = parse_size(args.tolerance) if args.tolerance else 1024
        return CompressionTarget(
            mode=TargetMode.EXACT, max_bytes=parse_size(args.exact),
            exact_tolerance=tol, **common,
        )
    # --max (optionally with --min) -> band
    max_b = parse_size(args.max_size) if args.max_size else None
    min_b = parse_size(args.min_size) if args.min_size else None
    return CompressionTarget(
        mode=TargetMode.SIZE_BAND, min_bytes=min_b, max_bytes=max_b, **common
    )


def _progress(verbose: int):
    if verbose <= 0:
        return None

    def cb(msg: str) -> None:
        print(f"  · {msg}", file=sys.stderr)

    return cb


def _print_result(r: CompressionResult) -> None:
    status = "landed in band" if r.landed_in_band else "OUTSIDE band"
    print(f"Output:   {r.output_path}")
    print(
        f"Size:     {format_size(r.original_bytes)} -> {format_size(r.final_bytes)} "
        f"({format_ratio(r.original_bytes, r.final_bytes)} saved)  [{status}]"
    )
    if r.note:
        print(f"Note:     {r.note}")
    compressed_children = [a for a in r.children if a.status == "compressed"]
    if r.children:
        print(f"Assets:   {len(r.children)} embedded "
              f"({len(compressed_children)} recompressed)")
        for a in r.children:
            print(
                f"  - {a.name:<24} {a.status:<10} "
                f"{format_size(a.original_bytes)} -> {format_size(a.final_bytes)}"
                + (f"  ({a.note})" if a.note else "")
            )


def _err(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
