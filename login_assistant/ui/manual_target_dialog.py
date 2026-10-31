"""手动选择目标窗口（正则匹配不到时的兜底）。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import winapi
from ..core.models import WindowInfo
from .widgets import HintLabel, MutedLabel, button


class ManualTargetDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择目标窗口")
        self.setModal(True)
        self.resize(860, 480)
        self._windows: list[WindowInfo] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        root.addWidget(
            MutedLabel(
                "仅列出当前可见的顶层窗口（已排除本工具自身）。"
                "选择后会把“标题 + 类名 + 进程路径”保存为手动目标签名；"
                "窗口关闭后签名失效，可随时重新选择。"
            )
        )

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题 / 类名 / 进程…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        row.addWidget(self.search, 1)
        refresh = button("刷新")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        root.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["标题", "类名", "PID", "进程", "完整性"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 170)
        self.table.setColumnWidth(4, 120)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.table, 1)

        self.hint = HintLabel("请选择一个窗口。")
        root.addWidget(self.hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("选择")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "primary")
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        root.addWidget(buttons)
        self._update_buttons()

    def refresh(self) -> None:
        try:
            windows = winapi.enum_top_windows(exclude_pid=os.getpid(), include_tool_windows=False)
        except Exception as exc:
            self.hint.setText(f"枚举窗口失败：{type(exc).__name__}")
            windows = []
        with_integrity: list[WindowInfo] = []
        for info in windows:
            try:
                enriched = winapi.get_window_info(info.hwnd, include_integrity=True)
            except Exception:
                enriched = None
            with_integrity.append(enriched or info)
        self._windows = with_integrity
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        rows = []
        for info in self._windows:
            haystack = f"{info.title} {info.class_name} {info.exe}".casefold()
            if needle and needle not in haystack:
                continue
            rows.append(info)
        self.table.setRowCount(len(rows))
        for row, info in enumerate(rows):
            values = [
                info.title,
                info.class_name,
                str(info.pid),
                info.exe or "（无法获取）",
                info.integrity_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, info.hwnd)
                self.table.setItem(row, column, item)
        self.hint.setText(
            f"共 {len(self._windows)} 个可见窗口，当前显示 {len(rows)} 个。"
            if self._windows
            else "没有可选的可见窗口。请先启动登录器。"
        )
        if rows:
            self.table.selectRow(0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.ok_button.setEnabled(self._selected_window() is not None)

    def _selected_window(self) -> WindowInfo | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        hwnd = item.data(Qt.UserRole)
        if not hwnd:
            return None
        for info in self._windows:
            if info.hwnd == int(hwnd):
                return info
        return None

    def _accept_selected(self) -> None:
        if self._selected_window() is None:
            return
        self.accept()

    def selected_window(self) -> WindowInfo | None:
        return self._selected_window()
