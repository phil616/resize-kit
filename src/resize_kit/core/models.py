"""Public data models — the contract between the engine and its callers.

These mirror ``DESIGN.md`` §3 (CompressionTarget / CompressionResult) and add
the small amount of operational metadata an enterprise tool needs (an audit
trail of operations, per-asset results inside containers).

The models are deliberately plain dataclasses with validation in
``__post_init__`` so they can be constructed from a CLI, a GUI form, or a JSON
payload without any framework coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .exceptions import ConfigurationError
from .media_type import FileFormat, MediaClass


class TargetMode(str, Enum):
    """How the desired output size is expressed."""

    RATIO = "ratio"  # shrink to a fraction of the original size
    SIZE_BAND = "size_band"  # land within [min_bytes, max_bytes]
    EXACT = "exact"  # land on a single byte target (min == max, tiny tolerance)
    INFLATE = "inflate"  # grow the file to a target size via legal padding


class PdfMode(str, Enum):
    """PDF compression strategy (see DESIGN.md §5.3)."""

    MULTIMEDIA = "multimedia"  # recompress embedded images, keep vectors/text/forms
    RASTERIZE = "rasterize"  # render each page to a bitmap, discard everything else


# A small default tolerance for EXACT mode, so we are not forced to hit a single
# byte through lossy encoders. Padding can still hit an exact byte when asked.
DEFAULT_EXACT_TOLERANCE = 1024  # ±1 KiB


@dataclass(slots=True)
class CompressionTarget:
    """What "done" means for a compression job (DESIGN.md §3.1)."""

    mode: TargetMode = TargetMode.RATIO
    ratio: Optional[float] = None
    min_bytes: Optional[int] = None
    max_bytes: Optional[int] = None
    allow_pad: bool = True
    allow_downscale: bool = True
    # Optional override for EXACT tolerance.
    exact_tolerance: int = DEFAULT_EXACT_TOLERANCE

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = TargetMode(self.mode)

        if self.mode is TargetMode.RATIO:
            if self.ratio is None:
                raise ConfigurationError("RATIO mode requires 'ratio'.")
            if not (0.0 < self.ratio <= 1.0):
                raise ConfigurationError(
                    f"ratio must be in (0, 1], got {self.ratio}."
                )
        elif self.mode is TargetMode.SIZE_BAND:
            if self.min_bytes is None and self.max_bytes is None:
                raise ConfigurationError(
                    "SIZE_BAND mode requires at least one of min_bytes/max_bytes."
                )
            self._validate_band()
        elif self.mode is TargetMode.EXACT:
            target = self.max_bytes if self.max_bytes is not None else self.min_bytes
            if target is None:
                raise ConfigurationError(
                    "EXACT mode requires a target via max_bytes (or min_bytes)."
                )
            tol = self.exact_tolerance
            self.min_bytes = max(0, target - tol)
            self.max_bytes = target + tol
        elif self.mode is TargetMode.INFLATE:
            target = self.min_bytes if self.min_bytes is not None else self.max_bytes
            if target is None:
                raise ConfigurationError(
                    "INFLATE mode requires a target size via min_bytes (or max_bytes)."
                )
            # Inflate aims at a floor; max is open unless explicitly capped.
            self.min_bytes = target
            if self.max_bytes is None:
                self.max_bytes = None

    def _validate_band(self) -> None:
        if (
            self.min_bytes is not None
            and self.max_bytes is not None
            and self.min_bytes > self.max_bytes
        ):
            raise ConfigurationError(
                f"min_bytes ({self.min_bytes}) must not exceed "
                f"max_bytes ({self.max_bytes})."
            )

    # --- convenience constructors -------------------------------------------------

    @classmethod
    def ratio_of(cls, ratio: float, **kw) -> "CompressionTarget":
        return cls(mode=TargetMode.RATIO, ratio=ratio, **kw)

    @classmethod
    def band(
        cls, min_bytes: Optional[int], max_bytes: Optional[int], **kw
    ) -> "CompressionTarget":
        return cls(
            mode=TargetMode.SIZE_BAND, min_bytes=min_bytes, max_bytes=max_bytes, **kw
        )

    @classmethod
    def exact(cls, target_bytes: int, **kw) -> "CompressionTarget":
        return cls(mode=TargetMode.EXACT, max_bytes=target_bytes, **kw)

    @classmethod
    def inflate_to(cls, target_bytes: int, **kw) -> "CompressionTarget":
        return cls(mode=TargetMode.INFLATE, min_bytes=target_bytes, **kw)

    # --- predicates used by the size controller -----------------------------------

    def in_band(self, size: int) -> bool:
        """True if ``size`` satisfies both bounds (open bounds always satisfied)."""
        if self.min_bytes is not None and size < self.min_bytes:
            return False
        if self.max_bytes is not None and size > self.max_bytes:
            return False
        return True

    @property
    def has_ceiling(self) -> bool:
        return self.max_bytes is not None

    @property
    def has_floor(self) -> bool:
        return self.min_bytes is not None

    def resolve(self, original_bytes: int) -> "CompressionTarget":
        """Return a concrete SIZE_BAND/EXACT/INFLATE target for ``original_bytes``.

        RATIO is the only relative mode; it is turned into a *ceiling* of
        ``round(ratio * original)`` (no floor — landing below the ratio is at
        least as good as hitting it). Every other mode is already absolute and is
        returned unchanged.
        """
        if self.mode is not TargetMode.RATIO:
            return self
        assert self.ratio is not None
        ceiling = max(1, round(self.ratio * original_bytes))
        return CompressionTarget(
            mode=TargetMode.SIZE_BAND,
            min_bytes=None,
            max_bytes=ceiling,
            allow_pad=self.allow_pad,
            allow_downscale=self.allow_downscale,
        )


@dataclass(slots=True)
class CompressionResult:
    """Outcome of a single compression job (DESIGN.md §3.2)."""

    output_path: str
    original_bytes: int
    final_bytes: int
    landed_in_band: bool
    media_class: MediaClass = MediaClass.UNKNOWN
    file_format: FileFormat = FileFormat.UNKNOWN
    operations: list[str] = field(default_factory=list)
    note: Optional[str] = None
    # For container jobs: per-asset sub-results, for auditability.
    children: list["AssetResult"] = field(default_factory=list)

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.final_bytes

    @property
    def ratio_achieved(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return self.final_bytes / self.original_bytes

    def add_op(self, op: str) -> None:
        self.operations.append(op)


@dataclass(slots=True)
class AssetResult:
    """Result for a single embedded asset inside a container."""

    name: str
    media_class: MediaClass
    original_bytes: int
    final_bytes: int
    status: str  # "compressed" | "skipped" | "failed" | "unchanged"
    note: Optional[str] = None
