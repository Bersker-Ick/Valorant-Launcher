"""添加 / 编辑账号对话框。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..core.models import AccountRecord
from ..core.store import AccountStore
from ..security.secret import wipe
from .widgets import HintLabel, MutedLabel


class AccountDialog(QDialog):
    def __init__(
        self,
        store: AccountStore,
        record: AccountRecord | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.record = record
        self.saved_record: AccountRecord | None = None
        self.setWindowTitle("编辑账号" if record else "添加账号")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.name_edit = QLineEdit(self.record.name if self.record else "")
        self.name_edit.setPlaceholderText("例如：主账号 / 小号")
        self.name_edit.setMaxLength(80)
        form.addRow("备注名", self.name_edit)

        self.account_edit = QLineEdit(self.record.account if self.record else "")
        self.account_edit.setPlaceholderText("账号 / 邮箱 / 手机号")
        self.account_edit.setMaxLength(200)
        form.addRow("账号", self.account_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMaxLength(256)
        if self.record:
            self.password_edit.setPlaceholderText("留空则保持原密码不变")
        else:
            self.password_edit.setPlaceholderText("登录密码")
        form.addRow("密码", self.password_edit)

        self.show_password = QCheckBox("显示密码")
        self.show_password.toggled.connect(self._toggle_password_visibility)
        form.addRow("", self.show_password)

        root.addLayout(form)

        self.warning = HintLabel("")
        self.warning.setStyleSheet("color:#b45309;")
        root.addWidget(self.warning)

        note = MutedLabel(
            "密码使用 Windows DPAPI（CurrentUser）加密后保存，落盘只有密文；"
            "列表、日志与异常信息不会显示明文。仅支持 A-Z、a-z、0-9 和常见英文符号自动输入。"
        )
        root.addWidget(note)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#b91c1c;")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Save).setProperty("kind", "primary")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.name_edit.textChanged.connect(self._validate_hint)
        self.account_edit.textChanged.connect(self._validate_hint)
        self.password_edit.textChanged.connect(self._validate_hint)
        self._validate_hint()
        self.name_edit.setFocus()

    def _toggle_password_visibility(self, visible: bool) -> None:
        self.password_edit.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)

    def _validate_hint(self) -> None:
        warnings: list[str] = []
        account = self.account_edit.text()
        password = self.password_edit.text()
        for label, value in (("账号", account), ("密码", password)):
            if value and any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in value):
                warnings.append(
                    f"{label}包含非 ASCII 字符，自动输入无法模拟这些字符；"
                    "仍可保存，但登录时需要手动输入。"
                )
        self.warning.setText("\n".join(dict.fromkeys(warnings)))
        self.warning.setVisible(bool(warnings))

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        account = self.account_edit.text().strip()
        password_text = self.password_edit.text()
        if not name:
            self._show_error("备注名不能为空")
            return
        if not account:
            self._show_error("账号不能为空")
            return
        if not self.record and not password_text:
            self._show_error("密码不能为空")
            return

        password_buf: bytearray | None = None
        try:
            if password_text:
                password_buf = bytearray(password_text.encode("utf-8"))
            if self.record is None:
                record = self.store.add(name, account, password_buf or bytearray())
            else:
                record = self.store.update(
                    self.record.id,
                    name=name,
                    account=account,
                    new_password=password_buf,
                )
            self.saved_record = record
        except Exception as exc:
            # DPAPIError / StoreError / ValueError 的消息都不含明文
            self._show_error(f"保存失败：{exc}")
            return
        finally:
            wipe(password_buf)
            self.password_edit.clear()
            password_text = ""
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        QMessageBox.critical(self, "无法保存", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.password_edit.clear()
        super().closeEvent(event)
