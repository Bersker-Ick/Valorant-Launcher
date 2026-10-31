"""诊断面板：目标窗口信息、SendInput 事件、UIA 探测、记事本自检、调试开关。"""

from __future__ import annotations

import html
import logging
import time
from typing import Callable

from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, save_config
from ..core import uia, winapi
from ..core.input import InputDiagnostics
from ..core.models import WindowInfo
from ..core.selftest import SelfTestResult, run_notepad_selftest
from ..paths import logs_dir
from .widgets import Badge, Card, HintLabel, MutedLabel, SectionTitle, ValueLabel, button, primary_button

LOGGER = logging.getLogger("login_assistant.ui.diagnostics")


class SelfTestWorker(QThread):
    result = Signal(object)

    def __init__(self, *, block_input: bool, delay_min: int, delay_max: int, diagnostics: InputDiagnostics) -> None:
        super().__init__()
        self.block_input = block_input
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.diagnostics = diagnostics

    def run(self) -> None:
        try:
            result = run_notepad_selftest(
                block_input=self.block_input,
                delay_min_ms=self.delay_min,
                delay_max_ms=self.delay_max,
                diagnostics=self.diagnostics,
            )
        except Exception as exc:
            result = SelfTestResult(
                ok=False,
                headline="自检线程异常",
                detail=f"{type(exc).__name__}: {exc}",
            )
        self.result.emit(result)


class ProbeWorker(QThread):
    result = Signal(object)

    def __init__(self, hwnd: int) -> None:
        super().__init__()
        self.hwnd = hwnd

    def run(self) -> None:
        try:
            data = uia.probe(self.hwnd)
        except Exception as exc:
            data = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.result.emit(data)


class PasswordProbeWorker(QThread):
    """只读探测密码框的 UIA ValuePattern 能力；不读取、不写入值。"""

    result = Signal(object)

    def __init__(self, point: tuple[int, int]) -> None:
        super().__init__()
        self.point = point

    def run(self) -> None:
        try:
            data = uia.probe_password_value(self.point)
        except Exception as exc:
            data = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.result.emit(data)


