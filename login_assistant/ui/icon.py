"""程序图标（运行时用 QPainter 生成，避免外部资源依赖）。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def _render(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(size / 64.0, size / 64.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2563eb"))
        painter.drawRoundedRect(QRectF(3, 3, 58, 58), 14, 14)

        pen = QPen(QColor("#ffffff"), 4.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(24, 32), 8.5, 8.5)
        painter.drawLine(QPointF(32.5, 32), QPointF(49, 32))
        painter.drawLine(QPointF(44, 32), QPointF(44, 38))
        painter.drawLine(QPointF(49, 32), QPointF(49, 37))
    finally:
        painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(size))
    return icon


def save_png(path: str, size: int = 256) -> None:
    _render(size).save(path, "PNG")
