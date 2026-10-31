"""盲填结果判定。

重要：密码框不可读，所以本工具不能“确认登录成功”。这里只根据可观察的
窗口状态（关闭/标题/按钮启用状态/新增文本）给出**倾向性**结论，并要求用户
最终手动确认。

关键区分：
* SendInput 返回 1 但账号框长度仍为 0 → 目标可能拒绝了模拟输入；
* 出现明确的“密码错误/验证码”文本 → 不再自动重试（避免风控计数）；
* 窗口关闭/按钮禁用 → 可能成功，但仍提示手动确认。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UiSnapshot:
    at: float
    window_exists: bool
    title: str = ""
    minimized: bool = False
    foreground: bool = False
    button_found: bool = False
    button_enabled: bool | None = None
    account_len: int | None = None
    password_focused: bool | None = None
    texts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def new_texts(self) -> tuple[str, ...]:
        return self.texts


@dataclass(frozen=True)
class Verdict:
    code: str
    headline: str
    detail: str
    retry_allowed: bool
    severity: str  # info | success | warning | error
    manual_only: bool = True
    error_texts: tuple[str, ...] = field(default_factory=tuple)


CREDENTIAL_KEYWORDS = (
    "密码错误",
    "密码不正确",
    "账号或密码",
    "帐号或密码",
    "用户名或密码",
    "账号不存在",
    "帐号不存在",
    "incorrect password",
    "invalid password",
    "invalid credentials",
    "wrong password",
    "incorrect username",
    "account not found",
)

CHALLENGE_KEYWORDS = (
    "验证码",
    "二次验证",
    "两步验证",
    "双重验证",
    "人机验证",
    "安全验证",
    "captcha",
    "verification code",
    "two-factor",
    "2fa",
    "authenticator",
)

GENERIC_ERROR_KEYWORDS = (
    "登录失败",
    "登陆失败",
    "认证失败",
    "发生错误",
    "未知错误",
    "网络错误",
    "连接失败",
    "请重试",
    "login failed",
    "sign in failed",
    "something went wrong",
    "error",
    "failed",
)

SUCCESS_KEYWORDS = (
    "登录成功",
    "登陆成功",
    "欢迎",
    "正在进入",
    "success",
    "welcome",
)


def new_texts(before: UiSnapshot, after: UiSnapshot) -> tuple[str, ...]:
    old = set(before.texts)
    return tuple(text for text in after.texts if text and text not in old)


def _matches(texts: tuple[str, ...], keywords: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for text in texts:
        lowered = text.casefold()
        if any(keyword.casefold() in lowered for keyword in keywords):
            result.append(text)
    return tuple(result)


def classify(
    before: UiSnapshot,
    after: UiSnapshot,
    *,
    expected_account_len: int | None,
    debug_input_only: bool = False,
) -> Verdict:
    if debug_input_only:
        return Verdict(
            code="debug_input_only",
            headline="仅输入模式完成",
            detail="已输入账号与密码，但按调试开关未点击登录按钮。请手动确认输入是否正确。",
            retry_allowed=False,
            severity="info",
        )

    if not after.window_exists:
        return Verdict(
            code="window_closed",
            headline="登录器窗口已关闭",
            detail=(
                "窗口在提交后关闭，可能已进入游戏，也可能是登录器退出/崩溃。"
                "请手动确认结果；本工具不会再次自动提交。"
            ),
            retry_allowed=False,
            severity="warning",
        )

    if after.minimized:
        return Verdict(
            code="window_minimized",
            headline="登录器被最小化",
            detail="窗口在提交后被最小化，无法继续观察。请手动还原并确认。",
            retry_allowed=False,
            severity="warning",
        )

    fresh = new_texts(before, after)
    credential = _matches(fresh, CREDENTIAL_KEYWORDS)
    if credential:
        return Verdict(
            code="credential_error",
            headline="疑似账号或密码错误",
            detail=(
                "登录器出现了密码/账号错误提示。按风控策略不再自动重试，"
                "请手动核对账号密码后重试。"
            ),
            retry_allowed=False,
            severity="error",
            error_texts=credential,
        )

    challenge = _matches(fresh, CHALLENGE_KEYWORDS)
    if challenge:
        return Verdict(
            code="challenge_required",
            headline="需要验证码 / 二次验证",
            detail="登录器要求人机验证或二次验证，请手动完成。本工具不会绕过验证。",
            retry_allowed=False,
            severity="warning",
            error_texts=challenge,
        )

    success = _matches(fresh, SUCCESS_KEYWORDS)
    if success:
        return Verdict(
            code="success_text",
            headline="出现成功/欢迎提示",
            detail="界面出现成功类文本，仍请手动确认是否已进入游戏。",
            retry_allowed=False,
            severity="success",
            error_texts=success,
        )

    generic = _matches(fresh, GENERIC_ERROR_KEYWORDS)
    if generic:
        return Verdict(
            code="login_error",
            headline="登录器返回错误提示",
            detail="出现新的错误文本；可能是网络/服务端问题。最多允许自动重试 1 次。",
            retry_allowed=True,
            severity="warning",
            error_texts=generic,
        )

    if before.button_found and before.button_enabled is True and after.button_enabled is False:
        return Verdict(
            code="progress_button_disabled",
            headline="登录按钮已变为禁用",
            detail=(
                "按钮禁用通常表示正在提交/加载。本工具不会据此断言成功，"
                "请等待并手动确认。"
            ),
            retry_allowed=False,
            severity="info",
        )

    if before.title and after.title and before.title != after.title:
        return Verdict(
            code="title_changed",
            headline="窗口标题已变化",
            detail="登录器标题发生变化，可能正在进入游戏；请手动确认。",
            retry_allowed=False,
            severity="info",
        )

    if expected_account_len is not None and expected_account_len > 0:
        length = after.account_len
        if length == 0:
            return Verdict(
                code="input_not_delivered",
                headline="目标程序可能拒绝了模拟输入",
                detail=(
                    "SendInput 已返回成功，但账号框仍为空，且没有出现密码错误提示。"
                    "这更像输入层被目标拒绝（例如低级键盘钩子检查 LLKHF_INJECTED），"
                    "而不是密码错误。最多自动重试 1 次后转手动确认。"
                ),
                retry_allowed=True,
                severity="error",
            )
        if length is not None and length != expected_account_len:
            return Verdict(
                code="partial_input",
                headline="账号框内容长度与预期不一致",
                detail=(
                    "账号框已有内容，但长度与期望不符；可能丢字、被目标格式化，"
                    "或键盘布局不一致。最多自动重试 1 次。"
                ),
                retry_allowed=True,
                severity="warning",
            )

    if before.title and after.title and before.title != after.title:
        return Verdict(
            code="title_changed",
            headline="窗口标题已变化",
            detail="登录器标题发生变化，可能正在进入游戏；请手动确认。",
            retry_allowed=False,
            severity="info",
        )

    if expected_account_len is None:
        return Verdict(
            code="input_rejected_suspected",
            headline="无法观察到输入结果",
            detail=(
                "UIA 不可用，无法读取账号框；未观察到按钮/标题/文本变化。"
                "若你确认 SendInput 返回成功，目标程序可能拒绝了模拟输入。"
            ),
            retry_allowed=True,
            severity="warning",
        )

    return Verdict(
        code="uncertain",
        headline="提交后没有明显变化",
        detail=(
            "没有检测到错误文本、按钮禁用或窗口变化。可能密码错误但提示延迟，"
            "也可能登录器忽略了输入。按策略最多自动重试 1 次，之后请手动确认。"
        ),
        retry_allowed=True,
        severity="warning",
    )
