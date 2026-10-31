"""目标窗口匹配规则（标题正则 + 类名正则）。

默认规则刻意保守：标题命中 Riot/Valorant 等关键词，类名必须像
Riot/CEF/Qt 登录器。默认**不**匹配 Avalonia，避免把同名源码管理工具
（例如标题恰好是仓库名的 SourceGit）当成游戏登录器。用户可在设置中修改，
或用手动选窗兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import ManualTarget, WindowInfo


class WindowMatchError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


@dataclass
class WindowMatchConfig:
    title_regex: str = r"(?i)(riot\s*client|valorant|无畏契约|拳头游戏|league\s*client)"
    class_regex: str = r"(?i)(riot|valorant|cef|chrome_widgetwin|qt\d*|applicationframewindow|unrealwindow)"
    exclude_title_regex: str = r"(?i)(登录助手|login\s*assistant)"
    process_regex: str = ""
    require_both: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "title_regex": self.title_regex,
            "class_regex": self.class_regex,
            "exclude_title_regex": self.exclude_title_regex,
            "process_regex": self.process_regex,
            "require_both": self.require_both,
        }

    @classmethod
    def from_dict(cls, data: object) -> "WindowMatchConfig":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg
        if isinstance(data.get("title_regex"), str):
            cfg.title_regex = data["title_regex"]
        if isinstance(data.get("class_regex"), str):
            cfg.class_regex = data["class_regex"]
        if isinstance(data.get("exclude_title_regex"), str):
            cfg.exclude_title_regex = data["exclude_title_regex"]
        if isinstance(data.get("process_regex"), str):
            cfg.process_regex = data["process_regex"]
        if isinstance(data.get("require_both"), bool):
            cfg.require_both = data["require_both"]
        return cfg

    def validate(self) -> None:
        for field, pattern in (
            ("title_regex", self.title_regex),
            ("class_regex", self.class_regex),
            ("exclude_title_regex", self.exclude_title_regex),
            ("process_regex", self.process_regex),
        ):
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                raise WindowMatchError(field, str(exc)) from exc


class WindowMatcher:
    def __init__(self, config: WindowMatchConfig) -> None:
        self.config = config
        config.validate()
        self._title = re.compile(config.title_regex) if config.title_regex else None
        self._class = re.compile(config.class_regex) if config.class_regex else None
        self._exclude = (
            re.compile(config.exclude_title_regex) if config.exclude_title_regex else None
        )
        self._process = (
            re.compile(config.process_regex) if config.process_regex else None
        )

    def matches(self, window: WindowInfo) -> bool:
        if self._exclude and (
            self._exclude.search(window.title) or self._exclude.search(window.class_name)
        ):
            return False
        if self._process and not self._process.search(window.exe or ""):
            return False
        title_ok = bool(self._title and self._title.search(window.title))
        class_ok = bool(self._class and self._class.search(window.class_name))
        if self._title is None and self._class is None:
            return False
        if self.config.require_both:
            if self._title is not None and not title_ok:
                return False
            if self._class is not None and not class_ok:
                return False
            return True
        return title_ok or class_ok

    def filter(self, windows: Iterable[WindowInfo]) -> list[WindowInfo]:
        return [window for window in windows if self.matches(window)]


@dataclass
class TargetMatch:
    window: WindowInfo | None
    source: str  # "manual" | "auto" | "none"
    candidates: list[WindowInfo]
    note: str = ""


def resolve_target(
    windows: list[WindowInfo],
    matcher: WindowMatcher,
    manual: ManualTarget | None,
) -> TargetMatch:
    """优先手动签名，其次正则；多候选时优先当前前台窗口。"""
    if manual is not None:
        manual_matches = [window for window in windows if manual.matches(window)]
        if manual_matches:
            return TargetMatch(manual_matches[0], "manual", manual_matches)

    candidates = matcher.filter(windows)
    if not candidates:
        return TargetMatch(None, "none", [], "没有窗口匹配当前规则")
    foreground = 0
    try:
        from . import winapi

        foreground = winapi.get_foreground_window()
    except Exception:
        pass
    for window in candidates:
        if window.hwnd == foreground:
            return TargetMatch(window, "auto", candidates)
    return TargetMatch(candidates[0], "auto", candidates)


def public_window_rows(windows: Iterable[WindowInfo]) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for window in windows:
        rows.append(
            (
                window.title,
                window.class_name,
                str(window.pid),
                window.exe_name,
                window.integrity_text,
            )
        )
    return rows
