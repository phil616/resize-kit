"""Exception hierarchy for resize-kit.

Every failure raised by the engine is a subclass of :class:`ResizeKitError`, so
callers (CLI, GUI, tests) can catch the whole family with one ``except`` clause
while still being able to discriminate the specific cause when it matters.

The cardinal rule from ``DESIGN.md`` §1.5 — *fail loudly, never emit a corrupt
file* — is encoded here: an unreachable size band is a first-class, explainable
error (:class:`UnreachableTargetError`) that carries the achievable bounds.
"""

from __future__ import annotations

from typing import Optional


class ResizeKitError(Exception):
    """Base class for every error raised by resize-kit."""


class ConfigurationError(ResizeKitError):
    """The engine was asked to do something it is not configured to do.

    Examples: an invalid :class:`~resize_kit.core.models.CompressionTarget`, or a
    PDF mode that does not exist.
    """


class ToolNotFoundError(ResizeKitError):
    """A required external binary (ffmpeg, soffice, gs, …) could not be located."""

    def __init__(self, tool: str, *, hint: Optional[str] = None) -> None:
        self.tool = tool
        self.hint = hint
        message = f"Required external tool {tool!r} was not found on this system."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)


class ToolExecutionError(ResizeKitError):
    """An external binary ran but exited non-zero or produced no usable output."""

    def __init__(
        self,
        tool: str,
        *,
        returncode: Optional[int] = None,
        stderr: str = "",
        command: Optional[list[str]] = None,
    ) -> None:
        self.tool = tool
        self.returncode = returncode
        self.stderr = stderr
        self.command = command or []
        tail = stderr.strip().splitlines()[-4:]
        detail = ("\n  " + "\n  ".join(tail)) if tail else ""
        super().__init__(
            f"{tool} failed (exit={returncode}).{detail}"
        )


class UnsupportedFormatError(ResizeKitError):
    """The input file's format is not handled by any registered component."""


class DetectionError(ResizeKitError):
    """The input file's format could not be determined or the file is unreadable."""


class MediaProcessingError(ResizeKitError):
    """A single media asset could not be processed.

    Per ``DESIGN.md`` §8, container handlers catch this for individual assets,
    log it, and continue with the rest of the document rather than aborting.
    """


class UnreachableTargetError(ResizeKitError):
    """The requested size band cannot be satisfied even at maximum compression.

    Carries the best the engine could actually achieve so the caller can decide
    whether to relax ``allow_downscale`` or widen the band.
    """

    def __init__(
        self,
        message: str,
        *,
        min_achievable: Optional[int] = None,
        max_achievable: Optional[int] = None,
    ) -> None:
        self.min_achievable = min_achievable
        self.max_achievable = max_achievable
        bounds = []
        if min_achievable is not None:
            bounds.append(f"min achievable={min_achievable} B")
        if max_achievable is not None:
            bounds.append(f"max achievable={max_achievable} B")
        if bounds:
            message = f"{message} ({', '.join(bounds)})"
        super().__init__(message)
