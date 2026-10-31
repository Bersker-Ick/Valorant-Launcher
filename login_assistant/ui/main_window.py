"""主窗口：账号管理 + 目标窗口 + 登录自动化 + 诊断。"""

from __future__ import annotations

import base64
import html
import logging
import os
import threading

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import AppConfig, save_config
from ..core import winapi
from ..core.automation import AutomationOptions, AutomationReport, AutomationRequest
from ..core.input import InputDiagnostics
from ..core.keymap import describe_unsupported, first_unsupported_byte
from ..core.models import AccountRecord, ManualTarget, WindowInfo
from ..core.store import AccountStore
from ..core.windowmatch import (
    WindowMatchError,
    WindowMatcher,
    resolve_target,
)
from ..paths import app_home
from .account_dialog import AccountDialog
from .calibration import run_calibration
from .diagnostics import DiagnosticsPanel
from .login_worker import LoginWorker
from .logpanel import LogPanel, QueueLogHandler
from .manual_target_dialog import ManualTargetDialog
from .settings_dialog import SettingsDialog
from .widgets import (
    Badge,
    BigValueLabel,
    Card,
    HintLabel,
    MutedLabel,
    SectionTitle,
    button,
    danger_button,
    ghost_button,
    primary_button,
)

LOGGER = logging.getLogger("login_assistant.ui.main")


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        store: AccountStore,
        config_warnings: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.store = store
        self.config_warnings = list(config_warnings or [])
        self.diagnostics = InputDiagnostics()
        self._current_id: str | None = None
        self._visible_records: list[AccountRecord] = []
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(600)
        self._config_timer.timeout.connect(self._save_config_now)

        self._target_info: WindowInfo | None = None
        self._target_source = "none"
        self._target_candidates = 0
        self._target_blocked = False
        self._last_target_key: tuple[int, str] | None = None
        self._matcher: WindowMatcher | None = None
        self._matcher_error: str | None = None
        self._busy = False
        self._calibrating = False
        self._login_worker: LoginWorker | None = None
        self._cancel_event: threading.Event | None = None

        try:
            self._matcher = WindowMatcher(self.config.window_match)
        except WindowMatchError as exc:
            self._matcher_error = f"窗口匹配正则无效：{exc}"
            self.config_warnings.append(self._matcher_error)

        self.log_handler = QueueLogHandler()
        app_logger = logging.getLogger("login_assistant")
        app_logger.addHandler(self.log_handler)
        if app_logger.level == logging.NOTSET:
            app_logger.setLevel(logging.INFO)

        self.setWindowTitle("登录助手")
        self.setMinimumSize(1020, 720)
        self.resize(1180, 820)
        self._build_ui()
        self._restore_geometry()
        self.refresh_accounts()
        self.refresh_target()
        self._target_timer = QTimer(self)
        self._target_timer.setInterval(2500)
        self._target_timer.timeout.connect(self.refresh_target)
        self._target_timer.start()

        self._load_warning_timer = QTimer(self)
        self._load_warning_timer.setSingleShot(True)
        self._load_warning_timer.timeout.connect(self._show_load_warnings)
        self._load_warning_timer.start(300)
        LOGGER.info("主界面已就绪；账号文件：%s", self.store.path)
        self.statusBar().showMessage("就绪", 4000)

    # -- construction ------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_accounts_tab(), "账号")
        self.diagnostics_panel = DiagnosticsPanel(
            self.config,
            self.diagnostics,
            config_saved=self._on_config_saved_externally,
        )
        self.diagnostics_panel.set_target_refresh_callback(self.refresh_target)
        self.tabs.addTab(self.diagnostics_panel, "诊断")
        layout.addWidget(self.tabs, 1)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.setStatusBar(status)
        self.path_label = QLabel(f"数据目录：{app_home()}")
        self.path_label.setObjectName("Muted")
        self.path_label.setToolTip(str(app_home()))
        status.addPermanentWidget(self.path_label)
        status.addPermanentWidget(QLabel(f"v{__version__}"))

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("登录助手")
        title.setObjectName("AppTitle")
        subtitle = QLabel("本地凭据 · Windows DPAPI 加密 · 不联网 · 不注入")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        row.addLayout(titles)
        row.addStretch(1)
        self.settings_button = button("设置")
        self.settings_button.clicked.connect(self._open_settings)
        row.addWidget(self.settings_button)
        open_data = button("数据目录")
        open_data.clicked.connect(self._open_data_dir)
        row.addWidget(open_data)
        return row

    def _build_accounts_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Root")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_account_card())
        splitter.addWidget(self._build_right_column())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([660, 440])
        layout.addWidget(splitter)
        return page

    def _build_account_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(SectionTitle("账号"))
        self.count_label = MutedLabel("0 条")
        header.addWidget(self.count_label)
        header.addStretch(1)
        self.add_button = primary_button("添加")
        self.add_button.clicked.connect(self._add_account)
        header.addWidget(self.add_button)
        card.add_layout(header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索备注名或账号…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self.refresh_accounts())
        card.add(self.search_edit)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["备注名", "账号", "密码"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(2, 110)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._edit_account())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        card.add(self.table, 1)

        self.empty_hint = HintLabel("还没有账号。点击“添加”保存第一条凭据。")
        card.add(self.empty_hint)

        row = QHBoxLayout()
        self.edit_button = button("编辑")
        self.edit_button.clicked.connect(self._edit_account)
        self.delete_button = danger_button("删除")
        self.delete_button.clicked.connect(self._delete_account)
        self.verify_button = button("验证解密")
        self.verify_button.clicked.connect(self._verify_secret)
        row.addWidget(self.edit_button)
        row.addWidget(self.delete_button)
        row.addWidget(self.verify_button)
        row.addStretch(1)
        card.add_layout(row)
        self._set_selection_buttons(False)
        return card

    def _build_right_column(self) -> QWidget:
        column = QWidget()
        column.setObjectName("Root")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_login_card())
        log_card = Card()
        log_header = QHBoxLayout()
        log_header.addWidget(SectionTitle("运行日志"))
        log_header.addStretch(1)
        clear = ghost_button("清空")
        clear.clicked.connect(lambda: self.log_view.clear())
        log_header.addWidget(clear)
        log_card.add_layout(log_header)
        self.log_view = LogPanel(self.log_handler)
        log_card.add(self.log_view, 1)
        layout.addWidget(log_card, 1)
        return column

    def _build_login_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(SectionTitle("登录"))
        header.addStretch(1)
        self.target_badge = Badge("未找到", "warn")
        header.addWidget(self.target_badge)
        card.add_layout(header)

        self.target_title_label = BigValueLabel("正在查找目标窗口…")
        self.target_meta = MutedLabel("")
        card.add(self.target_title_label)
        card.add(self.target_meta)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.refresh_target_button = button("刷新")
        self.refresh_target_button.clicked.connect(self.refresh_target)
        self.choose_target_button = button("选择窗口")
        self.choose_target_button.clicked.connect(self._choose_target)
        self.calibrate_button = button("校准")
        self.calibrate_button.clicked.connect(self._start_calibration)
        self.clear_manual_button = ghost_button("清除手动")
        self.clear_manual_button.clicked.connect(self._clear_manual_target)
        self.clear_manual_button.setVisible(False)
        controls.addWidget(self.refresh_target_button)
        controls.addWidget(self.choose_target_button)
        controls.addWidget(self.calibrate_button)
        controls.addWidget(self.clear_manual_button)
        controls.addStretch(1)
        card.add_layout(controls)

        self.target_warning = HintLabel("")
        self.target_warning.setStyleSheet("color:#b91c1c;")
        self.target_warning.setVisible(False)
        card.add(self.target_warning)

        self.selected_name = BigValueLabel("未选择账号")
        self.selected_account = MutedLabel("")
        self.selected_password = MutedLabel("密码：—")
        card.add(self.selected_name)
        card.add(self.selected_account)
        card.add(self.selected_password)

        self.login_status = HintLabel("请选择账号并确保登录器窗口已找到。")
        self.login_status.setMinimumHeight(30)
        card.add(self.login_status)

        login_row = QHBoxLayout()
        self.login_button = primary_button("自动登录")
        self.login_button.setMinimumHeight(46)
        self.login_button.setEnabled(False)
        self.login_button.clicked.connect(self._start_login)
        login_row.addWidget(self.login_button, 1)
        self.cancel_button = danger_button("取消")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_login)
        login_row.addWidget(self.cancel_button)
        card.add_layout(login_row)

        hint = HintLabel(
            "盲填模式：密码框不可读，工具只负责输入并观察窗口状态；"
            "失败最多自动重试 1 次，最终请手动确认。\n"
            "登录期间主窗口会自动最小化，避免和登录器抢前台；结果出来后恢复。"
        )
        card.add(hint)
        return card

    # -- accounts ----------------------------------------------------------
    def refresh_accounts(self, select_id: str | None = None) -> None:
        current = select_id or self._current_id
        records = self.store.find(self.search_edit.text())
        self._visible_records = records
        self.table.blockSignals(True)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            name_item = QTableWidgetItem(record.name)
            name_item.setData(Qt.UserRole, record.id)
            account_item = QTableWidgetItem(record.account)
            password_item = QTableWidgetItem(record.display_password)
            password_item.setTextAlignment(Qt.AlignCenter)
            for column, item in enumerate((name_item, account_item, password_item)):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.count_label.setText(f"{len(records)} / {len(self.store)} 条")

        target_row = -1
        if current:
            for row, record in enumerate(records):
                if record.id == current:
                    target_row = row
                    break
        if target_row < 0 and self.config.last_selected_id:
            for row, record in enumerate(records):
                if record.id == self.config.last_selected_id:
                    target_row = row
                    break
        if target_row < 0 and records:
            target_row = 0
        if target_row >= 0:
            self.table.selectRow(target_row)
            self._on_selection_changed()
        else:
            self._current_id = None
            self._on_selection_changed()

        if not records:
            self.empty_hint.setVisible(True)
            self.empty_hint.setText(
                "没有匹配的账号。" if len(self.store) > 0 else "还没有账号。点击“添加”保存第一条凭据。"
            )
        else:
            self.empty_hint.setVisible(False)

    def _selected_record(self) -> AccountRecord | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        record_id = item.data(Qt.UserRole)
        if not record_id:
            return None
        return self.store.get(str(record_id))

    def _on_selection_changed(self) -> None:
        record = self._selected_record()
        self._set_selection_buttons(record is not None)
        if record is None:
            self._current_id = None
            self.selected_name.setText("未选择账号")
            self.selected_account.setText("")
            self.selected_password.setText("密码：—")
            self._update_login_button()
            return
        self._current_id = record.id
        self.selected_name.setText(record.name)
        self.selected_account.setText(record.account)
        self.selected_password.setText(f"密码：{record.display_password}")
        self.config.last_selected_id = record.id
        self._config_timer.start()
        self._update_login_button()

    def _set_selection_buttons(self, enabled: bool) -> None:
        enabled = enabled and not self._busy
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.verify_button.setEnabled(enabled)

    def _add_account(self) -> None:
        if self._busy:
            return
        dialog = AccountDialog(self.store, None, self)
        if dialog.exec() == AccountDialog.Accepted and dialog.saved_record:
            LOGGER.info("账号已添加：id=%s", dialog.saved_record.id)
            self.refresh_accounts(select_id=dialog.saved_record.id)

    def _edit_account(self) -> None:
        if self._busy:
            return
        record = self._selected_record()
        if record is None:
            return
        dialog = AccountDialog(self.store, record, self)
        if dialog.exec() == AccountDialog.Accepted and dialog.saved_record:
            LOGGER.info("账号已更新：id=%s", record.id)
            self.refresh_accounts(select_id=record.id)

    def _delete_account(self) -> None:
        if self._busy:
            return
        record = self._selected_record()
        if record is None:
            return
        answer = QMessageBox.question(
            self,
            "删除账号",
            f"确定删除「{record.name}」({record.account}) 吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.delete(record.id)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", f"无法删除：{exc}")
            return
        LOGGER.info("账号已删除：id=%s", record.id)
        if self.config.last_selected_id == record.id:
            self.config.last_selected_id = None
        self.refresh_accounts()
        self._schedule_save()

    def _verify_secret(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        try:
            length = self.store.verify_decrypt(record.id)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "解密失败",
                f"无法解密该记录：{exc}\n\n"
                "密文只能由保存它的 Windows 用户在同一台计算机上解密。",
            )
            LOGGER.warning("解密验证失败：id=%s", record.id)
            return
        QMessageBox.information(
            self,
            "解密验证",
            f"DPAPI 解密成功（明文长度 {length} 字节，已立即覆写）。\n"
            "本对话框不会显示密码。",
        )
        LOGGER.info("解密验证成功：id=%s", record.id)

    def _table_menu(self, position) -> None:  # type: ignore[no-untyped-def]
        record = self._selected_record()
        if record is None:
            return
        menu = QMenu(self)
        edit_action = QAction("编辑", menu)
        edit_action.triggered.connect(self._edit_account)
        delete_action = QAction("删除", menu)
        delete_action.triggered.connect(self._delete_account)
        verify_action = QAction("验证解密", menu)
        verify_action.triggered.connect(self._verify_secret)
        copy_action = QAction("复制账号", menu)
        copy_action.triggered.connect(lambda: self._copy_account(record))
        menu.addAction(edit_action)
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(verify_action)
        menu.addAction(delete_action)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _copy_account(self, record: AccountRecord) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(record.account)
        self.statusBar().showMessage("账号已复制到剪贴板", 2500)

    # -- target ------------------------------------------------------------
    def refresh_target(self) -> None:
        if self._busy or self._calibrating:
            return
        if self._matcher is None:
            self._target_info = None
            self._target_source = "none"
            self._target_candidates = 0
            self._target_blocked = False
            self._apply_target_ui()
            self.diagnostics_panel.set_target(None, "正则无效", 0)
            return
        try:
            windows = winapi.enum_top_windows(exclude_pid=os.getpid(), include_tool_windows=False)
        except Exception as exc:
            LOGGER.warning("枚举窗口失败：%s", type(exc).__name__)
            self._target_info = None
            self._target_source = "none"
            self._target_candidates = 0
            self._target_blocked = False
            self._apply_target_ui()
            self.diagnostics_panel.set_target(None, "枚举失败", 0)
            return

        match = resolve_target(windows, self._matcher, self.config.manual_target)
        info = match.window
        if info is not None:
            enriched = winapi.get_window_info(info.hwnd, include_integrity=True)
            if enriched is not None:
                info = enriched
        self._target_info = info
        self._target_source = match.source
        self._target_candidates = len(match.candidates)
        self._apply_target_ui()
        source_text = {"manual": "手动目标", "auto": "标题/类名正则", "none": "未找到"}.get(
            match.source, match.source
        )
        self.diagnostics_panel.set_target(info, source_text, len(match.candidates))
        key = (info.hwnd, match.source) if info else None
        if key != self._last_target_key:
            self._last_target_key = key
            if info:
                LOGGER.info(
                    "目标窗口：%s (0x%X, PID %d, %s)，来源=%s",
                    info.title,
                    info.hwnd,
                    info.pid,
                    info.integrity_text,
                    source_text,
                )
            else:
                LOGGER.info("未找到目标窗口（来源=%s）", source_text)

    def _apply_target_ui(self) -> None:
        info = self._target_info
        manual = self.config.manual_target
        self.clear_manual_button.setVisible(manual is not None)
        self._target_blocked = False
        warning = ""
        if info is None:
            self.target_badge.set_state("未找到", "warn")
            self.target_title_label.setText("未找到目标登录器")
            if manual is not None:
                self.target_meta.setText("已保存手动目标，但该窗口当前不存在；请启动登录器或重新选择。")
            else:
                self.target_meta.setText("请启动登录器后点击“刷新”，或点击“选择窗口”手动指定。")
            self.calibrate_button.setEnabled(False)
        else:
            self.target_badge.set_state("手动目标" if self._target_source == "manual" else "已找到", "ok")
            self.target_title_label.setText(info.title or "（无标题窗口）")
            meta = (
                f"HWND {info.hwnd_hex} · PID {info.pid} · 类名 {info.class_name}\n"
                f"完整性：{info.integrity_text}"
            )
            if self._target_source == "auto" and self._target_candidates > 1:
                meta += f" · 另有 {self._target_candidates - 1} 个候选"
            if manual is not None and self._target_source == "auto":
                meta += " · 手动目标未找到，已回退到自动匹配"
            self.target_meta.setText(meta)
            self.calibrate_button.setEnabled(True)
            if info.integrity and info.integrity.rid is not None:
                own = winapi.self_integrity()
                if own.rid is not None and info.integrity.rid > own.rid:
                    self._target_blocked = True
                    warning = (
                        f"目标完整性级别（{info.integrity.label}）高于本工具（{own.label}）。\n"
                        "Windows UIPI 会阻止输入，请以管理员身份运行本工具后重试。"
                    )
            elif info.integrity and info.integrity.error == 5:
                self._target_blocked = True
                warning = (
                    "无法读取目标进程的完整性级别（拒绝访问），目标可能以更高权限运行。\n"
                    "请以管理员身份运行本工具后重试。"
                )
            elif info.integrity and info.integrity.rid is None:
                warning = "无法读取目标完整性级别；仍可尝试，失败时请查看诊断面板。"
        self.target_warning.setText(warning)
        self.target_warning.setVisible(bool(warning))
        if info is not None:
            if self._target_blocked:
                self.target_badge.set_state("权限不足", "error")
            elif warning:
                self.target_badge.set_state("需注意", "warn")
        self._update_login_button()

    def _update_login_button(self) -> None:
        record = self._selected_record()
        ready = bool(record and self._target_info and not self._busy and not self._target_blocked)
        self.login_button.setEnabled(ready)
        if self._busy:
            return
        if record is None:
            self.login_status.setText("请选择一个账号。")
        elif self._target_info is None:
            self.login_status.setText("未找到目标窗口；请刷新或手动选择登录器。")
        elif self._target_blocked:
            self.login_status.setText("目标权限更高：请以管理员身份运行本工具。")
        else:
            self.login_status.setText("准备就绪。点击后会把焦点切到登录器并输入凭据。")

    def _choose_target(self) -> None:
        if self._busy:
            return
        dialog = ManualTargetDialog(self)
        if dialog.exec() != ManualTargetDialog.Accepted:
            return
        info = dialog.selected_window()
        if info is None:
            return
        self.config.manual_target = ManualTarget(
            title=info.title,
            class_name=info.class_name,
            exe=info.exe,
        )
        try:
            save_config(self.config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"无法保存手动目标：{exc}")
            return
        LOGGER.info("手动目标已保存：%s (0x%X)", info.title, info.hwnd)
        self._last_target_key = None
        self.refresh_target()

    def _clear_manual_target(self) -> None:
        self.config.manual_target = None
        try:
            save_config(self.config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"无法清除手动目标：{exc}")
            return
        LOGGER.info("手动目标已清除")
        self._last_target_key = None
        self.refresh_target()

    def _start_calibration(self) -> None:
        if self._busy or self._calibrating:
            return
        if self._target_info is None:
            QMessageBox.information(self, "校准", "请先找到目标登录器窗口。")
            return
        if self.diagnostics_panel.is_busy():
            QMessageBox.information(self, "校准", "请等待当前自检或 UIA 探测完成后再校准。")
            return
        self._calibrating = True
        self._target_timer.stop()
        try:
            calibration = run_calibration(self, self._target_info)
        finally:
            self._calibrating = False
            self._target_timer.start()
        if calibration is None:
            self._update_login_button()
            return
        self.config.calibration = calibration
        try:
            save_config(self.config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"校准结果无法写入配置：{exc}")
            return
        QMessageBox.information(
            self,
            "校准完成",
            "三个坐标已保存。建议先执行“记事本自检”，再回到登录器实机测试。",
        )
        self.login_status.setText("校准已保存。建议先做“记事本自检”，再实机登录。")
        self.refresh_target()

    # -- login -------------------------------------------------------------
    def _start_login(self) -> None:
        if self._busy:
            return
        if self.diagnostics_panel.is_busy():
            QMessageBox.information(self, "登录", "请等待当前自检或 UIA 探测完成后再登录。")
            return
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "登录", "请先选择一个账号。")
            return
        info = self._target_info
        if info is None:
            QMessageBox.warning(self, "未找到目标窗口", "请启动登录器后点击“刷新”，或手动选择目标窗口。")
            self.refresh_target()
            return
        current = winapi.get_window_info(info.hwnd, include_integrity=False)
        if current is None:
            QMessageBox.warning(self, "目标窗口已关闭", "目标窗口已不存在，请刷新后重新选择。")
            self._target_info = None
            self._apply_target_ui()
            return
        if winapi.is_minimized(info.hwnd):
            QMessageBox.warning(self, "目标窗口已最小化", "请先还原登录器窗口，再点击自动登录。")
            return
        if self._target_blocked:
            QMessageBox.warning(
                self,
                "权限不足",
                "目标进程的完整性级别更高，Windows 会阻止键盘输入。\n"
                "请以管理员身份运行本工具后重试。",
            )
            return

        account_bytes = record.account.encode("utf-8")
        if first_unsupported_byte(account_bytes) is not None:
            QMessageBox.warning(
                self,
                "账号包含无法模拟的字符",
                describe_unsupported(account_bytes)
                + "\n\n请手动输入该账号，或改用只含 ASCII 可打印字符的账号。",
            )
            return

        cancel_event = threading.Event()
        options = AutomationOptions.from_config(self.config)
        request = AutomationRequest(
            hwnd=info.hwnd,
            account=bytearray(account_bytes),
            password_provider=lambda: self.store.decrypt_password(record.id),
            options=options,
            calibration=self.config.calibration,
            cancel=cancel_event,
        )
        worker = LoginWorker(request)
        worker.result.connect(self._on_login_result)
        worker.finished.connect(self._on_login_finished)
        worker.progress.connect(self._on_login_progress)
        self._login_worker = worker
        self._cancel_event = cancel_event
        self._set_busy(True)
        self.login_status.setText("正在登录：抢焦点并输入凭据…")
        LOGGER.info(
            "开始登录：目标=%s (0x%X)，账号 id=%s，最多 %d 次",
            info.title,
            info.hwnd,
            record.id,
            options.max_attempts,
        )
        # 主窗口在前台会与目标抢焦点（Windows 前台锁可能把焦点还给本程序）。
        # 输入期间最小化，让目标稳定处于前台；结果对话框出现前再恢复。
        self.showMinimized()
        QApplication.processEvents()
        LOGGER.info("登录期间主窗口已最小化，避免与目标窗口抢前台")
        worker.start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.add_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.refresh_target_button.setEnabled(not busy)
        self.choose_target_button.setEnabled(not busy)
        self.calibrate_button.setEnabled(not busy and self._target_info is not None)
        self.clear_manual_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.login_button.setText("登录中…" if busy else "自动登录")
        self.tabs.setTabEnabled(1, not busy)
        self._set_selection_buttons(not busy)
        if busy:
            self._target_timer.stop()
            self.login_button.setEnabled(False)
        else:
            self._target_timer.start()
            self._update_login_button()

    def _cancel_login(self) -> None:
        if self._login_worker is None or not self._login_worker.isRunning():
            return
        LOGGER.info("用户请求取消登录")
        self.cancel_button.setEnabled(False)
        self.login_status.setText("正在取消…（会在当前字符/等待结束后停止）")
        self._login_worker.cancel()

    def _on_login_progress(self, message: str) -> None:
        self.login_status.setText(message)
        self.statusBar().showMessage(message, 2500)

    def _on_login_result(self, report: AutomationReport) -> None:
        LOGGER.info(
            "登录结果：code=%s attempts=%d events=%d/%d duration=%.1fs",
            report.code,
            report.attempts,
            report.events_total,
            report.events_failed,
            report.duration_s,
        )
        self._restore_after_login()
        self.login_status.setText(report.headline)
        self._show_report_dialog(report)

    def _restore_after_login(self) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _show_report_dialog(self, report: AutomationReport) -> None:
        box = QMessageBox(self)
        if report.ok_likely:
            box.setIcon(QMessageBox.Information)
        elif report.code in {"uipi", "integrity", "integrity_unknown", "error", "worker_crash"}:
            box.setIcon(QMessageBox.Critical)
        elif report.code in {"cancelled", "debug_input_only"}:
            box.setIcon(QMessageBox.Information)
        else:
            box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("登录结果")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<b>{html.escape(report.headline)}</b><br><br>"
            f"{html.escape(report.detail).replace(chr(10), '<br>')}"
        )
        details = list(report.steps)
        details.append("")
        details.append(f"目标：{report.target_title} (0x{report.target_hwnd:X})")
        details.append(f"尝试次数：{report.attempts}")
        details.append(f"SendInput 事件：{report.events_total} 次，失败 {report.events_failed} 次")
        details.append(f"耗时：{report.duration_s:.1f} 秒")
        if report.verdict and report.verdict.error_texts:
            details.append("检测到的新文本：")
            details.extend(f"  · {text}" for text in report.verdict.error_texts)
        box.setDetailedText("\n".join(details))
        box.addButton(QMessageBox.Ok)
        calibrate_button = None
        refresh_button = None
        if report.code in {"calibration_required", "calibration_stale", "focus_wrong_field", "input_not_delivered"}:
            calibrate_button = box.addButton("重新校准", QMessageBox.ActionRole)
        if report.code in {"window_gone", "no_window", "window_minimized"}:
            refresh_button = box.addButton("刷新目标", QMessageBox.ActionRole)
        box.exec()
        clicked = box.clickedButton()
        if calibrate_button is not None and clicked is calibrate_button:
            QTimer.singleShot(0, self._start_calibration)
        elif refresh_button is not None and clicked is refresh_button:
            self.refresh_target()

    def _on_login_finished(self) -> None:
        self._login_worker = None
        self._cancel_event = None
        self._restore_after_login()
        self._set_busy(False)
        self.refresh_target()
        self.login_status.setText("登录流程已结束。请根据结果手动确认。")

    # -- config / settings -------------------------------------------------
    def _schedule_save(self) -> None:
        self._config_timer.start()

    def _save_config_now(self) -> None:
        try:
            self.config.window_geometry_b64 = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            save_config(self.config)
        except Exception as exc:
            LOGGER.error("保存配置失败：%s", type(exc).__name__)

    def _on_config_saved_externally(self) -> None:
        self.diagnostics_panel.block_input_check.blockSignals(True)
        self.diagnostics_panel.block_input_check.setChecked(self.config.input.block_input)
        self.diagnostics_panel.block_input_check.blockSignals(False)
        self.diagnostics_panel.input_only_check.blockSignals(True)
        self.diagnostics_panel.input_only_check.setChecked(self.config.input.input_only_no_click)
        self.diagnostics_panel.input_only_check.blockSignals(False)
        try:
            self._matcher = WindowMatcher(self.config.window_match)
            self._matcher_error = None
        except WindowMatchError as exc:
            self._matcher = None
            self._matcher_error = str(exc)
            QMessageBox.warning(self, "正则无效", f"{exc}\n\n请回到设置修正窗口匹配规则。")
        self._last_target_key = None
        self.refresh_target()

    def _open_settings(self) -> None:
        if self._busy:
            return
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == SettingsDialog.Accepted:
            self._on_config_saved_externally()
            LOGGER.info("设置已保存")
            self.statusBar().showMessage("设置已保存", 3000)

    def _open_data_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_home())))

    # -- warnings / lifecycle ---------------------------------------------
    def _show_load_warnings(self) -> None:
        warnings = list(self.config_warnings)
        if self.store.warning:
            warnings.append(self.store.warning)
        if not warnings:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("加载提示")
        box.setText("部分数据或配置未能正常加载，请检查：")
        box.setDetailedText("\n\n".join(warnings))
        box.exec()

    def _restore_geometry(self) -> None:
        value = self.config.window_geometry_b64
        if not value:
            return
        try:
            data = base64.b64decode(value.encode("ascii"))
            self.restoreGeometry(QByteArray(data))
        except Exception:
            LOGGER.debug("恢复窗口位置失败")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            answer = QMessageBox.question(
                self,
                "登录进行中",
                "登录流程仍在运行。退出会请求取消并等待线程结束，确定退出？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._login_worker.cancel()
            if not self._login_worker.wait(15000):
                QMessageBox.warning(self, "无法退出", "登录线程未能及时结束，已取消退出以避免残留 BlockInput。")
                event.ignore()
                return
        try:
            self.diagnostics_panel.shutdown()
        except Exception:
            pass
        try:
            self.config.window_geometry_b64 = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            save_config(self.config)
        except Exception as exc:
            LOGGER.error("退出时保存配置失败：%s", type(exc).__name__)
        try:
            self._target_timer.stop()
        except Exception:
            pass
        logging.getLogger("login_assistant").removeHandler(self.log_handler)
        super().closeEvent(event)
