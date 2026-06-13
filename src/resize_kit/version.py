"""Single source of truth for project identity and versioning.

Version scheme: Semantic Versioning ``MAJOR.MINOR.PATCH`` (https://semver.org).
The project starts at ``0.1.0``; bump MINOR for new features, PATCH for fixes,
and MAJOR once the public API/behaviour is declared stable (1.0.0).

Edit the author / repository constants here — they flow into the CLI ``--version``
output, the GUI footer, and packaging metadata.
"""

from __future__ import annotations

__version__ = "0.1.0"
__app_name__ = "resize-kit"
__author__ = "phil616"
__author_email__ = "phil616@163.com"
__repository__ = "https://github.com/phil616/resize-kit"
__description__ = "多格式有损压缩工具 · 精确目标体积控制"

# Convenience strings reused by the UI / CLI.
__version_tag__ = f"v{__version__}"
