"""登录自动化编排：窗口校验 → 焦点 → UIA/校准定位 → SendInput → 盲填判定。

安全边界：
* 只使用公开 Win32/UIA API，不注入、不 hook、不读写其它进程内存；
* 密码只在 Worker 线程内以 bytearray 短暂存在，输入完立即覆写；
* 日志不记录账号/密码/密码框内容；
* 结果只做“倾向性”判定，最终必须由用户手动确认（密码框不可读）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import winapi
from .input import InputDiagnostics, InputSender, SendInputFailure
from .keymap import UnsupportedCharacterError, describe_unsupported, is_typeable_bytes
from .models import CalibrationSet, WindowInfo
from .uia import Element, UiaError, UiaSession
from .verify import (
    CHALLENGE_KEYWORDS,
    CREDENTIAL_KEYWORDS,
    UiSnapshot,
    Verdict,
    classify,
)
from ..security.secret import wipe

LOGGER = logging.getLogger("login_assistant.core.automation")

LOGIN_BUTTON_KEYWORDS = (
    "登录",
    "登入",
    "登陆",
    "login",
    "log in",
    "sign in",
    "signin",
    "进入游戏",
    "开始游戏",
    "启动",
    "进入",
    "submit",
)
PASSWORD_KEYWORDS = ("pass", "pwd", "密码", "口令")
ACCOUNT_KEYWORDS = ("user", "account", "email", "login", "账号", "帐号", "邮箱", "手机", "用户名")
SEARCH_KEYWORDS = ("search", "搜索", "filter", "筛选", "查找")


class AutomationError(RuntimeError):
    def __init__(self, code: str, headline: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.headline = headline
        self.detail = detail


@dataclass(frozen=True)
class AutomationOptions:
    delay_min_ms: int = 40
    delay_max_ms: int = 80
    block_input: bool = False
    auto_enter: bool = True
    input_only_no_click: bool = False
    verify_wait_ms: int = 3500
    retry_cooldown_ms: int = 1200
    focus_timeout_ms: int = 800
    max_attempts: int = 2

    @classmethod
    def from_config(cls, cfg) -> "AutomationOptions":  # type: ignore[no-untyped-def]
        data = cfg.input
        return cls(
            delay_min_ms=data.delay_min_ms,
            delay_max_ms=data.delay_max_ms,
            block_input=data.block_input,
            auto_enter=data.auto_enter,
            input_only_no_click=data.input_only_no_click,
            verify_wait_ms=data.verify_wait_ms,
            retry_cooldown_ms=data.retry_cooldown_ms,
            focus_timeout_ms=data.focus_timeout_ms,
            max_attempts=max(1, min(2, data.max_attempts)),
        )


@dataclass
class AutomationRequest:
    hwnd: int
    account: bytes | bytearray
    password_provider: Callable[[], bytearray]
    options: AutomationOptions = field(default_factory=AutomationOptions)
    calibration: CalibrationSet = field(default_factory=CalibrationSet)
    progress: Callable[[str], None] | None = None
    cancel: threading.Event | None = None


@dataclass
class AutomationReport:
    code: str
    headline: str
    detail: str
    ok_likely: bool
    attempts: int
    steps: list[str]
    events_total: int
    events_failed: int
    verdict: Verdict | None
    duration_s: float
    target_hwnd: int
    target_title: str


@dataclass
class FieldPlan:
    source: str  # uia | calibration
    account_point: tuple[int, int]
    password_point: tuple[int, int]
    login_point: tuple[int, int] | None
    button_name: str
    account_element: Element | None = None
    password_element: Element | None = None
    button_element: Element | None = None
    expected_account_len: int | None = None
    account_hwnd: int = 0
    password_hwnd: int = 0


def _log_step(steps: list[str], progress: Callable[[str], None] | None, message: str) -> None:
    steps.append(message)
    LOGGER.info("%s", message)
    if progress is not None:
        try:
            progress(message)
        except Exception:
            pass


def _cancelled(request: AutomationRequest) -> bool:
    return bool(request.cancel and request.cancel.is_set())


def _sleep(seconds: float, cancel: threading.Event | None) -> bool:
    """可取消等待；返回 False 表示被取消。"""
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            return False
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return not (cancel is not None and cancel.is_set())


def _has_keyword(element: Element, keywords: tuple[str, ...]) -> bool:
    haystack = f"{element.name} {element.automation_id} {element.class_name}".casefold()
    return any(keyword.casefold() in haystack for keyword in keywords)


def _validate_target(hwnd: int) -> WindowInfo:
    info = winapi.get_window_info(hwnd, include_integrity=False)
    if info is None:
        raise AutomationError("window_gone", "目标窗口不存在", "目标窗口已关闭或句柄失效，请刷新后重新选择。")
    if not winapi.USER32.IsWindowVisible(hwnd):
        raise AutomationError("window_invisible", "目标窗口不可见", "目标窗口不可见，请还原窗口后重试。")
    if winapi.is_minimized(hwnd):
        raise AutomationError("window_minimized", "目标窗口已最小化", "目标窗口已最小化，请先还原登录器窗口。")
    if not winapi.is_enabled(hwnd):
        raise AutomationError("window_disabled", "目标窗口处于禁用状态", "目标窗口当前被禁用，无法接收输入。")
    if winapi.is_hung(hwnd):
        raise AutomationError("window_hung", "目标窗口无响应", "目标窗口处于 hung 状态，请等待或重启登录器。")
    return info


def _check_integrity(info: WindowInfo, steps: list[str]) -> None:
    own = winapi.self_integrity()
    target = winapi.get_integrity_level(info.pid)
    _log_step(
        steps,
        None,
        f"完整性级别：本工具={own.label}，目标={target.label}",
    )
    if target.rid is None:
        if target.error == 5:
            _log_step(
                steps,
                None,
                "目标进程受保护（WinError 5），无法读取完整性；"
                "将在每次点击前按实际输入控件进程（如 TASLogin64.exe）校验",
            )
            return
        _log_step(steps, None, "无法读取目标完整性级别；继续尝试，失败时请以管理员运行")
        return
    if own.rid is not None and target.rid > own.rid:
        raise AutomationError(
            "integrity",
            "目标进程完整性级别更高",
            f"目标为 {target.label}，本工具为 {own.label}。\n"
            "Windows UIPI 会阻止低完整性进程向高完整性窗口注入输入。\n"
            "请以管理员身份运行本工具后重试。",
        )


def _choose_login_button(buttons: list[Element], password_rect) -> Element | None:  # type: ignore[no-untyped-def]
    usable = [button for button in buttons if button.rect and button.rect.valid]
    if not usable:
        return None
    named: list[Element] = []
    for button in usable:
        name = button.name.casefold()
        if name and any(keyword.casefold() in name for keyword in LOGIN_BUTTON_KEYWORDS):
            named.append(button)
    below = [
        button
        for button in (named or usable)
        if button.rect
        and button.rect.top >= password_rect.bottom - 12
        and button.rect.left < password_rect.right
        and button.rect.right > password_rect.left
    ]
    if named:
        if below:
            return min(below, key=lambda b: abs(b.rect.top - password_rect.bottom))  # type: ignore[union-attr]
        # 名称匹配但不在密码框下方：可能是工具栏/账号切换按钮，宁可不点
        return None
    if len(below) == 1:
        button = below[0]
        if button.rect and 0 <= button.rect.top - password_rect.bottom <= 500:
            return button
    return None


def _in_virtual_screen(point: tuple[int, int]) -> bool:
    left, top, width, height = winapi.virtual_screen_rect()
    if width <= 0 or height <= 0:
        return True
    return left <= point[0] < left + width and top <= point[1] < top + height


def _read_account_length(element: Element | None) -> int | None:
    """读取非密码账号框的字符长度（绝不读取密码框）。

    优先 UIA ValuePattern；对 Win32 Edit 再退回 WM_GETTEXT 只读消息。
    WM_GETTEXT 不读取进程内存，也不会用于密码框。
    """
    if element is None:
        return None
    try:
        if element.is_password:
            return None
    except Exception:
        return None
    value: str | None = None
    try:
        value = element.value()
        if value:
            return len(value)
    except Exception:
        value = None
    try:
        native = element.native_window_handle
    except Exception:
        native = 0
    if native:
        text = winapi.read_window_text_message(native, max_chars=1024)
        if text is not None:
            return len(text)
    return len(value) if value is not None else None


def _wait_account_length(element: Element | None, timeout_s: float = 0.7) -> int | None:
    deadline = time.monotonic() + timeout_s
    last: int | None = None
    while True:
        length = _read_account_length(element)
        if length is not None:
            last = length
            if length > 0:
                return length
        if time.monotonic() >= deadline:
            return last
        time.sleep(0.12)


def _locate_with_uia(session: UiaSession, hwnd: int, options: AutomationOptions) -> FieldPlan | None:
    edits = [
        element
        for element in session.edits(hwnd)
        if element.rect and element.rect.valid and _in_virtual_screen(element.rect.center)
    ]
    if not edits:
        return None

    plain = [
        element
        for element in edits
        if not element.is_password and not _has_keyword(element, SEARCH_KEYWORDS)
    ]
    passwords = [element for element in edits if element.is_password]
    if not passwords:
        keyword_passwords = [element for element in plain if _has_keyword(element, PASSWORD_KEYWORDS)]
        if keyword_passwords:
            passwords = keyword_passwords
            plain = [element for element in plain if element not in keyword_passwords]

    password: Element | None = None
    account: Element | None = None
    if passwords:
        passwords.sort(key=lambda e: (e.rect.top, e.rect.left))  # type: ignore[union-attr]
        password = passwords[0]
        above = [
            element
            for element in plain
            if element.rect and element.rect.bottom <= password.rect.top + 10  # type: ignore[union-attr]
        ]
        if above:
            account = max(above, key=lambda e: e.rect.bottom)  # type: ignore[union-attr]
        elif plain:
            account = min(
                plain,
                key=lambda e: abs(e.rect.top - password.rect.top),  # type: ignore[union-attr]
            )
    else:
        non_search = [element for element in plain if element.rect]
        non_search.sort(key=lambda e: (e.rect.top, e.rect.left))  # type: ignore[union-attr]
        if len(non_search) >= 2:
            account, password = non_search[0], non_search[1]

    if account is None or password is None or account is password:
        return None
    if not account.rect or not password.rect:
        return None
    if account.rect.center == password.rect.center:
        return None

    buttons = [
        button
        for button in session.buttons(hwnd)
        if button.rect and button.rect.valid and _in_virtual_screen(button.rect.center)
    ]
    button = _choose_login_button(buttons, password.rect)
    if button is None and not options.auto_enter:
        return None

    expected_len: int | None = _read_account_length(account)

    return FieldPlan(
        source="uia",
        account_point=account.rect.center,
        password_point=password.rect.center,
        login_point=button.rect.center if button and button.rect else None,  # type: ignore[union-attr]
        button_name=button.name if button else "",
        account_element=account,
        password_element=password,
        button_element=button,
        expected_account_len=expected_len,
    )


def _calibration_plan(calibration: CalibrationSet, hwnd: int) -> FieldPlan:
    if not calibration.is_complete:
        raise AutomationError(
            "calibration_required",
            "无法定位输入框",
            "UI Automation 没有找到可用的账号框/密码框/登录按钮。\n"
            "请先点击“校准”，依次点击账号框、密码框、登录按钮；或手动选择目标窗口后重试。",
        )
    origin_x, origin_y, width, height = winapi.get_client_rect_screen(hwnd)
    points = [calibration.account, calibration.password, calibration.login]
    for point in points:
        if point is None:
            raise AutomationError("calibration_required", "校准数据不完整", "请重新校准三个坐标。")
        if abs(point.client_w - width) > 2 or abs(point.client_h - height) > 2:
            raise AutomationError(
                "calibration_stale",
                "窗口尺寸已变化",
                f"校准时的客户区为 {point.client_w}x{point.client_h}，当前为 {width}x{height}。\n"
                "请重新校准，避免点击到错误位置。",
            )
        if not (0 <= point.x < width and 0 <= point.y < height):
            raise AutomationError(
                "calibration_stale",
                "校准坐标超出窗口",
                "校准坐标已不在当前客户区内，请重新校准。",
            )
    account = calibration.account
    password = calibration.password
    login = calibration.login
    assert account and password and login
    return FieldPlan(
        source="calibration",
        account_point=(origin_x + account.x, origin_y + account.y),
        password_point=(origin_x + password.x, origin_y + password.y),
        login_point=(origin_x + login.x, origin_y + login.y),
        button_name="校准坐标",
    )


def _snapshot(
    session: UiaSession | None,
    hwnd: int,
    plan: FieldPlan,
) -> UiSnapshot:
    info = winapi.get_window_info(hwnd, include_integrity=False)
    now = time.monotonic()
    if info is None:
        return UiSnapshot(at=now, window_exists=False)
    texts: tuple[str, ...] = ()
    button_found = plan.button_element is not None
    button_enabled: bool | None = None
    account_len: int | None = None
    if session is not None:
        try:
            texts = tuple(session.texts(hwnd, limit=120))
        except Exception:
            texts = ()
        if plan.button_element is not None:
            try:
                button_enabled = plan.button_element.is_enabled
            except Exception:
                button_enabled = None
        elif plan.button_name:
            try:
                for button in session.buttons(hwnd):
                    if button.name == plan.button_name:
                        button_found = True
                        button_enabled = button.is_enabled
                        break
            except Exception:
                pass
        if plan.account_element is not None and not plan.account_element.is_password:
            account_len = _read_account_length(plan.account_element)
        elif plan.account_hwnd:
            text = winapi.read_window_text_message(plan.account_hwnd, max_chars=1024)
            if text is not None:
                account_len = len(text)
    return UiSnapshot(
        at=now,
        window_exists=True,
        title=info.title,
        minimized=winapi.is_minimized(hwnd),
        foreground=winapi.foreground_matches(hwnd),
        button_found=button_found,
        button_enabled=button_enabled,
        account_len=account_len,
        texts=texts,
    )


def _verify_field_focus(element: Element, hwnd: int) -> None:
    try:
        native = element.native_window_handle
    except Exception:
        native = 0
    focus = winapi.target_focus_info(hwnd)
    if native:
        fg = winapi.get_foreground_window()
        native_pid = winapi.get_window_pid(native)
        target_pid = winapi.get_window_pid(hwnd)
        # TASLogin64 等子进程的 Edit 是独立顶层窗口；点击后前台就是它本人。
        if fg == native or (fg and winapi.get_root_window(fg) == native):
            return
        if native_pid == target_pid or winapi.is_descendant_process(native_pid, target_pid):
            native_tid = winapi.get_window_thread_id(native)
            native_focus = winapi.get_focus_hwnd_for_thread(native_tid)
            if native_focus and (
                native_focus == native or winapi.USER32.IsChild(native, native_focus)
            ):
                return
        if focus.focus_hwnd == native:
            return
        raise AutomationError(
            "focus_wrong_field",
            "焦点未落在目标输入框",
            f"UIA 目标控件句柄=0x{native:X}，当前前台=0x{fg:X}，目标线程焦点=0x{focus.focus_hwnd:X}。\n"
            "为避免把密码输入到错误位置，已中止。请重新校准或手动检查界面。",
        )
    try:
        if element.has_keyboard_focus:
            return
    except Exception:
        pass
    if focus.in_target:
        # CEF/自绘控件可能不暴露 HasKeyboardFocus；至少确认焦点在目标窗口内
        return
    raise AutomationError(
        "focus_wrong_field",
        "焦点不在目标窗口",
        f"点击后焦点仍在其它窗口（{focus.detail}），已中止，避免误输入。",
    )


WRONG_CONTROL_TYPES = {
    50000,  # Button
    50002,  # CheckBox
    50005,  # Hyperlink
    50006,  # Image
    50007,  # ListItem
    50013,  # RadioButton
    50020,  # Text
    50024,  # TreeItem
    50029,  # DataItem
}

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_DISABLED = 0x08000000
WS_EX_NOACTIVATE = 0x08000000
ES_PASSWORD = 0x0020
ES_READONLY = 0x0800


def _validate_point_on_target(hwnd: int, point: tuple[int, int], label: str, steps: list[str]) -> winapi.PointWindowInfo:
    """点击前确认坐标属于目标登录器，或其子进程的登录组件。

    腾讯/部分登录器会把真正的输入框放到子进程（例如 TASLogin64.exe）；
    这些 Edit 不是启动器 hwnd 的子窗口，但属于同一个登录流程。只接受
    “目标本身 / 同进程 / 目标后代进程”；无关的上层窗口仍然拒绝。
    """
    under = winapi.window_at_point(point[0], point[1])
    root = under.root
    if root is None:
        raise AutomationError(
            "point_not_on_target",
            "校准坐标下没有窗口",
            f"{label}坐标 {point} 当前没有可命中的窗口。请还原登录器后重新校准。",
        )
    target_pid = winapi.get_window_pid(int(hwnd))
    accepted = root.hwnd == int(hwnd) or root.pid == target_pid
    relationship = "目标窗口"
    if not accepted and winapi.is_descendant_process(root.pid, target_pid):
        accepted = True
        relationship = f"目标子进程 {winapi.process_label(root.pid)}"
    if not accepted:
        actual = (
            f"{root.title!r} class={root.class_name!r} PID={root.pid} "
            f"进程={winapi.process_label(root.pid)} hwnd=0x{root.hwnd:X}"
        )
        raise AutomationError(
            "point_not_on_target",
            "校准坐标当前不在目标窗口上",
            f"{label}坐标 {point} 现在落在 {actual}。\n"
            "这通常是因为登录器被其他窗口遮挡、窗口移动/缩放，或校准点已过期。\n"
            "请关闭遮挡窗口、还原登录器后重新校准；工具不会在这个坐标上乱点。",
        )

    # 实际接收输入的控件可能属于子进程；按它的完整性级别做 UIPI 预检。
    own = winapi.self_integrity()
    control_integrity = winapi.get_integrity_level(root.pid)
    if (
        control_integrity.rid is not None
        and own.rid is not None
        and control_integrity.rid > own.rid
    ):
        raise AutomationError(
            "integrity",
            "实际输入控件进程完整性级别更高",
            f"{label}坐标落在 {winapi.process_label(root.pid)}，其完整性为 {control_integrity.label}，"
            f"本工具为 {own.label}。\n请以管理员身份运行本工具后重试。",
        )
    if control_integrity.rid is None and control_integrity.error == 5:
        _log_step(
            steps,
            None,
            f"{label}坐标所在进程受保护，无法读取完整性；继续尝试，失败时请以管理员运行",
        )

    _log_step(
        steps,
        None,
        f"点击前检查 {label}: 坐标 {point} → {under.child_class or '未知控件'} / "
        f"{relationship} {winapi.process_label(root.pid)} hwnd=0x{root.hwnd:X}",
    )
    return under


def _validate_control_under_point(
    session: UiaSession | None,
    point: tuple[int, int],
    kind: str,
    label: str,
    steps: list[str],
) -> None:
    """只读地检查坐标下的 UIA 控件类型，避免把按钮/链接当成输入框。"""
    if session is None:
        return
    try:
        element = session.element_from_point(point[0], point[1])
        if element is None:
            _log_step(steps, None, f"UIA ElementFromPoint 在 {label} 坐标处没有返回元素")
            return
        info = element.info()
        control_type = info.control_type
        name = (info.name or "").strip()
        _log_step(
            steps,
            None,
            f"点击前 UIA 检查 {label}: 类型={control_type} name={name[:40]!r} class={info.class_name!r}",
        )
        if kind in {"account", "password"}:
            if control_type in WRONG_CONTROL_TYPES:
                raise AutomationError(
                    "point_wrong_control",
                    "校准坐标不在输入框上",
                    f"{label}坐标 {point} 落在控件类型 {control_type}"
                    + (f"（{name[:60]!r}）" if name else "")
                    + "，看起来不是输入框。\n请重新校准该点，避免把账号密码输入到按钮/链接上。",
                )
            if control_type == 50004:  # Edit
                if kind == "account" and info.is_password:
                    raise AutomationError(
                        "point_wrong_control",
                        "账号框坐标落在密码框上",
                        "请重新校准账号框坐标。",
                    )
                if kind == "password" and not info.is_password:
                    _log_step(steps, None, "UIA 未把密码框标记为 IsPassword；按坐标继续，但请留意焦点")

            # 原生 Edit：检查 ES_PASSWORD/ES_READONLY/禁用位。只读密码框无论
            # 怎样 SendInput 都不会接收字符，必须明确告诉用户。
            native = info.native_window_handle
            if native:
                style = int(winapi.USER32.GetWindowLongW(native, GWL_STYLE)) & 0xFFFFFFFF
                exstyle = int(winapi.USER32.GetWindowLongW(native, GWL_EXSTYLE)) & 0xFFFFFFFF
                is_pwd_style = bool(style & ES_PASSWORD)
                readonly = bool(style & ES_READONLY)
                disabled = bool(style & WS_DISABLED) or not info.is_enabled
                noactivate = bool(exstyle & WS_EX_NOACTIVATE)
                _log_step(
                    steps,
                    None,
                    f"{label} 原生样式：ES_PASSWORD={is_pwd_style} readonly={readonly} "
                    f"disabled={disabled} NOACTIVATE={noactivate}",
                )
                if noactivate:
                    _log_step(
                        steps,
                        None,
                        f"{label}带 WS_EX_NOACTIVATE；可能无法通过鼠标/SetForegroundWindow 获得键盘焦点",
                    )
                if disabled:
                    raise AutomationError(
                        "field_disabled",
                        f"{label}处于禁用状态",
                        "输入框当前不可用；请等待登录器加载完成，或重新校准。",
                    )
                if readonly:
                    raise AutomationError(
                        "field_readonly",
                        f"{label}是只读控件",
                        f"{label}（hwnd=0x{native:X}）带 ES_READONLY 样式，模拟键盘无法输入。\n"
                        "这不是输入层失败；请手动填写该字段，或检查登录器是否尚未解锁输入。",
                    )
                if kind == "account" and is_pwd_style:
                    raise AutomationError(
                        "point_wrong_control",
                        "账号框坐标落在密码控件上",
                        "该控件带 ES_PASSWORD 样式，请重新校准账号框。",
                    )
                if kind == "password" and not (is_pwd_style or info.is_password):
                    _log_step(
                        steps,
                        None,
                        "密码控件既没有 ES_PASSWORD 也没有 UIA IsPassword；"
                        "可能是自绘/安全控件，继续尝试但可能拒绝注入",
                    )
        elif kind == "login":
            if control_type in {50004, 50002, 50013}:  # Edit / CheckBox / RadioButton
                raise AutomationError(
                    "point_wrong_control",
                    "登录按钮坐标落在输入控件上",
                    f"登录按钮坐标 {point} 落在控件类型 {control_type}，不是按钮。请重新校准登录按钮。",
                )
    except AutomationError:
        raise
    except Exception as exc:
        _log_step(steps, None, f"UIA 坐标检查失败（{type(exc).__name__}），退回窗口根检查")
        return


def _require_foreground(hwnd: int, phase: str, steps: list[str]) -> None:
    report = winapi.ensure_foreground(hwnd, timeout_ms=1000)
    if not report.ok:
        raise AutomationError(
            "foreground_lost",
            "前台焦点被其他窗口抢占",
            f"{phase}后，当前前台是 {report.brief}。\n"
            f"{report.detail}\n\n"
            "工具已尝试重新聚焦目标但失败。请关闭抢占前台的窗口后重试；"
            "如果目标已经跳转到新窗口，请刷新目标并重新校准。",
        )
    if report.recovered:
        _log_step(steps, None, f"{phase}后前台曾被 {report.brief} 抢占；{report.detail}")


def _click_field(
    sender: InputSender,
    hwnd: int,
    point: tuple[int, int],
    element: Element | None,
    label: str,
    steps: list[str],
    *,
    clicks: int = 1,
    session: UiaSession | None = None,
    kind: str = "field",
) -> int:
    if not _in_virtual_screen(point):
        raise AutomationError(
            "invalid_coordinates",
            "输入框坐标无效",
            f"{label}的坐标 {point} 不在虚拟桌面范围内，可能是窗口已最小化/移动。",
        )
    under = _validate_point_on_target(hwnd, point, label, steps)
    _validate_control_under_point(session, point, kind, label, steps)
    result = sender.click_screen(point[0], point[1], clicks=clicks)
    if not result.ok:
        raise AutomationError("sendinput", "点击目标输入框失败", result.detail)
    time.sleep(0.06)
    report = winapi.ensure_foreground(hwnd, timeout_ms=900)
    if not report.ok:
        raise AutomationError(
            "foreground_lost",
            "前台焦点被其他窗口抢占",
            f"点击{label}后，当前前台是 {report.brief}。\n"
            f"{report.detail}\n\n"
            "工具已尝试重新聚焦目标但失败。请关闭抢占前台的窗口后重试；"
            "如果点击位置不是输入框，请重新校准。",
        )
    if report.recovered:
        _log_step(steps, None, f"点击{label}后前台曾被抢占；{report.detail}")

    expected_hwnd = 0
    if element is not None:
        try:
            expected_hwnd = int(element.native_window_handle or 0)
        except Exception:
            expected_hwnd = 0
    if not expected_hwnd:
        expected_hwnd = int(under.child_hwnd or 0)

    if expected_hwnd and not winapi.control_has_focus(expected_hwnd):
        focus_report = winapi.focus_control(expected_hwnd, timeout_ms=800)
        if not focus_report.ok:
            raise AutomationError(
                "focus_wrong_field",
                "无法把焦点放到目标输入框",
                f"点击{label}后，控件 hwnd=0x{expected_hwnd:X} 没有获得键盘焦点。\n"
                f"{focus_report.message}\n"
                "这通常意味着该控件是只读/自绘/安全控件，或点击被透明层拦截。\n"
                "请重新校准；如果仍失败，请尝试手动填写该字段。",
            )
        _log_step(
            steps,
            None,
            f"点击{label}后焦点未落在目标控件，已强制聚焦 hwnd=0x{expected_hwnd:X}",
        )

    if element is not None:
        try:
            element.set_focus()
            time.sleep(0.04)
        except Exception:
            pass
        _require_foreground(hwnd, f"聚焦{label}", steps)
        _verify_field_focus(element, hwnd)
    else:
        # 校准模式没有 UIA 元素；如果前台是目标本身或目标后代进程
        # （TASLogin64 的 Edit），就认为焦点在登录流程内。
        if not winapi.foreground_matches(hwnd):
            info = winapi.target_focus_info(hwnd)
            if info.focus_hwnd and not info.in_target:
                raise AutomationError(
                    "focus_wrong_field",
                    "焦点不在目标窗口",
                    f"点击{label}后焦点落在其它窗口（{info.detail}），已中止。",
                )
    _log_step(
        steps,
        None,
        f"已点击{label} ({point[0]}, {point[1]})，焦点控件=0x{expected_hwnd:X}"
        if expected_hwnd
        else f"已点击{label} ({point[0]}, {point[1]})",
    )
    return expected_hwnd


def run_login(request: AutomationRequest) -> AutomationReport:
    started = time.monotonic()
    options = request.options
    steps: list[str] = []
    diagnostics = InputDiagnostics()
    sender = InputSender(
        delay_min_ms=options.delay_min_ms,
        delay_max_ms=options.delay_max_ms,
        diagnostics=diagnostics,
    )
    attempts = 0
    target_title = ""
    verdict: Verdict | None = None
    session: UiaSession | None = None
    account_keep = bytearray(request.account)
    try:
        info = _validate_target(request.hwnd)
        target_title = info.title
        sender.hkl = winapi.get_keyboard_layout_for_window(request.hwnd)
        _log_step(steps, request.progress, f"目标窗口：{info.title} (0x{info.hwnd:X}, PID {info.pid})")
        _check_integrity(info, steps)

        if _cancelled(request):
            raise AutomationError("cancelled", "已取消", "用户取消了本次登录。")

        if not is_typeable_bytes(account_keep):
            raise AutomationError(
                "unsupported_chars",
                "账号包含无法模拟的字符",
                describe_unsupported(account_keep) + "\n请手动输入该账号。",
            )

        focus = winapi.focus_window(request.hwnd, timeout_ms=options.focus_timeout_ms)
        _log_step(steps, request.progress, focus.message)
        if not focus.ok:
            raise AutomationError("foreground_failed", "无法激活目标窗口", focus.message)

        try:
            session = UiaSession()
            session.open()
            _log_step(steps, request.progress, "UI Automation 已连接")
        except UiaError as exc:
            if session is not None:
                session.close()
                session = None
            _log_step(steps, request.progress, f"UI Automation 不可用：{exc}")

        while attempts < options.max_attempts:
            attempts += 1
            _log_step(steps, request.progress, f"开始第 {attempts}/{options.max_attempts} 次尝试")
            if _cancelled(request):
                raise AutomationError("cancelled", "已取消", "用户取消了本次登录。")

            focus = winapi.focus_window(request.hwnd, timeout_ms=options.focus_timeout_ms)
            if not focus.ok:
                raise AutomationError("foreground_failed", "无法激活目标窗口", focus.message)

            plan: FieldPlan | None = None
            if session is not None:
                try:
                    plan = _locate_with_uia(session, request.hwnd, options)
                except Exception as exc:
                    _log_step(steps, request.progress, f"UIA 定位异常：{type(exc).__name__}")
                    plan = None
            if plan is None:
                plan = _calibration_plan(request.calibration, request.hwnd)
            _log_step(
                steps,
                request.progress,
                f"定位方式：{'UI Automation' if plan.source == 'uia' else '校准坐标'}"
                + (f"，按钮：{plan.button_name}" if plan.button_name else "，提交方式：Enter"),
            )

            expected_len: int | None = len(account_keep) if plan.account_element is not None else None
            ime = winapi.detach_ime(request.hwnd)
            _log_step(steps, request.progress, ime.detail)
            blocked = False
            password: bytearray | None = None
            account_payload: bytearray | None = None
            attempt_verdict: Verdict | None = None
            baseline: UiSnapshot | None = None
            try:
                if options.block_input:
                    ok, err = winapi.block_input(True)
                    blocked = ok
                    _log_step(
                        steps,
                        request.progress,
                        "BlockInput(True) 成功" if ok else f"BlockInput(True) 失败 (WinError {err})，继续但按键可能被物理输入干扰",
                    )

                try:
                    password = request.password_provider()
                except Exception as exc:
                    raise AutomationError(
                        "password_decrypt",
                        "无法解密保存的密码",
                        f"DPAPI 解密失败（{type(exc).__name__}）。请确认仍是保存该记录的 Windows 用户。",
                    ) from exc
                if not isinstance(password, bytearray):
                    password = bytearray(password)
                if not password:
                    raise AutomationError("password_decrypt", "密码为空", "保存的密码为空，无法自动登录。")
                if not is_typeable_bytes(password):
                    raise AutomationError(
                        "unsupported_chars",
                        "密码包含无法模拟的字符",
                        describe_unsupported(password) + "\n请手动输入密码。",
                    )

                account_payload = bytearray(account_keep)
                baseline = _snapshot(session, request.hwnd, plan)

                plan.account_hwnd = _click_field(
                    sender,
                    request.hwnd,
                    plan.account_point,
                    plan.account_element,
                    "账号框",
                    steps,
                    clicks=3 if plan.source == "uia" else 1,
                    session=session,
                    kind="account",
                )
                if plan.account_hwnd:
                    expected_len = len(account_keep)
                sender.clear_field()
                report = sender.type_bytes(account_payload, cancel=request.cancel.is_set if request.cancel else None)
                if report.aborted:
                    raise AutomationError("cancelled", "已取消", "输入账号时被取消。")
                if report.sent_chars != report.total_chars:
                    raise AutomationError("sendinput", "账号输入不完整", "SendInput 未能发送全部字符。")
                _log_step(steps, request.progress, f"账号输入完成（{report.sent_chars} 个字符）")
                time.sleep(0.10)
                _require_foreground(request.hwnd, "账号输入", steps)

                account_len_after = _wait_account_length(plan.account_element, 0.7)
                if account_len_after is None and plan.account_hwnd:
                    deadline_len = time.monotonic() + 0.7
                    while time.monotonic() < deadline_len:
                        text = winapi.read_window_text_message(plan.account_hwnd, max_chars=1024)
                        if text is not None:
                            account_len_after = len(text)
                            if account_len_after > 0:
                                break
                        time.sleep(0.12)
                if account_len_after is not None:
                    if account_len_after == 0:
                        attempt_verdict = Verdict(
                            code="input_not_delivered",
                            headline="目标程序可能拒绝了模拟输入",
                            detail=(
                                "SendInput 对账号的每次调用都返回成功，但账号框仍为空。"
                                "这更像目标拒绝模拟输入（例如低级键盘钩子检查 LLKHF_INJECTED），"
                                "而不是密码错误。按策略最多重试 1 次。"
                            ),
                            retry_allowed=True,
                            severity="error",
                        )
                    elif expected_len is not None and account_len_after != expected_len:
                        _log_step(
                            steps,
                            request.progress,
                            f"账号框长度 {account_len_after} 与预期 {expected_len} 不一致，继续但将记录风险",
                        )

                if attempt_verdict is None:
                    plan.password_hwnd = _click_field(
                        sender,
                        request.hwnd,
                        plan.password_point,
                        plan.password_element,
                        "密码框",
                        steps,
                        clicks=3 if plan.source == "uia" else 1,
                        session=session,
                        kind="password",
                    )
                    sender.clear_field()
                    password_report = sender.type_bytes(password, cancel=request.cancel.is_set if request.cancel else None)
                    password = None  # type_bytes 已覆写
                    if password_report.aborted:
                        raise AutomationError("cancelled", "已取消", "输入密码时被取消。")
                    if password_report.sent_chars != password_report.total_chars:
                        raise AutomationError("sendinput", "密码输入不完整", "SendInput 未能发送全部字符。")
                    _log_step(steps, request.progress, f"密码输入完成（{password_report.sent_chars} 个字符，内容不记录）")
                    time.sleep(0.10)
                    _require_foreground(request.hwnd, "密码输入", steps)
                    if plan.password_hwnd and not winapi.control_has_focus(plan.password_hwnd):
                        raise AutomationError(
                            "focus_wrong_field",
                            "密码框未保持键盘焦点",
                            f"密码输入后，控件 hwnd=0x{plan.password_hwnd:X} 不再持有焦点；"
                            "密码可能没有进入密码框。请重新校准密码框，或手动输入密码。",
                        )

                    value_len: int | None = None
                    if plan.account_element is not None:
                        try:
                            value_len = _read_account_length(plan.account_element)
                        except Exception:
                            value_len = None
                    elif plan.account_hwnd:
                        text = winapi.read_window_text_message(plan.account_hwnd, max_chars=1024)
                        if text is not None:
                            value_len = len(text)
                    if value_len is not None:
                        _log_step(
                            steps,
                            None,
                            f"密码输入后账号框长度={value_len}（输入账号后为 {account_len_after}）",
                        )
                        if account_len_after is not None and value_len != account_len_after:
                            raise AutomationError(
                                "focus_wrong_field",
                                "密码可能被输入到账号框",
                                "密码输入后账号框长度发生变化，焦点可能未落在密码框。为避免错误提交，已中止。",
                            )

                    if options.input_only_no_click:
                        attempt_verdict = Verdict(
                            code="debug_input_only",
                            headline="仅输入模式完成",
                            detail="已输入账号与密码，但按调试开关未点击登录按钮。请手动确认输入是否正确。",
                            retry_allowed=False,
                            severity="info",
                        )
                        _log_step(steps, request.progress, "仅输入不点击：跳过登录按钮")
                    else:
                        if request.cancel is not None and request.cancel.is_set():
                            raise AutomationError("cancelled", "已取消", "提交前被取消。")
                        if plan.login_point is not None:
                            _validate_point_on_target(request.hwnd, plan.login_point, "登录按钮", steps)
                            _validate_control_under_point(
                                session,
                                plan.login_point,
                                "login",
                                "登录按钮",
                                steps,
                            )
                            _log_step(
                                steps,
                                request.progress,
                                f"点击登录按钮：{plan.button_name or '（未命名）'} ({plan.login_point[0]}, {plan.login_point[1]})",
                            )
                            click = sender.click_screen(*plan.login_point)
                            if not click.ok:
                                raise AutomationError("sendinput", "点击登录按钮失败", click.detail)
                        else:
                            _log_step(steps, request.progress, "点击 Enter 提交")
                            sender.tap_enter()

                        after = _snapshot(session, request.hwnd, plan)
                        deadline = time.monotonic() + max(0.8, options.verify_wait_ms / 1000.0)
                        last = after
                        while time.monotonic() < deadline:
                            if request.cancel is not None and request.cancel.is_set():
                                break
                            if not winapi.is_window_valid(request.hwnd):
                                last = _snapshot(session, request.hwnd, plan)
                                break
                            fresh = _snapshot(session, request.hwnd, plan)
                            last = fresh
                            fresh_new = [text for text in fresh.texts if text not in baseline.texts]  # type: ignore[union-attr]
                            joined = " ".join(fresh_new).casefold()
                            if any(keyword.casefold() in joined for keyword in CREDENTIAL_KEYWORDS + CHALLENGE_KEYWORDS):
                                break
                            time.sleep(0.30)
                        attempt_verdict = classify(
                            baseline,  # type: ignore[arg-type]
                            last,
                            expected_account_len=expected_len,
                            debug_input_only=False,
                        )
                        _log_step(
                            steps,
                            request.progress,
                            f"结果判定：{attempt_verdict.code}（重试允许={attempt_verdict.retry_allowed}）",
                        )
            finally:
                if blocked:
                    ok, err = winapi.block_input(False)
                    _log_step(
                        steps,
                        request.progress,
                        "BlockInput(False) 成功" if ok else f"BlockInput(False) 失败 (WinError {err})",
                    )
                if ime.ok:
                    restored = winapi.restore_ime(ime)
                    _log_step(steps, request.progress, "IME 已恢复" if restored else "IME 恢复失败")
                if password is not None:
                    wipe(password)
                if account_payload is not None:
                    wipe(account_payload)

            if attempt_verdict is None:
                raise AutomationError("unknown", "未得到判定", "内部状态错误：没有产生判定结果。")
            verdict = attempt_verdict

            if verdict.retry_allowed and attempts < options.max_attempts:
                _log_step(steps, request.progress, "按策略自动重试 1 次（不会连续重试）")
                if not _sleep(options.retry_cooldown_ms / 1000.0, request.cancel):
                    raise AutomationError("cancelled", "已取消", "重试等待期间被取消。")
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
                try:
                    session = UiaSession()
                    session.open()
                except UiaError:
                    session = None
                continue
            break

        assert verdict is not None
        detail = verdict.detail
        if verdict.retry_allowed and attempts >= options.max_attempts:
            detail += "\n已执行自动重试上限（最多 1 次），请手动确认并完成后续操作。"
        if verdict.code not in {"success_text", "progress_button_disabled"}:
            detail += "\n本工具是盲填，无法读取密码框，请手动确认最终结果。"
        return AutomationReport(
            code=verdict.code,
            headline=verdict.headline,
            detail=detail,
            ok_likely=verdict.code in {"success_text", "progress_button_disabled"},
            attempts=attempts,
            steps=steps,
            events_total=diagnostics.total_events,
            events_failed=diagnostics.failures,
            verdict=verdict,
            duration_s=time.monotonic() - started,
            target_hwnd=request.hwnd,
            target_title=target_title,
        )
    except AutomationError as exc:
        LOGGER.warning("登录中止：%s（%s）", exc.code, exc.headline)
        return AutomationReport(
            code=exc.code,
            headline=exc.headline,
            detail=exc.detail,
            ok_likely=False,
            attempts=attempts,
            steps=steps,
            events_total=diagnostics.total_events,
            events_failed=diagnostics.failures,
            verdict=None,
            duration_s=time.monotonic() - started,
            target_hwnd=request.hwnd,
            target_title=target_title,
        )
    except SendInputFailure as exc:
        code = "uipi" if exc.winerror == 5 else "sendinput"
        headline = "权限不足（UIPI）" if exc.winerror == 5 else "SendInput 调用失败"
        detail = (
            "SendInput 返回 0 且 GetLastError=5，Windows 完整性级别阻止了输入。\n"
            "请以管理员身份运行本工具后重试。"
            if exc.winerror == 5
            else f"SendInput 失败：{exc}"
        )
        LOGGER.warning("SendInput 失败：code=%s winerror=%s", code, exc.winerror)
        return AutomationReport(
            code=code,
            headline=headline,
            detail=detail,
            ok_likely=False,
            attempts=attempts,
            steps=steps,
            events_total=diagnostics.total_events,
            events_failed=diagnostics.failures,
            verdict=None,
            duration_s=time.monotonic() - started,
            target_hwnd=request.hwnd,
            target_title=target_title,
        )
    except UnsupportedCharacterError as exc:
        return AutomationReport(
            code="unsupported_chars",
            headline="包含无法模拟的字符",
            detail=str(exc) + "\n请手动输入该账号或密码。",
            ok_likely=False,
            attempts=attempts,
            steps=steps,
            events_total=diagnostics.total_events,
            events_failed=diagnostics.failures,
            verdict=None,
            duration_s=time.monotonic() - started,
            target_hwnd=request.hwnd,
            target_title=target_title,
        )
    except Exception as exc:  # 未预期异常不把可能的敏感内容带进消息
        LOGGER.exception("登录流程未预期异常：%s", type(exc).__name__)
        return AutomationReport(
            code="error",
            headline="登录流程发生异常",
            detail=f"未预期异常（{type(exc).__name__}）。详情已写入脱敏日志，请手动确认。",
            ok_likely=False,
            attempts=attempts,
            steps=steps,
            events_total=diagnostics.total_events,
            events_failed=diagnostics.failures,
            verdict=None,
            duration_s=time.monotonic() - started,
            target_hwnd=request.hwnd,
            target_title=target_title,
        )
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        wipe(account_keep)
