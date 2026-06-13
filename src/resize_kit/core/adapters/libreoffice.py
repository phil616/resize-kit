"""LibreOffice (soffice) adapter (Layer 0).

Used only for the legacy-binary Office round-trip (DESIGN.md §5.2):
DOC <-> DOCX and PPT <-> PPTX. We never edit OLE2 binaries directly; we
normalize to OOXML, process, and convert back.

soffice is finicky about concurrent instances sharing one user profile, so we
hand it a throwaway ``-env:UserInstallation`` profile per call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..exceptions import ToolExecutionError
from .process import run, which

log = get_logger(__name__)

# Output filter names understood by `soffice --convert-to`.
CONVERT_FILTERS: dict[str, str] = {
    "docx": "docx:MS Word 2007 XML",
    "doc": "doc:MS Word 97",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "ppt": "ppt:MS PowerPoint 97",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
}


class LibreOfficeAdapter:
    """Convert documents between formats via headless LibreOffice."""

    def __init__(self, soffice_path: Optional[str] = None) -> None:
        self.soffice_path = (
            soffice_path or which("soffice") or which("libreoffice") or "soffice"
        )

    def is_available(self) -> bool:
        return (
            which(self.soffice_path) is not None
            or which("soffice") is not None
            or which("libreoffice") is not None
            or Path(self.soffice_path).exists()
        )

    def convert(
        self,
        input_path: Path,
        target_ext: str,
        out_dir: Path,
        *,
        profile_dir: Optional[Path] = None,
        timeout: float = 300,
    ) -> Path:
        """Convert ``input_path`` to ``target_ext`` inside ``out_dir``.

        Returns the path of the produced file. Raises :class:`ToolExecutionError`
        if soffice runs but no output file appears (it sometimes exits 0 yet
        silently fails on a corrupt input).
        """
        target_ext = target_ext.lower().lstrip(".")
        convert_arg = CONVERT_FILTERS.get(target_ext, target_ext)
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [self.soffice_path, "--headless", "--norestore"]
        if profile_dir is not None:
            profile_dir.mkdir(parents=True, exist_ok=True)
            # Path.as_uri() yields a platform-correct file URL: file:///home/...
            # on POSIX and file:///C:/... on Windows (a bare f"file://{path}"
            # would be malformed on Windows).
            cmd.append(f"-env:UserInstallation={profile_dir.resolve().as_uri()}")
        cmd += [
            "--convert-to",
            convert_arg,
            "--outdir",
            str(out_dir),
            str(input_path),
        ]

        result = run(cmd, tool="soffice", timeout=timeout)

        expected = out_dir / f"{input_path.stem}.{target_ext}"
        if expected.exists():
            return expected
        # soffice names by stem; if collision/odd casing, fall back to newest match.
        candidates = sorted(
            out_dir.glob(f"*.{target_ext}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        raise ToolExecutionError(
            "soffice",
            returncode=result.returncode,
            stderr=(
                f"No .{target_ext} produced for {input_path.name}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            ),
            command=result.command,
        )
