"""把 logging 输出接到 GUI 日志面板（线程安全队列 + QTimer 拉取）。"""

from __future__ import annotations

import logging
import threading
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit

from ..security.redact import RedactingFormatter


class QueueLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 3000) -> None:
        super().__init__()
        self._queue: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover
            message = record.getMessage()
        with self._lock:
            self._queue.append(message)

    def drain(self) -> list[str]:
        with self._lock:
            if not self._queue:
                return []
            items = list(self._queue)
            self._queue.clear()
            return items


class LogPanel(QPlainTextEdit):
    def __init__(self, handler: QueueLogHandler, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(3000)
        self.setPlaceholderText("运行日志会显示在这里（已脱敏）")
        self._handler = handler
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def _drain(self) -> None:
        items = self._handler.drain()
        if not items:
            return
        for item in items:
            self.appendPlainText(item)
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
