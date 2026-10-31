"""小型可复用界面控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, margins: tuple[int, int, int, int] = (16, 16, 16, 16), spacing: int = 10) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.NoFrame)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)

    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self._layout.addLayout(layout)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class MutedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Muted")
        self.setWordWrap(True)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)


class HintLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Hint")
        self.setWordWrap(True)


class FieldLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Muted")


class ValueLabel(QLabel):
    def __init__(self, text: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Value")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWordWrap(True)


class BigValueLabel(QLabel):
    def __init__(self, text: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("BigValue")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWordWrap(True)


class Badge(QLabel):
    def __init__(self, text: str = "未连接", state: str = "idle", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_state(text, state)

    def set_state(self, text: str, state: str) -> None:
        self.setText(text)
        self.setProperty("state", state)
        style = self.style()
        style.unpolish(self)
        style.polish(self)


def button(text: str, *, kind: str = "secondary", parent: QWidget | None = None) -> QPushButton:
    widget = QPushButton(text, parent)
    widget.setProperty("kind", kind)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def primary_button(text: str, *, parent: QWidget | None = None) -> QPushButton:
    return button(text, kind="primary", parent=parent)


def danger_button(text: str, *, parent: QWidget | None = None) -> QPushButton:
    return button(text, kind="danger", parent=parent)


def ghost_button(text: str, *, parent: QWidget | None = None) -> QPushButton:
    return button(text, kind="ghost", parent=parent)