class DiagnosticsPanel(QWidget):
    def __init__(
        self,
        config: AppConfig,
        diagnostics: InputDiagnostics,
        config_saved: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.diagnostics = diagnostics
        self.config_saved = config_saved
        self.target_refresh_cb: Callable[[], None] | None = None
        self._target_info: WindowInfo | None = None
        self._worker: SelfTestWorker | None = None
        self._probe_worker: ProbeWorker | None = None
        self._password_probe_worker: PasswordProbeWorker | None = None
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self._refresh_events)
        self._timer.start()
        self.refresh_target()

    # -- layout ------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        inner.setObjectName("Root")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._build_target_card())
        layout.addWidget(self._build_selftest_card())
        layout.addWidget(self._build_events_card(), 1)
        layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_target_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(SectionTitle("目标窗口"))
        header.addStretch(1)
        self.target_badge = Badge("未找到", "warn")
        header.addWidget(self.target_badge)
        self.refresh_button = button("刷新")
        self.refresh_button.clicked.connect(self.refresh_target)
        header.addWidget(self.refresh_button)
        self.probe_button = primary_button("UIA 探测")
        self.probe_button.clicked.connect(self._run_probe)
        self.probe_button.setEnabled(False)
        header.addWidget(self.probe_button)
        self.password_probe_button = button("密码框 UIA 写入探测")
        self.password_probe_button.clicked.connect(self._run_password_probe)
        self.password_probe_button.setEnabled(False)
        header.addWidget(self.password_probe_button)
        card.add_layout(header)

        hint = HintLabel(
            "目标由“标题正则 + 类名正则”或手动选窗确定；这里显示目标句柄、类名、"
            "PID、进程路径与完整性级别。UIA 探测只读取可访问性结构，不读取任何输入值。"
            "“密码框 UIA 写入探测”只检查 ValuePattern 是否可用/是否只读，不会写入。"
        )
        card.add(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        self.v_hwnd = ValueLabel("—")
        self.v_title = ValueLabel("—")
        self.v_class = ValueLabel("—")
        self.v_pid = ValueLabel("—")
        self.v_exe = ValueLabel("—")
        self.v_integrity = ValueLabel("—")
        self.v_source = ValueLabel("—")
        self.v_candidates = ValueLabel("—")
        self.v_foreground_status = ValueLabel("—")
        self.v_foreground = ValueLabel("—")
        form.addRow("窗口句柄", self.v_hwnd)
        form.addRow("窗口标题", self.v_title)
        form.addRow("窗口类名", self.v_class)
        form.addRow("进程 PID", self.v_pid)
        form.addRow("进程路径", self.v_exe)
        form.addRow("完整性级别", self.v_integrity)
        form.addRow("匹配来源", self.v_source)
        form.addRow("候选窗口", self.v_candidates)
        form.addRow("目标在前台", self.v_foreground_status)
        form.addRow("当前前台", self.v_foreground)
        card.add_layout(form)
        return card

    def _build_events_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(SectionTitle("SendInput 诊断"))
        header.addStretch(1)
        self.events_summary = MutedLabel("尚无事件")
        header.addWidget(self.events_summary)
        refresh = button("刷新")
        refresh.clicked.connect(self._refresh_events)
        clear = button("清空")
        clear.clicked.connect(self._clear_events)
        header.addWidget(refresh)
        header.addWidget(clear)
        card.add_layout(header)

        hint = HintLabel(
            "每条键盘/鼠标事件单独调用 SendInput，并记录返回值与 GetLastError；"
            "不记录字符内容，避免密码进入诊断信息。"
        )
        card.add(hint)

        self.events_table = QTableWidget(0, 8)
        self.events_table.setHorizontalHeaderLabels(
            ["#", "动作", "VK", "扫描码", "Flags", "返回", "GetLastError", "时间"]
        )
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.events_table.setAlternatingRowColors(True)
        self.events_table.setMinimumHeight(230)
        header_view = self.events_table.horizontalHeader()
        header_view.setStretchLastSection(True)
        for index, width in enumerate((50, 90, 55, 70, 80, 55, 100)):
            self.events_table.setColumnWidth(index, width)
        card.add(self.events_table)
        return card

    def _build_selftest_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(SectionTitle("输入层自检"))
        header.addStretch(1)
        self.selftest_button = primary_button("记事本自检")
        self.selftest_button.clicked.connect(self._run_selftest)
        header.addWidget(self.selftest_button)
        card.add_layout(header)

        desc = MutedLabel(
            "点击后会打开一个新的记事本，输入 Abc123!@# 并读回比对。"
            "该操作只读取本工具自己启动的记事本，不会读取目标登录器的密码框。"
        )
        card.add(desc)

        row = QHBoxLayout()
        self.block_input_check = QCheckBox("自检期间 BlockInput")
        self.block_input_check.setChecked(self.config.input.block_input)
        self.block_input_check.toggled.connect(self._toggle_block_input)
        row.addWidget(self.block_input_check)
        row.addSpacing(18)
        self.input_only_check = QCheckBox("仅输入不点击（调试）")
        self.input_only_check.setChecked(self.config.input.input_only_no_click)
        self.input_only_check.toggled.connect(self._toggle_input_only)
        row.addWidget(self.input_only_check)
        row.addStretch(1)
        open_logs = button("打开日志目录")
        open_logs.clicked.connect(self._open_logs)
        row.addWidget(open_logs)
        card.add_layout(row)

        self.selftest_status = HintLabel("尚未自检")
        card.add(self.selftest_status)
        return card

    # -- target ------------------------------------------------------------
    def set_target_refresh_callback(self, callback: Callable[[], None]) -> None:
        self.target_refresh_cb = callback

    def refresh_target(self) -> None:
        if self.target_refresh_cb is not None:
            self.target_refresh_cb()
            return
        try:
            info = winapi.get_foreground_info(include_integrity=True)
        except Exception:
            info = None
        self.set_target(info, "当前前台", 1 if info else 0)

    def set_target(self, info: WindowInfo | None, source: str, candidates: int) -> None:
        self._target_info = info
        foreground = winapi.get_foreground_info(include_integrity=False)
        self.v_foreground.setText(
            f"{foreground.title} (0x{foreground.hwnd:X}, PID {foreground.pid})"
            if foreground
            else "无"
        )
        if info is None:
            self.target_badge.set_state("未找到", "warn")
            for label in (
                self.v_hwnd,
                self.v_title,
                self.v_class,
                self.v_pid,
                self.v_exe,
                self.v_integrity,
                self.v_source,
                self.v_candidates,
                self.v_foreground_status,
            ):
                label.setText("—")
            self.v_source.setText(source or "—")
            self.probe_button.setEnabled(False)
            self.password_probe_button.setEnabled(False)
            return
        self.target_badge.set_state("已找到", "ok")
        self.v_hwnd.setText(info.hwnd_hex)
        self.v_title.setText(info.title or "（空）")
        self.v_class.setText(info.class_name or "（空）")
        self.v_pid.setText(str(info.pid))
        self.v_exe.setText(info.exe or "（无法获取）")
        self.v_integrity.setText(info.integrity_text)
        self.v_source.setText(source)
        self.v_candidates.setText(str(candidates))
        self.v_foreground_status.setText("是" if winapi.get_foreground_window() == info.hwnd else "否")
        self.v_integrity.setStyleSheet("")
        if info.integrity and info.integrity.rid is not None:
            own = winapi.self_integrity()
            if own.rid is not None and info.integrity.rid > own.rid:
                self.v_integrity.setStyleSheet("color:#b91c1c;")
        self.probe_button.setEnabled(True)
        self.password_probe_button.setEnabled(True)

    def _run_probe(self) -> None:
        if self._target_info is None:
            QMessageBox.information(self, "UIA 探测", "请先找到目标窗口。")
            return
        if self.is_busy():
            return
        self.probe_button.setEnabled(False)
        self.probe_button.setText("探测中…")
        self._probe_worker = ProbeWorker(self._target_info.hwnd)
        self._probe_worker.result.connect(self._on_probe_result)
        self._probe_worker.finished.connect(self._on_probe_finished)
        self._probe_worker.start()

    def _on_probe_finished(self) -> None:
        self.probe_button.setEnabled(self._target_info is not None)
        self.probe_button.setText("UIA 探测")
        self.password_probe_button.setEnabled(self._target_info is not None)

    def _run_password_probe(self) -> None:
        if self._target_info is None:
            QMessageBox.information(self, "密码框 UIA 探测", "请先找到目标窗口。")
            return
        if self.is_busy():
            return
        cal = self.config.calibration
        if not cal.is_complete or cal.password is None:
            QMessageBox.information(
                self,
                "密码框 UIA 探测",
                "还没有完整的校准坐标。请先在主界面完成账号/密码/登录按钮校准。",
            )
            return
        origin_x, origin_y, width, height = winapi.get_client_rect_screen(self._target_info.hwnd)
        point_cfg = cal.password
        if abs(point_cfg.client_w - width) > 2 or abs(point_cfg.client_h - height) > 2:
            QMessageBox.warning(
                self,
                "窗口尺寸已变化",
                f"校准时的客户区为 {point_cfg.client_w}x{point_cfg.client_h}，"
                f"当前为 {width}x{height}。\n请重新校准后再探测密码框。",
            )
            return
        point = (origin_x + point_cfg.x, origin_y + point_cfg.y)
        self.password_probe_button.setEnabled(False)
        self.password_probe_button.setText("探测中…")
        self._password_probe_worker = PasswordProbeWorker(point)
        self._password_probe_worker.result.connect(self._on_password_probe_result)
        self._password_probe_worker.finished.connect(self._on_password_probe_finished)
        self._password_probe_worker.start()

    def _on_password_probe_finished(self) -> None:
        self.password_probe_button.setEnabled(self._target_info is not None)
        self.password_probe_button.setText("密码框 UIA 写入探测")

    def _on_password_probe_result(self, data: object) -> None:
        if not isinstance(data, dict) or not data.get("ok"):
            error = data.get("error") if isinstance(data, dict) else "未知错误"
            QMessageBox.warning(self, "密码框 UIA 探测失败", str(error))
            return
        info = data.get("info")
        state = data.get("value_pattern")
        lines: list[str] = []
        if info is not None:
            lines.append(f"控件类型：{info.control_type}")
            lines.append(f"类名：{info.class_name!r}")
            lines.append(f"名称：{info.name!r}")
            lines.append(f"PID：{info.process_id}")
            lines.append(f"原生 hwnd：0x{info.native_window_handle:X}" if info.native_window_handle else "原生 hwnd：—")
            lines.append(f"UIA IsPassword：{info.is_password}")
            lines.append(f"启用：{info.is_enabled}")
        if state is not None:
            lines.append(f"ValuePattern：{state.summary}")
        if state is not None and state.available and state.read_only is False:
            conclusion = "该密码框支持 UIA 写入。可在“设置 → 输入”勾选“密码用 UIA ValuePattern 写入（实验）”后试登录。"
        elif state is not None and state.available and state.read_only is True:
            conclusion = "该密码框的 ValuePattern 是只读的，UIA 写入不可用；只能手动输入。"
        else:
            conclusion = "该密码框没有可用的 ValuePattern；UIA 写入不可用。"
        lines.append("")
        lines.append(conclusion)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("密码框 UIA 写入探测")
        box.setText("只读探测完成；未读取、未写入任何密码值。")
        box.setDetailedText("\n".join(lines))
        box.exec()

    def _on_probe_result(self, data: object) -> None:
        if not isinstance(data, dict) or not data.get("ok"):
            error = data.get("error") if isinstance(data, dict) else "未知错误"
            QMessageBox.warning(self, "UIA 探测失败", str(error))
            return
        edits = data.get("edits", [])
        buttons = data.get("buttons", [])
        texts = data.get("texts", [])
        lines: list[str] = []
        lines.append(f"Edit 控件：{len(edits)} 个")
        for info in edits[:8]:
            rect = info.rect
            lines.append(
                f"  · name={info.name!r} id={info.automation_id!r} "
                f"password={info.is_password} rect={rect} focus={info.has_keyboard_focus}"
            )
        lines.append(f"Button 控件：{len(buttons)} 个")
        for info in buttons[:10]:
            lines.append(f"  · {info.name!r} rect={info.rect} enabled={info.is_enabled}")
        lines.append(f"Text 控件：{len(texts)} 个")
        for text in texts[:10]:
            lines.append(f"  · {str(text)[:80]!r}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("UIA 探测")
        box.setText("已读取目标窗口的 UI Automation 结构（只读，不读取输入值）。")
        box.setDetailedText("\n".join(lines))
        box.exec()

    # -- events ------------------------------------------------------------
    def _refresh_events(self) -> None:
        if not self.isVisible():
            return
        events = self.diagnostics.snapshot()[-120:]
        self.events_table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = [
                str(event.seq),
                event.kind,
                f"0x{event.vk:02X}",
                f"0x{event.scan:02X}",
                f"0x{event.flags:04X}",
                str(event.ret),
                str(event.error),
                time_text(event.at),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if event.ret != 1:
                    item.setForeground(Qt.red)
                self.events_table.setItem(row, column, item)
        self.events_summary.setText(
            f"共 {self.diagnostics.total_events} 次，失败 {self.diagnostics.failures} 次"
        )
        if events:
            self.events_table.scrollToBottom()

    def _clear_events(self) -> None:
        self.diagnostics.clear()
        self._refresh_events()

    # -- self test ---------------------------------------------------------
    def _run_selftest(self) -> None:
        if self.is_busy():
            return
        self.selftest_button.setEnabled(False)
        self.selftest_status.setText("正在启动记事本并输入测试串…")
        self._worker = SelfTestWorker(
            block_input=self.config.input.block_input,
            delay_min=self.config.input.delay_min_ms,
            delay_max=self.config.input.delay_max_ms,
            diagnostics=self.diagnostics,
        )
        self._worker.result.connect(self._on_selftest_done)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        self.selftest_button.setEnabled(True)
        self._refresh_events()

    def _on_selftest_done(self, result: SelfTestResult) -> None:
        self.selftest_status.setText(
            f"{result.headline}；事件 {result.events_total} 次，失败 {result.events_failed} 次"
        )
        LOGGER.info(
            "记事本自检：%s（事件 %d，失败 %d）",
            result.headline,
            result.events_total,
            result.events_failed,
        )
        icon = QMessageBox.Information if result.ok else QMessageBox.Warning
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle("记事本自检")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<b>{html.escape(result.headline)}</b><br>{html.escape(result.detail)}"
            f"<br><br>期望：<code>{html.escape(result.expected)}</code>"
            f"<br>实际：<code>{html.escape(result.actual or '（未读取）')}</code>"
        )
        box.setDetailedText("\n".join(result.steps))
        box.exec()

    # -- toggles -----------------------------------------------------------
    def _toggle_block_input(self, checked: bool) -> None:
        if checked and not self.config.input.block_input:
            answer = QMessageBox.question(
                self,
                "启用 BlockInput？",
                "自检/登录期间物理键盘鼠标会被暂时屏蔽。\n"
                "程序会用 try/finally 恢复，工作线程退出时 Windows 也会自动解除。\n\n"
                "确认启用？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.block_input_check.blockSignals(True)
                self.block_input_check.setChecked(False)
                self.block_input_check.blockSignals(False)
                return
        self.config.input.block_input = checked
        self._save_config()
        LOGGER.warning("BlockInput 设置为 %s", checked)

    def _toggle_input_only(self, checked: bool) -> None:
        self.config.input.input_only_no_click = checked
        self._save_config()
        LOGGER.info("仅输入不点击（调试）设置为 %s", checked)

    def _save_config(self) -> None:
        try:
            save_config(self.config)
            if self.config_saved:
                self.config_saved()
        except Exception as exc:
            LOGGER.error("保存配置失败：%s", type(exc).__name__)

    def _open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))

    # -- shutdown ----------------------------------------------------------
    def is_busy(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._worker, self._probe_worker)
        )

    def shutdown(self) -> None:
        for worker in (self._worker, self._probe_worker):
            if worker is not None and worker.isRunning():
                worker.wait(15000)


def time_text(monotonic: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(time.time() - (time.monotonic() - monotonic)))
