"""界面主题（浅色、圆角卡片、蓝色主色）。"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

QSS = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f4f6f9;
}
QWidget#Root {
    background: #f4f6f9;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}
QLabel#AppTitle {
    font-size: 22px;
    font-weight: 600;
    color: #111827;
}
QLabel#AppSubtitle {
    color: #6b7280;
    font-size: 12px;
}
QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 600;
    color: #111827;
}
QLabel#Muted {
    color: #6b7280;
    font-size: 12px;
}
QLabel#Hint {
    color: #9ca3af;
    font-size: 12px;
}
QLabel#Value {
    color: #111827;
}
QLabel#BigValue {
    font-size: 15px;
    font-weight: 600;
    color: #111827;
}
QLabel#Badge {
    padding: 3px 10px;
    border-radius: 10px;
    font-size: 12px;
}
QLabel#Badge[state="ok"] {
    background: #dcfce7;
    color: #166534;
}
QLabel#Badge[state="warn"] {
    background: #fef3c7;
    color: #92400e;
}
QLabel#Badge[state="error"] {
    background: #fee2e2;
    color: #991b1b;
}
QLabel#Badge[state="idle"] {
    background: #e5e7eb;
    color: #374151;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 14px;
    color: #111827;
}
QPushButton:hover {
    background: #f9fafb;
    border-color: #9ca3af;
}
QPushButton:pressed {
    background: #f3f4f6;
}
QPushButton:disabled {
    color: #9ca3af;
    background: #f3f4f6;
    border-color: #e5e7eb;
}
QPushButton[kind="primary"] {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[kind="primary"]:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}
QPushButton[kind="primary"]:disabled {
    background: #bfdbfe;
    border-color: #bfdbfe;
    color: #ffffff;
}
QPushButton[kind="danger"] {
    color: #b91c1c;
    border-color: #fecaca;
    background: #fff5f5;
}
QPushButton[kind="danger"]:hover {
    background: #fee2e2;
}
QPushButton[kind="ghost"] {
    background: transparent;
    border: none;
    color: #2563eb;
    padding: 4px 8px;
}
QPushButton[kind="ghost"]:hover {
    background: #eff6ff;
}
QLineEdit, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: #bfdbfe;
    selection-color: #111827;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background: #f9fafb;
    color: #9ca3af;
}
QCheckBox {
    spacing: 6px;
    color: #374151;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #9ca3af;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
    image: none;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    gridline-color: #f1f5f9;
    alternate-background-color: #f9fafb;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTableWidget::item {
    padding: 6px 8px;
}
QHeaderView::section {
    background: #f8fafc;
    color: #475569;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 8px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #6b7280;
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
    font-weight: 600;
}
QTabBar::tab:hover {
    color: #111827;
}
QPlainTextEdit#LogView {
    background: #0f172a;
    color: #d1fae5;
    border: 1px solid #0f172a;
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: #1e3a8a;
}
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    color: #6b7280;
}
QStatusBar::item {
    border: none;
}
QToolTip {
    background: #111827;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 5px;
    min-width: 30px;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(QSS)
