"""Main application window for resize-kit."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QThread
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.adapters.registry import default_registry
from ..core.atomic.base import CompressorOptions
from ..core.detect import detect_format
from ..core.dispatcher import JobOptions
from ..core.exceptions import ConfigurationError, ResizeKitError
from ..core.media_type import FileFormat
from ..core.models import CompressionResult, CompressionTarget, PdfMode, TargetMode
from ..core.sizes import format_ratio, format_size, parse_size
from ..version import __version__
from .worker import CompressionWorker

_MODE_ORDER = [TargetMode.RATIO, TargetMode.SIZE_BAND, TargetMode.EXACT, TargetMode.INFLATE]
_MODE_LABELS = {
    TargetMode.RATIO: "Ratio (shrink to a fraction)",
    TargetMode.SIZE_BAND: "Size band (min ≤ size ≤ max)",
    TargetMode.EXACT: "Exact size (±tolerance)",
    TargetMode.INFLATE: "Inflate (grow to size, lossless)",
}


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"resize-kit {__version__}")
        self.setMinimumSize(740, 880)
        self._input_path: Optional[Path] = None
        self._input_format: FileFormat = FileFormat.UNKNOWN
        self._thread: Optional[QThread] = None
        self._worker: Optional[CompressionWorker] = None
        self._build_ui()
        self._refresh_tool_status()

    # --- UI construction ---------------------------------------------------------

    def _build_ui(self) -> None:
        # Everything lives inside a scroll area so controls keep their natural
        # size on small screens instead of being compressed/clipped.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QLabel("resize-kit")
        header.setObjectName("title")
        root.addWidget(header)
        self.tool_status = QLabel()
        self.tool_status.setObjectName("toolStatus")
        root.addWidget(self.tool_status)

        root.addWidget(self._build_input_group())
        root.addWidget(self._build_target_group())
        root.addWidget(self._build_options_group())
        root.addWidget(self._build_output_group())
        # Re-suggest the output extension when the DOC/PPT escape hatch toggles.
        self.keep_ooxml.toggled.connect(self._suggest_output)

        self.run_button = QPushButton("Compress")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._on_run)
        self.run_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel)
        self.cancel_button.setEnabled(False)
        run_row = QHBoxLayout()
        run_row.addWidget(self.run_button, 3)
        run_row.addWidget(self.cancel_button, 1)
        root.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        root.addWidget(self._build_result_group(), 1)

    def _build_input_group(self) -> QGroupBox:
        box = QGroupBox("1 · Input file")
        layout = QVBoxLayout(box)
        from .widgets import DropLabel

        self.drop = DropLabel("Drag a file here, or click Browse…")
        self.drop.fileDropped.connect(self._select_file)
        layout.addWidget(self.drop)

        row = QHBoxLayout()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_input)
        self.input_info = QLabel("No file selected.")
        self.input_info.setObjectName("infoLabel")
        row.addWidget(browse)
        row.addWidget(self.input_info, 1)
        layout.addLayout(row)
        return box

    def _build_target_group(self) -> QGroupBox:
        box = QGroupBox("2 · Target")
        layout = QVBoxLayout(box)

        self.mode_combo = QComboBox()
        for mode in _MODE_ORDER:
            self.mode_combo.addItem(_MODE_LABELS[mode], mode)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._page_ratio())
        self.mode_stack.addWidget(self._page_band())
        self.mode_stack.addWidget(self._page_exact())
        self.mode_stack.addWidget(self._page_inflate())
        # All pages share one footprint; reserve enough height for the tallest
        # so switching modes never clips controls.
        self.mode_stack.setMinimumHeight(96)
        layout.addWidget(self.mode_stack)
        return box

    def _page_ratio(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.ratio_slider = QSlider(Qt.Horizontal)
        self.ratio_slider.setRange(5, 100)
        self.ratio_slider.setValue(50)
        self.ratio_value = QLabel("50% of original")
        self.ratio_slider.valueChanged.connect(
            lambda v: self.ratio_value.setText(f"{v}% of original")
        )
        lay.addRow("Compress to:", self.ratio_slider)
        lay.addRow("", self.ratio_value)
        return w

    def _page_band(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.band_min = QLineEdit()
        self.band_min.setPlaceholderText("optional, e.g. 150KB")
        self.band_max = QLineEdit()
        self.band_max.setPlaceholderText("e.g. 200KB")
        lay.addRow("Minimum size:", self.band_min)
        lay.addRow("Maximum size:", self.band_max)
        return w

    def _page_exact(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.exact_size = QLineEdit()
        self.exact_size.setPlaceholderText("e.g. 1MB")
        self.exact_tol = QLineEdit()
        self.exact_tol.setPlaceholderText("default 1KB")
        lay.addRow("Exact size:", self.exact_size)
        lay.addRow("Tolerance ±:", self.exact_tol)
        return w

    def _page_inflate(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.inflate_size = QLineEdit()
        self.inflate_size.setPlaceholderText("e.g. 900KB")
        lay.addRow("Grow to size:", self.inflate_size)
        hint = QLabel("Lossless: pixels/samples are unchanged; only padding is added.")
        hint.setObjectName("infoLabel")
        hint.setWordWrap(True)
        lay.addRow("", hint)
        return w

    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("3 · Options")
        lay = QFormLayout(box)
        self.pdf_mode = QComboBox()
        self.pdf_mode.addItem("Multimedia (keep text/vectors)", PdfMode.MULTIMEDIA)
        self.pdf_mode.addItem("Rasterize (image-only, smallest)", PdfMode.RASTERIZE)
        self.pdf_mode.setEnabled(False)
        lay.addRow("PDF mode:", self.pdf_mode)

        self.png_alpha = QComboBox()
        self.png_alpha.addItem("Quantize (recommended)", "quantize")
        self.png_alpha.addItem("Channel split", "channel_split")
        lay.addRow("Transparent PNG:", self.png_alpha)

        self.keep_ooxml = QCheckBox("For DOC/PPT, output DOCX/PPTX (safer, precise)")
        self.no_downscale = QCheckBox("Disallow downscaling (resolution / sample rate)")
        self.no_pad = QCheckBox("Disallow padding to reach the minimum size")
        lay.addRow(self.keep_ooxml)
        lay.addRow(self.no_downscale)
        lay.addRow(self.no_pad)
        return box

    def _build_output_group(self) -> QGroupBox:
        box = QGroupBox("4 · Output")
        lay = QHBoxLayout(box)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output path (auto-suggested on selection)")
        browse = QPushButton("Save as…")
        browse.clicked.connect(self._browse_output)
        lay.addWidget(self.output_edit, 1)
        lay.addWidget(browse)
        return box

    def _build_result_group(self) -> QGroupBox:
        box = QGroupBox("Result")
        lay = QVBoxLayout(box)
        self.result_summary = QLabel("Results will appear here.")
        self.result_summary.setObjectName("infoLabel")
        self.result_summary.setWordWrap(True)
        lay.addWidget(self.result_summary)

        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setHorizontalHeaderLabels(["Asset", "Status", "Before", "After"])
        self.asset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.asset_table.verticalHeader().setVisible(False)
        self.asset_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.asset_table.setVisible(False)
        lay.addWidget(self.asset_table)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(120)
        lay.addWidget(self.log)
        return box

    # --- input handling ----------------------------------------------------------

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file")
        if path:
            self._select_file(path)

    def _select_file(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.is_file():
            return
        self._input_path = path
        try:
            self._input_format = detect_format(path)
        except ResizeKitError:
            self._input_format = FileFormat.UNKNOWN
        size = path.stat().st_size
        self.drop.setText(path.name)
        self.input_info.setText(
            f"{format_size(size)} · {self._input_format.value} "
            f"({self._input_format.media_class.value})"
        )
        self.pdf_mode.setEnabled(self._input_format is FileFormat.PDF)
        self._suggest_output()
        self.run_button.setEnabled(self._input_format is not FileFormat.UNKNOWN)

    def _suggest_output(self) -> None:
        if not self._input_path:
            return
        suffix = self._input_path.suffix
        if self.keep_ooxml.isChecked() and self._input_format is FileFormat.DOC:
            suffix = ".docx"
        elif self.keep_ooxml.isChecked() and self._input_format is FileFormat.PPT:
            suffix = ".pptx"
        out = self._input_path.with_name(f"{self._input_path.stem}.rk{suffix}")
        self.output_edit.setText(str(out))

    def _browse_output(self) -> None:
        start = self.output_edit.text() or ""
        path, _ = QFileDialog.getSaveFileName(self, "Save output as", start)
        if path:
            self.output_edit.setText(path)

    def _on_mode_changed(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)

    # --- target / options assembly ----------------------------------------------

    def _build_target(self) -> CompressionTarget:
        mode = self.mode_combo.currentData()
        common = dict(
            allow_downscale=not self.no_downscale.isChecked(),
            allow_pad=not self.no_pad.isChecked(),
        )
        if mode is TargetMode.RATIO:
            return CompressionTarget(
                mode=TargetMode.RATIO, ratio=self.ratio_slider.value() / 100.0, **common
            )
        if mode is TargetMode.SIZE_BAND:
            min_b = parse_size(self.band_min.text()) if self.band_min.text().strip() else None
            max_b = parse_size(self.band_max.text()) if self.band_max.text().strip() else None
            if min_b is None and max_b is None:
                raise ConfigurationError("Enter at least a maximum (or minimum) size.")
            return CompressionTarget(
                mode=TargetMode.SIZE_BAND, min_bytes=min_b, max_bytes=max_b, **common
            )
        if mode is TargetMode.EXACT:
            if not self.exact_size.text().strip():
                raise ConfigurationError("Enter the exact target size.")
            tol = parse_size(self.exact_tol.text()) if self.exact_tol.text().strip() else 1024
            return CompressionTarget(
                mode=TargetMode.EXACT, max_bytes=parse_size(self.exact_size.text()),
                exact_tolerance=tol, **common,
            )
        # INFLATE
        if not self.inflate_size.text().strip():
            raise ConfigurationError("Enter the target size to grow to.")
        return CompressionTarget.inflate_to(parse_size(self.inflate_size.text()), **common)

    def _build_options(self) -> JobOptions:
        return JobOptions(
            pdf_mode=self.pdf_mode.currentData(),
            keep_ooxml=self.keep_ooxml.isChecked(),
            compressor_options=CompressorOptions(
                png_alpha_strategy=self.png_alpha.currentData()
            ),
        )

    # --- run / worker lifecycle --------------------------------------------------

    def _on_run(self) -> None:
        if not self._input_path:
            return
        try:
            target = self._build_target()
        except ResizeKitError as exc:
            QMessageBox.warning(self, "Invalid target", str(exc))
            return
        output = Path(self.output_edit.text().strip() or self._input_path.with_name(
            f"{self._input_path.stem}.rk{self._input_path.suffix}"
        ))
        if output.resolve() == self._input_path.resolve():
            QMessageBox.warning(self, "Invalid output", "Output must differ from the input file.")
            return

        self.log.clear()
        self.asset_table.setRowCount(0)
        self.asset_table.setVisible(False)
        self.result_summary.setText("Working…")
        self._set_busy(True)

        self._thread = QThread()
        self._worker = CompressionWorker(self._input_path, target, output, self._build_options())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            self._append_log("Cancellation requested… (stops after the current step)")
            self.cancel_button.setEnabled(False)

    def _on_progress(self, msg: str) -> None:
        self._append_log(msg)

    def _on_succeeded(self, result: CompressionResult) -> None:
        self._render_result(result)

    def _on_failed(self, message: str) -> None:
        self.result_summary.setText(f"❌ {message}")
        self._append_log(f"FAILED: {message}")

    def _on_cancelled(self) -> None:
        self.result_summary.setText("Cancelled.")
        self._append_log("Cancelled.")

    def _cleanup_thread(self) -> None:
        self._set_busy(False)
        if self._thread:
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _set_busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy and self._input_path is not None)
        self.cancel_button.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(1)

    # --- rendering ---------------------------------------------------------------

    def _render_result(self, r: CompressionResult) -> None:
        status = "✅ landed in band" if r.landed_in_band else "⚠️ outside requested band"
        summary = (
            f"{status}\n"
            f"{format_size(r.original_bytes)} → {format_size(r.final_bytes)}  "
            f"({format_ratio(r.original_bytes, r.final_bytes)} saved)\n"
            f"Saved to: {r.output_path}"
        )
        if r.note:
            summary += f"\nNote: {r.note}"
        self.result_summary.setText(summary)

        if r.children:
            self.asset_table.setVisible(True)
            self.asset_table.setRowCount(len(r.children))
            for row, a in enumerate(r.children):
                self.asset_table.setItem(row, 0, QTableWidgetItem(a.name))
                self.asset_table.setItem(row, 1, QTableWidgetItem(a.status))
                self.asset_table.setItem(row, 2, QTableWidgetItem(format_size(a.original_bytes)))
                self.asset_table.setItem(row, 3, QTableWidgetItem(format_size(a.final_bytes)))

    def _append_log(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def _refresh_tool_status(self) -> None:
        parts = []
        for s in default_registry().statuses():
            mark = "✓" if s.available else "✗"
            parts.append(f"{s.name} {mark}")
        self.tool_status.setText("Tools:  " + "    ".join(parts))
