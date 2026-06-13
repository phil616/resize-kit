"""Small reusable widgets for the resize-kit GUI."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import QLabel


class DropLabel(QLabel):
    """A label that accepts a single dropped file and emits its path."""

    fileDropped = pyqtSignal(str)

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("dropLabel")
        self.setMinimumHeight(90)
        self.setWordWrap(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt naming)
        if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self._restyle()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dragActive", False)
        self._restyle()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("dragActive", False)
        self._restyle()
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path and Path(path).is_file():
                self.fileDropped.emit(path)
                event.acceptProposedAction()

    def _restyle(self) -> None:
        # Force a style refresh so the [dragActive="true"] QSS selector applies.
        self.style().unpolish(self)
        self.style().polish(self)
