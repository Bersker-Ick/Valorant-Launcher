from __future__ import annotations

import unittest

from login_assistant.core import winapi
from login_assistant.core.automation import (
    AutomationError,
    _choose_login_button,
    _read_account_length,
    _require_foreground,
    _validate_control_under_point,
    _validate_point_on_target,
)
from login_assistant.core.models import WindowInfo
from login_assistant.core.uia import ElementInfo, Rect


class FakeElement:
    def __init__(self, name: str, rect: Rect, *, password: bool = False) -> None:
        self.name = name
        self.rect = rect
        self._password = password
        self.value_result = ""
        self.native = 0

    @property
    def is_password(self) -> bool:
        return self._password

    @property
    def native_window_handle(self) -> int:
        return self.native

    def value(self) -> str | None:
        if self._password:
            return None
        return self.value_result


class AutomationHelperTest(unittest.TestCase):
    def test_read_account_length(self) -> None:
        element = FakeElement("account", Rect(0, 0, 10, 10))
        element.value_result = "hello"
        self.assertEqual(_read_account_length(element), 5)
        element.value_result = ""
        self.assertEqual(_read_account_length(element), 0)

    def test_password_never_read(self) -> None:
        element = FakeElement("password", Rect(0, 0, 10, 10), password=True)
        element.value_result = "secret"
        self.assertIsNone(_read_account_length(element))
        self.assertIsNone(_read_account_length(None))

    def test_choose_named_button_below_password(self) -> None:
        password = Rect(100, 100, 300, 130)
        toolbar = FakeElement("登录", Rect(100, 10, 200, 40))
        submit = FakeElement("登录", Rect(100, 150, 200, 190))
        self.assertIs(_choose_login_button([toolbar, submit], password), submit)

    def test_toolbar_only_not_clicked(self) -> None:
        password = Rect(100, 100, 300, 130)
        toolbar = FakeElement("登录", Rect(100, 10, 200, 40))
        self.assertIsNone(_choose_login_button([toolbar], password))

    def test_unnamed_single_button_below(self) -> None:
        password = Rect(100, 100, 300, 130)
        submit = FakeElement("OK", Rect(100, 145, 220, 180))
        self.assertIs(_choose_login_button([submit], password), submit)

    def test_unnamed_far_button_not_clicked(self) -> None:
        password = Rect(100, 100, 300, 130)
        far = FakeElement("Help", Rect(100, 900, 220, 940))
        self.assertIsNone(_choose_login_button([far], password))

    def test_point_validation_rejects_other_window(self) -> None:
        original = winapi.window_at_point
        try:
            target = WindowInfo(hwnd=10, title="Launcher", class_name="Chrome_WidgetWin_1", pid=100)
            winapi.window_at_point = lambda _x, _y: winapi.PointWindowInfo(  # type: ignore[assignment]
                11, 11, "Chrome_WidgetWin_1",
                WindowInfo(hwnd=11, title="Other", class_name="Chrome_WidgetWin_1", pid=200),
            )
            with self.assertRaises(AutomationError) as ctx:
                _validate_point_on_target(10, (5, 5), "账号框", [])
            self.assertEqual(ctx.exception.code, "point_not_on_target")
            winapi.window_at_point = lambda _x, _y: winapi.PointWindowInfo(  # type: ignore[assignment]
                12, 10, "Edit", target,
            )
            _validate_point_on_target(10, (5, 5), "账号框", [])
        finally:
            winapi.window_at_point = original  # type: ignore[assignment]

    def test_uia_point_control_validation(self) -> None:
        info = ElementInfo(
            control_type=50000,
            name="登录",
            automation_id="",
            class_name="Button",
            rect=Rect(0, 0, 10, 10),
            is_password=False,
            is_enabled=True,
            is_offscreen=False,
            process_id=1,
            has_keyboard_focus=False,
        )

        class FakeElement:
            def info(self) -> ElementInfo:
                return info

        class FakeSession:
            def element_from_point(self, _x: int, _y: int) -> FakeElement:
                return FakeElement()

        with self.assertRaises(AutomationError) as ctx:
            _validate_control_under_point(FakeSession(), (5, 5), "account", "账号框", [])  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "point_wrong_control")
        # 登录按钮点落在 Button 上是合法的
        _validate_control_under_point(FakeSession(), (5, 5), "login", "登录按钮", [])  # type: ignore[arg-type]

    def test_foreground_matches_root(self) -> None:
        original_fg = winapi.get_foreground_window
        original_root = winapi.get_root_window
        try:
            winapi.get_foreground_window = lambda: 20  # type: ignore[assignment]
            winapi.get_root_window = lambda hwnd: 10 if hwnd == 20 else hwnd  # type: ignore[assignment]
            self.assertTrue(winapi.foreground_matches(10))
            winapi.get_foreground_window = lambda: 30  # type: ignore[assignment]
            winapi.get_root_window = lambda hwnd: 30  # type: ignore[assignment]
            self.assertFalse(winapi.foreground_matches(10))
        finally:
            winapi.get_foreground_window = original_fg  # type: ignore[assignment]
            winapi.get_root_window = original_root  # type: ignore[assignment]

    def test_require_foreground_error_has_actual_window(self) -> None:
        original = winapi.ensure_foreground

        class FakeReport:
            ok = False
            recovered = False
            brief = "'Other' class='Chrome_WidgetWin_1' PID=9 hwnd=0x9"
            detail = "foreground stolen"

        try:
            winapi.ensure_foreground = lambda _hwnd, timeout_ms=0: FakeReport()  # type: ignore[assignment]
            with self.assertRaises(AutomationError) as ctx:
                _require_foreground(10, "账号输入", [])
            self.assertEqual(ctx.exception.code, "foreground_lost")
            self.assertIn("Other", str(ctx.exception))
        finally:
            winapi.ensure_foreground = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
