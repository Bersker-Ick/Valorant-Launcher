"""设置对话框：窗口匹配规则、输入参数、调试开关。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, save_config
from ..core import winapi
from ..core.windowmatch import WindowMatchConfig, WindowMatcher, WindowMatchError
from .widgets import HintLabel, MutedLabel, button


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(600, 520)
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_match_tab(), "窗口匹配")
        tabs.addTab(self._build_input_tab(), "输入")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Save).setProperty("kind", "primary")
        reset = buttons.addButton("恢复默认", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset_defaults)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_match_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        hint = MutedLabel(
            "标题与类名都使用 Python 正则（re.search）。默认要求两者同时匹配，"
            "以减少把浏览器/源码工具误认成登录器。修改后可用“测试规则”查看命中窗口。"
        )
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.title_regex = QLineEdit()
        self.title_regex.setPlaceholderText("例如 (?i)(riot\\s*client|valorant)")
        form.addRow("标题正则", self.title_regex)

        self.class_regex = QLineEdit()
        self.class_regex.setPlaceholderText("例如 (?i)(riot|cef|chrome_widgetwin)")
        form.addRow("类名正则", self.class_regex)

        self.exclude_regex = QLineEdit()
        self.exclude_regex.setPlaceholderText("匹配到的窗口会被排除")
        form.addRow("排除正则", self.exclude_regex)

        self.process_regex = QLineEdit()
        self.process_regex.setPlaceholderText("可选：按进程完整路径过滤")
        form.addRow("进程正则", self.process_regex)

        layout.addLayout(form)

        self.require_both = QCheckBox("标题和类名必须同时匹配")
        layout.addWidget(self.require_both)

        test_row = QHBoxLayout()
        self.test_button = button("测试规则（当前窗口）")
        self.test_button.clicked.connect(self._test_rules)
        test_row.addWidget(self.test_button)
        self.test_result = HintLabel("")
        test_row.addWidget(self.test_result, 1)
        layout.addLayout(test_row)

        layout.addStretch(1)
        return page

    def _build_input_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        delay_row = QHBoxLayout()
        self.delay_min = QSpinBox()
        self.delay_min.setRange(0, 1000)
        self.delay_min.setSuffix(" ms")
        self.delay_max = QSpinBox()
        self.delay_max.setRange(0, 1000)
        self.delay_max.setSuffix(" ms")
        delay_row.addWidget(self.delay_min)
        delay_row.addWidget(QLabel("至"))
        delay_row.addWidget(self.delay_max)
        delay_row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(delay_row)
        form.addRow("字符间隔", wrap)

        self.verify_wait = QSpinBox()
        self.verify_wait.setRange(800, 15000)
        self.verify_wait.setSingleStep(250)
        self.verify_wait.setSuffix(" ms")
        form.addRow("提交后观察时间", self.verify_wait)

        layout.addLayout(form)

        self.block_input = QCheckBox("输入期间调用 BlockInput(True) 屏蔽物理键鼠")
        layout.addWidget(self.block_input)

        block_hint = HintLabel(
            "BlockInput 是可选高风险项：它会暂时屏蔽真实键盘鼠标，程序用 try/finally 恢复；"
            "若工作线程异常退出，Windows 也会在该线程结束时自动解除。建议只在确认环境时开启。"
        )
        block_hint.setStyleSheet("color:#b45309;")
        layout.addWidget(block_hint)

        self.auto_enter = QCheckBox("找不到登录按钮时用 Enter 提交")
        layout.addWidget(self.auto_enter)

        self.input_only = QCheckBox("仅输入不点击（调试：不点击登录按钮，也不自动重试）")
        layout.addWidget(self.input_only)

        self.password_uia = QCheckBox("密码用 UIA ValuePattern 写入（实验，非键盘）")
        layout.addWidget(self.password_uia)
        uia_hint = HintLabel(
            "当密码框拒绝 SendInput 时，可尝试通过 Windows UI Automation 直接写入。"
            "这不是键盘模拟；密码框可能不支持或只读，失败会明确报错。密码值不会写入日志。"
        )
        uia_hint.setStyleSheet("color:#b45309;")
        layout.addWidget(uia_hint)

        retry_hint = MutedLabel(
            "登录失败最多自动重试 1 次；检测到明确的密码错误/验证码提示时会直接转为手动确认，"
            "避免触发风控计数。"
        )
        layout.addWidget(retry_hint)
        layout.addStretch(1)
        return page

    def _load(self) -> None:
        match = self.config.window_match
        self.title_regex.setText(match.title_regex)
        self.class_regex.setText(match.class_regex)
        self.exclude_regex.setText(match.exclude_title_regex)
        self.process_regex.setText(match.process_regex)
        self.require_both.setChecked(match.require_both)
        self.delay_min.setValue(self.config.input.delay_min_ms)
        self.delay_max.setValue(self.config.input.delay_max_ms)
        self.verify_wait.setValue(self.config.input.verify_wait_ms)
        self.block_input.setChecked(self.config.input.block_input)
        self.auto_enter.setChecked(self.config.input.auto_enter)
        self.input_only.setChecked(self.config.input.input_only_no_click)
        self.password_uia.setChecked(self.config.input.password_use_uia)

    def _collect_match(self) -> WindowMatchConfig:
        return WindowMatchConfig(
            title_regex=self.title_regex.text(),
            class_regex=self.class_regex.text(),
            exclude_title_regex=self.exclude_regex.text(),
            process_regex=self.process_regex.text(),
            require_both=self.require_both.isChecked(),
        )

    def _test_rules(self) -> None:
        cfg = self._collect_match()
        try:
            matcher = WindowMatcher(cfg)
        except WindowMatchError as exc:
            self.test_result.setText(f"正则无效：{exc}")
            self.test_result.setStyleSheet("color:#b91c1c;")
            return
        windows = winapi.enum_top_windows(include_tool_windows=True)
        matches = matcher.filter(windows)
        if not matches:
            self.test_result.setText(f"当前 {len(windows)} 个窗口中无匹配")
            self.test_result.setStyleSheet("color:#b45309;")
            return
        titles = "；".join(f"{w.title[:28]} (0x{w.hwnd:X})" for w in matches[:5])
        more = f" 等 {len(matches)} 个" if len(matches) > 5 else ""
        self.test_result.setText(f"命中 {len(matches)} 个：{titles}{more}")
        self.test_result.setStyleSheet("color:#166534;")

    def _reset_defaults(self) -> None:
        defaults = AppConfig()
        self.title_regex.setText(defaults.window_match.title_regex)
        self.class_regex.setText(defaults.window_match.class_regex)
        self.exclude_regex.setText(defaults.window_match.exclude_title_regex)
        self.process_regex.setText(defaults.window_match.process_regex)
        self.require_both.setChecked(defaults.window_match.require_both)
        self.delay_min.setValue(defaults.input.delay_min_ms)
        self.delay_max.setValue(defaults.input.delay_max_ms)
        self.verify_wait.setValue(defaults.input.verify_wait_ms)
        self.block_input.setChecked(defaults.input.block_input)
        self.auto_enter.setChecked(defaults.input.auto_enter)
        self.input_only.setChecked(defaults.input.input_only_no_click)
        self.password_uia.setChecked(defaults.input.password_use_uia)
        self.test_result.setText("已恢复默认值（尚未保存）")
        self.test_result.setStyleSheet("color:#6b7280;")

    def _on_save(self) -> None:
        match = self._collect_match()
        try:
            match.validate()
        except WindowMatchError as exc:
            QMessageBox.warning(self, "正则无效", f"{exc}\n\n请修正后再保存。")
            return
        if self.delay_min.value() > self.delay_max.value():
            QMessageBox.warning(self, "参数无效", "字符间隔下限不能大于上限。")
            return
        if self.block_input.isChecked() and not self.config.input.block_input:
            answer = QMessageBox.question(
                self,
                "启用 BlockInput？",
                "启用后，自检/登录期间物理键盘鼠标会被暂时屏蔽。\n"
                "程序会用 try/finally 恢复；工作线程退出时 Windows 也会自动解除。\n\n"
                "确认启用？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.block_input.setChecked(False)
                return
        self.config.window_match = match
        self.config.input.delay_min_ms = self.delay_min.value()
        self.config.input.delay_max_ms = self.delay_max.value()
        self.config.input.verify_wait_ms = self.verify_wait.value()
        self.config.input.block_input = self.block_input.isChecked()
        self.config.input.auto_enter = self.auto_enter.isChecked()
        self.config.input.input_only_no_click = self.input_only.isChecked()
        self.config.input.password_use_uia = self.password_uia.isChecked()
        try:
            self.config.normalize()
            save_config(self.config)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", f"无法保存配置：{exc}")
            return
        self.accept()
