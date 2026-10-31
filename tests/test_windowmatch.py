from __future__ import annotations

import unittest

from login_assistant.core.models import ManualTarget, WindowInfo
from login_assistant.core.windowmatch import (
    WindowMatchConfig,
    WindowMatchError,
    WindowMatcher,
    resolve_target,
)


def win(title: str, cls: str, pid: int = 1, hwnd: int = 1) -> WindowInfo:
    return WindowInfo(hwnd=hwnd, title=title, class_name=cls, pid=pid)


class WindowMatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = WindowMatcher(WindowMatchConfig())

    def test_riot_client(self) -> None:
        self.assertTrue(self.matcher.matches(win("Riot Client", "RiotClient")))
        self.assertTrue(self.matcher.matches(win("VALORANT", "UnrealWindow")))
        self.assertTrue(self.matcher.matches(win("无畏契约", "Chrome_WidgetWin_1")))

    def test_sourcegit_false_positive(self) -> None:
        # 仓库名恰好是 Valorant-Launcher，但 SourceGit 是 Avalonia 窗口；
        # 默认规则必须避免把源码管理工具当成游戏登录器。
        self.assertFalse(self.matcher.matches(win("Valorant-Launcher", "Avalonia-359cc19a")))
        self.assertFalse(self.matcher.matches(win("Valorant-Launcher", "SunAwtFrame")))

    def test_exclude_own_window(self) -> None:
        self.assertFalse(self.matcher.matches(win("登录助手", "Qt5152QWindowIcon")))
        self.assertFalse(self.matcher.matches(win("Login Assistant", "Qt5152QWindowIcon")))

    def test_require_both_false(self) -> None:
        matcher = WindowMatcher(WindowMatchConfig(require_both=False))
        self.assertTrue(matcher.matches(win("Riot Client", "NotAThing")))
        self.assertTrue(matcher.matches(win("Whatever", "RiotClient")))

    def test_invalid_regex(self) -> None:
        with self.assertRaises(WindowMatchError):
            WindowMatcher(WindowMatchConfig(title_regex="["))

    def test_resolve_manual_first(self) -> None:
        manual = ManualTarget("My Launcher", "MyClass")
        windows = [
            win("My Launcher", "MyClass", hwnd=10),
            win("Riot Client", "RiotClient", hwnd=20),
        ]
        match = resolve_target(windows, self.matcher, manual)
        self.assertEqual(match.source, "manual")
        self.assertEqual(match.window.hwnd, 10)

    def test_resolve_auto(self) -> None:
        windows = [
            win("Notepad", "Notepad", hwnd=1),
            win("Riot Client", "RiotClient", hwnd=2),
        ]
        match = resolve_target(windows, self.matcher, None)
        self.assertEqual(match.source, "auto")
        self.assertEqual(match.window.hwnd, 2)

    def test_resolve_none(self) -> None:
        match = resolve_target([win("Notepad", "Notepad")], self.matcher, None)
        self.assertIsNone(match.window)
        self.assertEqual(match.source, "none")


if __name__ == "__main__":
    unittest.main()
