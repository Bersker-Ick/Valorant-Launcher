from __future__ import annotations

import unittest

from login_assistant.core.automation import (
    _choose_login_button,
    _read_account_length,
)
from login_assistant.core.uia import Rect


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


if __name__ == "__main__":
    unittest.main()
