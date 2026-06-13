"""Per-job temporary workspace management (DESIGN.md §8).

Every job runs inside its own isolated temp directory that is removed on exit —
success or failure — so partial artifacts never leak. Final outputs are placed
atomically (write-to-temp-then-rename) so a crash mid-write can never leave a
half-written file at the destination.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

from ..logging_config import get_logger

log = get_logger(__name__)


class TempWorkspace:
    """A self-cleaning scratch directory, usable as a context manager."""

    def __init__(self, *, base_dir: Optional[Path] = None, prefix: str = "rk_job_") -> None:
        self._base_dir = base_dir
        self._prefix = prefix
        self.path: Path = Path()

    def __enter__(self) -> "TempWorkspace":
        base = str(self._base_dir) if self._base_dir else None
        self.path = Path(tempfile.mkdtemp(prefix=self._prefix, dir=base))
        log.debug("workspace created: %s", self.path)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.cleanup()

    def subdir(self, name: str) -> Path:
        d = self.path / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cleanup(self) -> None:
        if self.path and self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
            log.debug("workspace removed: %s", self.path)


def atomic_place(src: Path, dst: Path) -> None:
    """Move ``src`` onto ``dst`` atomically where the filesystem allows it.

    Writes through a sibling temp file in ``dst``'s directory and ``os.replace``;
    falls back to a cross-device move if src/dst live on different filesystems.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".rk_tmp_{uuid.uuid4().hex}{dst.suffix}"
    try:
        try:
            os.replace(src, tmp)  # fast path: same filesystem
        except OSError:
            shutil.copyfile(src, tmp)  # cross-device fallback
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
