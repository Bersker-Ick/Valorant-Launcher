"""校准模式：全屏半透明遮罩依次捕获账号框/密码框/登录按钮的屏幕坐标。

不使用全局鼠标 hook：遮罩自己接收点击并记录 Win32 物理光标坐标，
然后把“相对目标客户区”的物理像素坐标保存到配置。
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from ..core import winapi
from ..core.models import CalibrationPoint, CalibrationSet, WindowInfo

LOGGER = logging.getLogger("login_assistant.ui.calibration")

STEP_TEXTS = (
    ("账号输入框", "请点击目标登录器的【账号输入框】"),
    ("密码框", "请点击目标登录器的【密码输入框】"),
    ("登录按钮", "请点击目标登录器的【登录按钮】"),
)


class CalibrationOverlay(QDialog):
    def __init__(
        self,
        client_rect: tuple[int, int, int, int],
        virtual_geometry: QRect,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_rect = client_rect
        self._points: list[tuple[int, int]] = []
        self._message = ""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setGeometry(virtual_geometry)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    @property
    def points(self) -> list[tuple[int, int]]:
        return list(self._points)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor(2, 6, 23, 165))

            panel_width = min(760, max(460, self.width() - 120))
            panel = QRectF((self.width() - panel_width) / 2, 70, panel_width, 300)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(15, 23, 42, 235))
            painter.drawRoundedRect(panel, 14, 14)

            painter.setPen(QColor("#f8fafc"))
            title_font = QFont("Microsoft YaHei UI", 20, QFont.Bold)
            painter.setFont(title_font)
            painter.drawText(
                QRectF(panel.left() + 28, panel.top() + 22, panel.width() - 56, 36),
                Qt.AlignLeft | Qt.AlignVCenter,
                "校准登录器坐标",
            )

            if self._points:
                step_index = min(len(self._points), 2)
            else:
                step_index = 0
            _, instruction = STEP_TEXTS[step_index]
            painter.setPen(QColor("#93c5fd"))
            painter.setFont(QFont("Microsoft YaHei UI", 15, QFont.Bold))
            painter.drawText(
                QRectF(panel.left() + 28, panel.top() + 72, panel.width() - 56, 32),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"第 {len(self._points) + 1}/3 步：{instruction}",
            )

            painter.setPen(QColor("#cbd5e1"))
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(
                QRectF(panel.left() + 28, panel.top() + 112, panel.width() - 56, 52),
                Qt.AlignLeft | Qt.TextWordWrap,
                "点击只记录屏幕坐标，不会传给目标窗口；请确保登录器窗口完整可见。\n"
                "按 Esc 取消。坐标不会上传，只保存在本机 config.json。",
            )

            y = panel.top() + 176
            for index, (label, _text) in enumerate(STEP_TEXTS):
                done = index < len(self._points)
                painter.setPen(QColor("#86efac") if done else QColor("#64748b"))
                painter.setFont(QFont("Microsoft YaHei UI", 10))
                marker = "✓" if done else "○"
                painter.drawText(
                    QRectF(panel.left() + 28, y, panel.width() - 56, 24),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"{marker}  {label}" + ("（已记录）" if done else ""),
                )
                y += 28

            if self._message:
                painter.setPen(QColor("#fca5a5"))
                painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
                painter.drawText(
                    QRectF(panel.left() + 28, panel.top() + 262, panel.width() - 56, 26),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    self._message,
                )

            # 已记录点的小十字（局部坐标近似即可，仅作视觉反馈）
            painter.setPen(QPen(QColor("#22c55e"), 2))
            for index, (x, y) in enumerate(self._points):
                local = self.mapFromGlobal(self._screen_to_qt_global(x, y))
                painter.drawLine(local.x() - 9, local.y(), local.x() + 9, local.y())
                painter.drawLine(local.x(), local.y() - 9, local.x(), local.y() + 9)
                painter.drawText(local.x() + 12, local.y() - 8, str(index + 1))
        finally:
            painter.end()

    def _screen_to_qt_global(self, x: int, y: int):  # type: ignore[no-untyped-def]
        # 物理 -> Qt 逻辑：用所在屏幕的 devicePixelRatio 换算
        from PySide6.QtCore import QPoint

        for screen in QGuiApplication.screens():
            geometry = screen.geometry()
            ratio = screen.devicePixelRatio()
            physical_left = round(geometry.left() * ratio)
            physical_top = round(geometry.top() * ratio)
            physical_width = round(geometry.width() * ratio)
            physical_height = round(geometry.height() * ratio)
            if (
                physical_left <= x < physical_left + physical_width
                and physical_top <= y < physical_top + physical_height
            ):
                return QPoint(
                    geometry.left() + int((x - physical_left) / ratio),
                    geometry.top() + int((y - physical_top) / ratio),
                )
        return QPoint(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x, y = winapi.get_cursor_pos()
        left, top, width, height = self._client_rect
        if not (left <= x < left + width and top <= y < top + height):
            self._message = "点击位置不在目标窗口客户区内，请重新点击。"
            self.update()
            return
        self._message = ""
        self._points.append((x, y))
        self.update()
        if len(self._points) >= 3:
            QTimer.singleShot(120, self.accept)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def run_calibration(parent: QWidget, target: WindowInfo) -> CalibrationSet | None:
    """显示校准遮罩；成功返回坐标集合，取消/失败返回 None。"""
    try:
        left, top, width, height = winapi.get_client_rect_screen(target.hwnd)
    except OSError as exc:
        QMessageBox.critical(parent, "无法校准", f"读取目标客户区失败：{exc}")
        return None
    if width < 50 or height < 50:
        QMessageBox.critical(parent, "无法校准", "目标客户区尺寸异常，请还原窗口后重试。")
        return None

    answer = QMessageBox.question(
        parent,
        "开始校准",
        "校准顺序：账号输入框 → 密码输入框 → 登录按钮。\n\n"
        "点击“是”后主窗口会隐藏，请确保目标登录器窗口完整可见；"
        "遮罩上的点击只记录坐标，不会传给登录器。",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if answer != QMessageBox.Yes:
        return None

    focus = winapi.focus_window(target.hwnd, timeout_ms=1000)
    if not focus.ok:
        QMessageBox.warning(
            parent,
            "无法激活登录器",
            focus.message + "\n\n请先手动切换到登录器窗口，再回到本工具点击“校准”。",
        )
        return None

    virtual = QRect()
    for screen in QGuiApplication.screens():
        virtual = virtual.united(screen.geometry())
    if virtual.isNull():
        virtual = QRect(0, 0, 1920, 1080)

    overlay = CalibrationOverlay((left, top, width, height), virtual, None)
    overlay.setWindowModality(Qt.ApplicationModal)
    parent.hide()
    QGuiApplication.processEvents()
    time.sleep(0.35)
    try:
        result = overlay.exec()
    finally:
        parent.show()
        parent.raise_()
        parent.activateWindow()

    if result != QDialog.Accepted or len(overlay.points) != 3:
        LOGGER.info("校准已取消")
        return None

    try:
        new_left, new_top, new_width, new_height = winapi.get_client_rect_screen(target.hwnd)
    except OSError as exc:
        QMessageBox.critical(parent, "校准失败", f"重新读取目标客户区失败：{exc}")
        return None
    if abs(new_width - width) > 2 or abs(new_height - height) > 2:
        QMessageBox.warning(
            parent,
            "校准失败",
            f"校准期间窗口尺寸发生变化（{width}x{height} → {new_width}x{new_height}），请重新校准。",
        )
        return None
    if abs(new_left - left) > 2 or abs(new_top - top) > 2:
        QMessageBox.warning(
            parent,
            "校准失败",
            "校准期间窗口位置发生变化，坐标可能不可靠，请重新校准。",
        )
        return None

    points = []
    for screen_x, screen_y in overlay.points:
        rel_x = screen_x - new_left
        rel_y = screen_y - new_top
        if not (0 <= rel_x < new_width and 0 <= rel_y < new_height):
            QMessageBox.warning(parent, "校准失败", "有坐标落在客户区之外，请重新校准。")
            return None
        points.append(
            CalibrationPoint(x=rel_x, y=rel_y, client_w=new_width, client_h=new_height)
        )
    if len({(p.x, p.y) for p in points}) < 3:
        QMessageBox.warning(parent, "校准失败", "三个点击位置过于接近，请重新校准。")
        return None

    calibration = CalibrationSet(account=points[0], password=points[1], login=points[2])
    LOGGER.info(
        "校准完成：账号(%d,%d) 密码(%d,%d) 按钮(%d,%d) 客户区 %dx%d",
        points[0].x,
        points[0].y,
        points[1].x,
        points[1].y,
        points[2].x,
        points[2].y,
        new_width,
        new_height,
    )
    return calibration
