"""QApplication bootstrap and the GUI entry point."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from ..logging_config import configure_logging

_STYLESHEET = """
QWidget { font-size: 13px; color: #1f2933; }
#title { font-size: 24px; font-weight: 700; color: #102a43; }
#subtitle { color: #627d98; font-size: 13px; }
#toolStatus { color: #486581; font-size: 12px; }
#infoLabel { color: #627d98; }
#footer { color: #829ab1; font-size: 11px; padding-top: 6px; }
#footer a { color: #2680c2; text-decoration: none; }
QGroupBox {
    font-weight: 600; border: 1px solid #d9e2ec; border-radius: 8px;
    margin-top: 12px; padding: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #334e68; }
#dropLabel {
    border: 2px dashed #9fb3c8; border-radius: 8px; color: #627d98;
    background: #f0f4f8; padding: 12px;
}
#dropLabel[dragActive="true"] { border-color: #2680c2; background: #e6f0fb; color: #102a43; }
QPushButton {
    background: #e4ebf1; border: 1px solid #bcccdc; border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { background: #d9e2ec; }
QPushButton:disabled { color: #9fb3c8; background: #f0f4f8; }
#runButton {
    background: #2680c2; color: white; border: none; font-weight: 700; padding: 10px;
}
#runButton:hover { background: #186faf; }
#runButton:disabled { background: #9fb3c8; }
QLineEdit, QComboBox {
    border: 1px solid #bcccdc; border-radius: 5px; padding: 5px; min-height: 18px;
}
QPlainTextEdit#log {
    background: #102a43; color: #bcccdc; border-radius: 6px;
    font-family: monospace; font-size: 12px;
}
QProgressBar { border: 1px solid #d9e2ec; border-radius: 5px; text-align: center; height: 8px; }
QProgressBar::chunk { background: #2680c2; border-radius: 5px; }
QTableWidget { border: 1px solid #d9e2ec; border-radius: 6px; }
"""


def build_application(argv: Optional[Sequence[str]] = None):
    """Create (or reuse) the QApplication and the main window."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(list(argv) if argv else sys.argv)
    app.setApplicationName("resize-kit")
    app.setStyleSheet(_STYLESHEET)

    from .main_window import MainWindow

    window = MainWindow()
    return app, window


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_logging("info")
    app, window = build_application(argv)
    window.show()
    return app.exec_()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
