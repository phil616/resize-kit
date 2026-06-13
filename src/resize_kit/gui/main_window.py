"""resize-kit 主窗口（中文界面）。"""

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
from ..version import (
    __author__,
    __description__,
    __repository__,
    __version_tag__,
)
from .worker import CompressionWorker

_MODE_ORDER = [TargetMode.RATIO, TargetMode.SIZE_BAND, TargetMode.EXACT, TargetMode.INFLATE]
_MODE_LABELS = {
    TargetMode.RATIO: "按比例（压缩到原始大小的一部分）",
    TargetMode.SIZE_BAND: "体积区间（最小 ≤ 体积 ≤ 最大）",
    TargetMode.EXACT: "精确体积（±容差）",
    TargetMode.INFLATE: "增大体积（灌水到目标大小，无损）",
}

# 资源处理状态 -> 中文显示
_ASSET_STATUS_LABELS = {
    "compressed": "已压缩",
    "skipped": "已跳过",
    "failed": "失败",
    "unchanged": "未变更",
}


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"resize-kit {__version_tag__} · 多格式压缩工具")
        self.setMinimumSize(760, 900)
        self._input_path: Optional[Path] = None
        self._input_format: FileFormat = FileFormat.UNKNOWN
        self._thread: Optional[QThread] = None
        self._worker: Optional[CompressionWorker] = None
        self._build_ui()
        self._refresh_tool_status()

    # --- 界面构建 ---------------------------------------------------------------

    def _build_ui(self) -> None:
        # 全部内容放进滚动区域，避免在小屏幕上控件被压缩/裁剪。
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
        subtitle = QLabel(f"{__version_tag__} · {__description__}")
        subtitle.setObjectName("subtitle")
        root.addWidget(subtitle)
        self.tool_status = QLabel()
        self.tool_status.setObjectName("toolStatus")
        root.addWidget(self.tool_status)

        root.addWidget(self._build_input_group())
        root.addWidget(self._build_target_group())
        root.addWidget(self._build_options_group())
        root.addWidget(self._build_output_group())
        # 切换 DOC/PPT 退路选项时，重新建议输出扩展名。
        self.keep_ooxml.toggled.connect(self._suggest_output)

        self.run_button = QPushButton("开始压缩")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._on_run)
        self.run_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
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
        root.addWidget(self._build_footer())

    def _build_input_group(self) -> QGroupBox:
        box = QGroupBox("1 · 输入文件")
        layout = QVBoxLayout(box)
        from .widgets import DropLabel

        self.drop = DropLabel("将文件拖入此处，或点击“浏览”")
        self.drop.fileDropped.connect(self._select_file)
        layout.addWidget(self.drop)

        row = QHBoxLayout()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_input)
        self.input_info = QLabel("尚未选择文件。")
        self.input_info.setObjectName("infoLabel")
        row.addWidget(browse)
        row.addWidget(self.input_info, 1)
        layout.addLayout(row)
        return box

    def _build_target_group(self) -> QGroupBox:
        box = QGroupBox("2 · 目标")
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
        # 各页面共用同一区域，预留最高页面的高度，避免切换时裁剪控件。
        self.mode_stack.setMinimumHeight(96)
        layout.addWidget(self.mode_stack)
        return box

    def _page_ratio(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.ratio_slider = QSlider(Qt.Horizontal)
        self.ratio_slider.setRange(5, 100)
        self.ratio_slider.setValue(50)
        self.ratio_value = QLabel("占原始大小的 50%")
        self.ratio_slider.valueChanged.connect(
            lambda v: self.ratio_value.setText(f"占原始大小的 {v}%")
        )
        lay.addRow("压缩到：", self.ratio_slider)
        lay.addRow("", self.ratio_value)
        return w

    def _page_band(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.band_min = QLineEdit()
        self.band_min.setPlaceholderText("可选，例如 150KB")
        self.band_max = QLineEdit()
        self.band_max.setPlaceholderText("例如 200KB")
        lay.addRow("最小体积：", self.band_min)
        lay.addRow("最大体积：", self.band_max)
        return w

    def _page_exact(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.exact_size = QLineEdit()
        self.exact_size.setPlaceholderText("例如 1MB")
        self.exact_tol = QLineEdit()
        self.exact_tol.setPlaceholderText("默认 1KB")
        lay.addRow("精确体积：", self.exact_size)
        lay.addRow("容差 ±：", self.exact_tol)
        return w

    def _page_inflate(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        self.inflate_size = QLineEdit()
        self.inflate_size.setPlaceholderText("例如 900KB")
        lay.addRow("增大到：", self.inflate_size)
        hint = QLabel("无损：像素 / 采样数据保持不变，仅添加填充字节。")
        hint.setObjectName("infoLabel")
        hint.setWordWrap(True)
        lay.addRow("", hint)
        return w

    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("3 · 选项")
        lay = QFormLayout(box)
        self.pdf_mode = QComboBox()
        self.pdf_mode.addItem("多媒体（保留文字 / 矢量）", PdfMode.MULTIMEDIA)
        self.pdf_mode.addItem("栅格化（仅图像，体积最小）", PdfMode.RASTERIZE)
        self.pdf_mode.setEnabled(False)
        lay.addRow("PDF 模式：", self.pdf_mode)

        self.png_alpha = QComboBox()
        self.png_alpha.addItem("调色板量化（推荐）", "quantize")
        self.png_alpha.addItem("通道分离", "channel_split")
        lay.addRow("透明 PNG：", self.png_alpha)

        self.keep_ooxml = QCheckBox("DOC/PPT 输出为 DOCX/PPTX（更稳妥、可精确控制）")
        self.no_downscale = QCheckBox("禁止降分辨率 / 降采样率")
        self.no_pad = QCheckBox("禁止通过填充达到最小体积")
        lay.addRow(self.keep_ooxml)
        lay.addRow(self.no_downscale)
        lay.addRow(self.no_pad)
        return box

    def _build_output_group(self) -> QGroupBox:
        box = QGroupBox("4 · 输出")
        lay = QHBoxLayout(box)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("输出路径（选择文件后自动建议）")
        browse = QPushButton("另存为…")
        browse.clicked.connect(self._browse_output)
        lay.addWidget(self.output_edit, 1)
        lay.addWidget(browse)
        return box

    def _build_result_group(self) -> QGroupBox:
        box = QGroupBox("结果")
        lay = QVBoxLayout(box)
        self.result_summary = QLabel("处理结果将显示在这里。")
        self.result_summary.setObjectName("infoLabel")
        self.result_summary.setWordWrap(True)
        lay.addWidget(self.result_summary)

        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setHorizontalHeaderLabels(["资源", "状态", "压缩前", "压缩后"])
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

    def _build_footer(self) -> QLabel:
        # 版本号 / 作者 / 仓库信息（仓库为可点击链接）。
        footer = QLabel(
            f"resize-kit {__version_tag__} · 作者 {__author__} · "
            f'<a href="{__repository__}">{__repository__}</a>'
        )
        footer.setObjectName("footer")
        footer.setTextFormat(Qt.RichText)
        footer.setOpenExternalLinks(True)
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        return footer

    # --- 输入处理 ---------------------------------------------------------------

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
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
            f"（{self._input_format.media_class.value}）"
        )
        self.pdf_mode.setEnabled(self._input_format is FileFormat.PDF)
        self._suggest_output()
        if self._input_format is FileFormat.UNKNOWN:
            self.input_info.setText(self.input_info.text() + " · 不支持的格式")
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
        path, _ = QFileDialog.getSaveFileName(self, "另存为", start)
        if path:
            self.output_edit.setText(path)

    def _on_mode_changed(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)

    # --- 目标 / 选项组装 --------------------------------------------------------

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
                raise ConfigurationError("请至少填写最大体积（或最小体积）。")
            return CompressionTarget(
                mode=TargetMode.SIZE_BAND, min_bytes=min_b, max_bytes=max_b, **common
            )
        if mode is TargetMode.EXACT:
            if not self.exact_size.text().strip():
                raise ConfigurationError("请填写精确目标体积。")
            tol = parse_size(self.exact_tol.text()) if self.exact_tol.text().strip() else 1024
            return CompressionTarget(
                mode=TargetMode.EXACT, max_bytes=parse_size(self.exact_size.text()),
                exact_tolerance=tol, **common,
            )
        # INFLATE 增大模式
        if not self.inflate_size.text().strip():
            raise ConfigurationError("请填写要增大到的目标体积。")
        return CompressionTarget.inflate_to(parse_size(self.inflate_size.text()), **common)

    def _build_options(self) -> JobOptions:
        return JobOptions(
            pdf_mode=self.pdf_mode.currentData(),
            keep_ooxml=self.keep_ooxml.isChecked(),
            compressor_options=CompressorOptions(
                png_alpha_strategy=self.png_alpha.currentData()
            ),
        )

    # --- 运行 / 工作线程生命周期 ------------------------------------------------

    def _on_run(self) -> None:
        if not self._input_path:
            return
        try:
            target = self._build_target()
        except ResizeKitError as exc:
            QMessageBox.warning(self, "目标无效", str(exc))
            return
        output = Path(self.output_edit.text().strip() or self._input_path.with_name(
            f"{self._input_path.stem}.rk{self._input_path.suffix}"
        ))
        if output.resolve() == self._input_path.resolve():
            QMessageBox.warning(self, "输出无效", "输出文件必须与输入文件不同。")
            return

        self.log.clear()
        self.asset_table.setRowCount(0)
        self.asset_table.setVisible(False)
        self.result_summary.setText("处理中…")
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
            self._append_log("已请求取消…（将在当前步骤完成后停止）")
            self.cancel_button.setEnabled(False)

    def _on_progress(self, msg: str) -> None:
        self._append_log(msg)

    def _on_succeeded(self, result: CompressionResult) -> None:
        self._render_result(result)

    def _on_failed(self, message: str) -> None:
        self.result_summary.setText(f"❌ {message}")
        self._append_log(f"失败：{message}")

    def _on_cancelled(self) -> None:
        self.result_summary.setText("已取消。")
        self._append_log("已取消。")

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

    # --- 结果渲染 ---------------------------------------------------------------

    def _render_result(self, r: CompressionResult) -> None:
        status = "✅ 已落入目标区间" if r.landed_in_band else "⚠️ 超出目标区间"
        summary = (
            f"{status}\n"
            f"{format_size(r.original_bytes)} → {format_size(r.final_bytes)}  "
            f"（节省 {format_ratio(r.original_bytes, r.final_bytes)}）\n"
            f"已保存到：{r.output_path}"
        )
        if r.note:
            summary += f"\n说明：{r.note}"
        self.result_summary.setText(summary)

        if r.children:
            self.asset_table.setVisible(True)
            self.asset_table.setRowCount(len(r.children))
            for row, a in enumerate(r.children):
                status_text = _ASSET_STATUS_LABELS.get(a.status, a.status)
                self.asset_table.setItem(row, 0, QTableWidgetItem(a.name))
                self.asset_table.setItem(row, 1, QTableWidgetItem(status_text))
                self.asset_table.setItem(row, 2, QTableWidgetItem(format_size(a.original_bytes)))
                self.asset_table.setItem(row, 3, QTableWidgetItem(format_size(a.final_bytes)))

    def _append_log(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def _refresh_tool_status(self) -> None:
        parts = []
        for s in default_registry().statuses():
            mark = "✓" if s.available else "✗"
            parts.append(f"{s.name} {mark}")
        self.tool_status.setText("外部工具：  " + "    ".join(parts))
