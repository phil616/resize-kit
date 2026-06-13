"""Background compression worker.

Compression can take many seconds (ffmpeg, LibreOffice). Running it on the Qt
main thread would freeze the UI, so a :class:`CompressionWorker` QObject does the
work on a dedicated :class:`~PyQt5.QtCore.QThread` and reports back via signals.

Cancellation is cooperative: the progress callback raises :class:`JobCancelled`
when a cancel has been requested, so the job aborts cleanly between encode steps
(never mid-write of an external process).
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from ..core.dispatcher import Dispatcher, JobOptions
from ..core.exceptions import ResizeKitError
from ..core.models import CompressionResult, CompressionTarget


class JobCancelled(Exception):
    """Raised inside the progress callback to abort a job cooperatively."""


class CompressionWorker(QObject):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)  # CompressionResult
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    finished = pyqtSignal()  # always emitted last (success or failure)

    def __init__(
        self,
        input_path: Path,
        target: CompressionTarget,
        output_path: Path,
        options: JobOptions,
    ) -> None:
        super().__init__()
        self._input = input_path
        self._target = target
        self._output = output_path
        self._options = options
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        def on_progress(msg: str) -> None:
            if self._cancel_requested:
                raise JobCancelled()
            self.progress.emit(msg)

        try:
            dispatcher = Dispatcher(options=self._options)
            self.progress.emit(f"Starting: {self._input.name}")
            result: CompressionResult = dispatcher.compress(
                self._input, self._target, self._output, on_progress=on_progress
            )
            self.succeeded.emit(result)
        except JobCancelled:
            self.cancelled.emit()
        except ResizeKitError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors to the UI
            self.failed.emit(f"Unexpected error: {exc}")
        finally:
            self.finished.emit()
