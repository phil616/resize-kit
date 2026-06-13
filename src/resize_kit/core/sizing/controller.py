"""SizeBandController — converge an encoder's output into a target size band.

This is the cross-cutting algorithm of DESIGN.md §6:

* **Ceiling** is reached by binary search over a monotonic quality *knob*
  (JPEG quality, audio bitrate, video CRF-as-quality): find the *highest*
  quality whose output is ``<= max_bytes``.
* **Floor** is reached by format-legal **padding** (:mod:`.padding`): bytes a
  decoder ignores, added with byte precision.
* When even the lowest quality overshoots the ceiling, an optional
  **downscale** callback (lower resolution / sample rate) is applied and the
  search restarts. If downscaling is exhausted or disallowed, the job fails
  loudly with the achievable bounds (never a corrupt file).

The controller is encoder-agnostic: callers supply an ``encode(knob) -> Path``
closure and the integer knob range. Higher knob **must** yield a larger (or
equal) file. Results are cached per knob so binary search never re-encodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ...logging_config import get_logger
from ..exceptions import UnreachableTargetError
from ..media_type import FileFormat
from ..models import CompressionTarget, TargetMode
from . import padding as padding_mod

log = get_logger(__name__)

EncodeFn = Callable[[int], Path]
DownscaleFn = Callable[[], bool]
ProgressFn = Callable[[str], None]


@dataclass(slots=True)
class ConvergeResult:
    path: Path
    size: int
    landed_in_band: bool
    operations: list[str] = field(default_factory=list)
    note: Optional[str] = None


class SizeBandController:
    """Drive an encoder to a target size band via binary search + padding."""

    def __init__(self, *, max_iterations: int = 12) -> None:
        self.max_iterations = max_iterations

    def converge(
        self,
        *,
        target: CompressionTarget,
        encode: EncodeFn,
        knob_min: int,
        knob_max: int,
        fmt: FileFormat,
        downscale: Optional[DownscaleFn] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> ConvergeResult:
        if knob_min > knob_max:
            raise ValueError("knob_min must be <= knob_max")
        ops: list[str] = []
        cache: dict[int, tuple[Path, int]] = {}

        def emit(msg: str) -> None:
            log.debug(msg)
            if on_progress:
                on_progress(msg)

        def run_knob(knob: int) -> tuple[Path, int]:
            knob = max(knob_min, min(knob_max, knob))
            if knob not in cache:
                p = encode(knob)
                cache[knob] = (p, p.stat().st_size)
                emit(f"knob={knob} -> {cache[knob][1]} B")
            return cache[knob]

        downscale_steps = 0
        while True:
            result = self._converge_once(
                target=target,
                run_knob=run_knob,
                knob_min=knob_min,
                knob_max=knob_max,
                ops=ops,
            )
            if result is not None:
                return self._finalize(result, target, fmt, ops, emit)

            # Lowest quality still overshoots the ceiling -> try downscaling.
            if target.allow_downscale and downscale is not None and downscale():
                downscale_steps += 1
                cache.clear()
                ops.append(f"downscale step {downscale_steps}")
                emit(f"ceiling unreachable; downscaled (step {downscale_steps}) and retrying")
                continue

            # No more knobs to turn: report the smallest size we could achieve.
            _, smallest = run_knob(knob_min)
            raise UnreachableTargetError(
                "Could not compress below the ceiling even at maximum compression"
                + ("/downscaling" if downscale is not None else ""),
                min_achievable=smallest,
                max_achievable=run_knob(knob_max)[1],
            )

    # --- one pass at the current resolution --------------------------------------

    def _converge_once(
        self,
        *,
        target: CompressionTarget,
        run_knob: Callable[[int], tuple[Path, int]],
        knob_min: int,
        knob_max: int,
        ops: list[str],
    ) -> Optional[tuple[Path, int]]:
        """Return (path, size) with size <= ceiling, or None if downscale needed."""
        # Floor-only / no ceiling: keep top quality, padding will lift the floor.
        if not target.has_ceiling:
            path, size = run_knob(knob_max)
            ops.append(f"encoded at max quality (knob={knob_max})")
            return (path, size)

        max_bytes = target.max_bytes
        assert max_bytes is not None

        # 1) Highest quality already under the ceiling? Then we are done (subject
        #    to the floor, which padding handles downstream).
        hi_path, hi_size = run_knob(knob_max)
        if hi_size <= max_bytes:
            ops.append(f"max quality already <= ceiling (knob={knob_max})")
            return (hi_path, hi_size)

        # 2) Even the lowest quality overshoots -> caller must downscale.
        lo_path, lo_size = run_knob(knob_min)
        if lo_size > max_bytes:
            return None

        # 3) Binary search for the largest knob with size <= ceiling.
        best = (lo_path, lo_size)
        lo, hi = knob_min, knob_max
        iterations = 0
        while lo <= hi and iterations < self.max_iterations:
            iterations += 1
            mid = (lo + hi) // 2
            path, size = run_knob(mid)
            if size <= max_bytes:
                best = (path, size)
                lo = mid + 1
            else:
                hi = mid - 1
        ops.append(f"binary search -> {best[1]} B (<= {max_bytes})")
        return best

    # --- floor / padding ---------------------------------------------------------

    def _finalize(
        self,
        result: tuple[Path, int],
        target: CompressionTarget,
        fmt: FileFormat,
        ops: list[str],
        emit: ProgressFn,
    ) -> ConvergeResult:
        path, size = result

        if target.in_band(size):
            return ConvergeResult(path=path, size=size, landed_in_band=True, operations=list(ops))

        # Below the floor: pad up if allowed and a carrier exists.
        if target.has_floor and size < (target.min_bytes or 0):
            return self._apply_padding(path, target, fmt, ops, emit)

        # Above the ceiling with no further recourse (shouldn't happen here).
        return ConvergeResult(
            path=path,
            size=size,
            landed_in_band=target.in_band(size),
            operations=list(ops),
            note="Output sits outside the requested band.",
        )

    def _apply_padding(
        self,
        path: Path,
        target: CompressionTarget,
        fmt: FileFormat,
        ops: list[str],
        emit: ProgressFn,
    ) -> ConvergeResult:
        floor = target.min_bytes or 0
        pad_target = self._pad_target(target, floor)

        if not target.allow_pad:
            return ConvergeResult(
                path=path,
                size=path.stat().st_size,
                landed_in_band=False,
                operations=list(ops),
                note=f"Below floor by {floor - path.stat().st_size} B; padding disabled.",
            )
        if not padding_mod.supports_padding(fmt):
            return ConvergeResult(
                path=path,
                size=path.stat().st_size,
                landed_in_band=False,
                operations=list(ops),
                note=f"Below floor; no format-legal padding carrier for {fmt.value!r}.",
            )

        before = path.stat().st_size
        final = padding_mod.pad_to_size(path, fmt, pad_target)
        ops.append(f"padded +{final - before} B to reach floor")
        emit(f"padded {before} -> {final} B (target {pad_target})")
        return ConvergeResult(
            path=path,
            size=final,
            landed_in_band=target.in_band(final),
            operations=list(ops),
            note=f"Added {final - before} B of format-legal padding.",
        )

    @staticmethod
    def _pad_target(target: CompressionTarget, floor: int) -> int:
        """Pick the byte target padding should aim for."""
        if target.mode is TargetMode.EXACT and target.min_bytes and target.max_bytes:
            # Aim for the exact requested center of the tolerance window.
            return (target.min_bytes + target.max_bytes) // 2
        return floor
