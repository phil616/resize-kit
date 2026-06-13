"""Robust subprocess execution helpers shared by every Layer 0 adapter.

Centralizing process spawning here means timeouts, output capture, and error
translation (-> :class:`ToolExecutionError`) are implemented once and behave
identically for ffmpeg, soffice, ghostscript and friends.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ...logging_config import get_logger
from ..exceptions import ToolExecutionError, ToolNotFoundError

log = get_logger(__name__)


@dataclass(slots=True)
class CommandResult:
    """Captured result of a finished subprocess."""

    returncode: int
    stdout: str
    stderr: str
    command: list[str]


def which(executable: str) -> Optional[str]:
    """Locate ``executable`` on PATH, returning its absolute path or None."""
    return shutil.which(executable)


def run(
    command: Sequence[str],
    *,
    tool: str,
    timeout: Optional[float] = None,
    cwd: Optional[Path] = None,
    check: bool = True,
    env: Optional[dict[str, str]] = None,
) -> CommandResult:
    """Run a command, capturing stdout/stderr as text.

    Args:
        command: argv list. ``command[0]`` must be an absolute path or on PATH.
        tool: human label used in error messages.
        timeout: seconds before the process is killed (None = no limit).
        cwd: working directory.
        check: if True, a non-zero exit raises :class:`ToolExecutionError`.

    Raises:
        ToolNotFoundError: if the executable cannot be spawned.
        ToolExecutionError: on timeout or (when ``check``) non-zero exit.
    """
    argv = [str(c) for c in command]
    log.debug("exec [%s]: %s", tool, " ".join(argv))
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(tool) from exc
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        raise ToolExecutionError(
            tool,
            returncode=None,
            stderr=f"Timed out after {timeout}s.\n{stderr}",
            command=argv,
        ) from exc

    result = CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        command=argv,
    )
    if check and completed.returncode != 0:
        raise ToolExecutionError(
            tool,
            returncode=completed.returncode,
            stderr=result.stderr,
            command=argv,
        )
    return result
