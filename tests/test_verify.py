from __future__ import annotations

import unittest

from login_assistant.core.verify import UiSnapshot, classify, new_texts


def snap(**overrides) -> UiSnapshot:  # type: ignore[no-untyped-def]
    data = dict(
        at=0.0,
        window_exists=True,
        title="Riot Client",
        minimized=False,
        foreground=True,
        button_found=True,
        button_enabled=True,
        account_len=0,
        texts=(),
    )
    data.update(overrides)
    return UiSnapshot(**data)


class VerifyTest(unittest.TestCase):
    def test_debug_input_only(self) -> None:
        verdict = classify(snap(), snap(), expected_account_len=4, debug_input_only=True)
        self.assertEqual(verdict.code, "debug_input_only")
        self.assertFalse(verdict.retry_allowed)

    def test_window_closed(self) -> None:
        verdict = classify(snap(), snap(window_exists=False), expected_account_len=4)
        self.assertEqual(verdict.code, "window_closed")
        self.assertFalse(verdict.retry_allowed)

    def test_minimized(self) -> None:
        verdict = classify(snap(), snap(minimized=True), expected_account_len=4)
        self.assertEqual(verdict.code, "window_minimized")
        self.assertFalse(verdict.retry_allowed)

    def test_credential_error_no_retry(self) -> None:
        verdict = classify(
            snap(),
            snap(texts=("账号或密码错误",)),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "credential_error")
        self.assertFalse(verdict.retry_allowed)

    def test_challenge_no_retry(self) -> None:
        verdict = classify(
            snap(),
            snap(texts=("请输入验证码",)),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "challenge_required")
        self.assertFalse(verdict.retry_allowed)

    def test_success_text(self) -> None:
        verdict = classify(
            snap(),
            snap(texts=("登录成功，欢迎回来",)),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "success_text")
        self.assertFalse(verdict.retry_allowed)

    def test_generic_error_can_retry(self) -> None:
        verdict = classify(
            snap(),
            snap(texts=("网络连接失败，请稍后重试",)),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "login_error")
        self.assertTrue(verdict.retry_allowed)

    def test_button_disabled_progress(self) -> None:
        verdict = classify(
            snap(button_enabled=True),
            snap(button_enabled=False),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "progress_button_disabled")
        self.assertFalse(verdict.retry_allowed)

    def test_input_not_delivered(self) -> None:
        verdict = classify(snap(), snap(account_len=0), expected_account_len=4)
        self.assertEqual(verdict.code, "input_not_delivered")
        self.assertTrue(verdict.retry_allowed)

    def test_partial_input(self) -> None:
        verdict = classify(snap(), snap(account_len=2), expected_account_len=4)
        self.assertEqual(verdict.code, "partial_input")
        self.assertTrue(verdict.retry_allowed)

    def test_title_changed(self) -> None:
        verdict = classify(
            snap(title="Riot Client"),
            snap(title="Riot Client - 正在进入"),
            expected_account_len=4,
        )
        self.assertEqual(verdict.code, "title_changed")
        self.assertFalse(verdict.retry_allowed)

    def test_uncertain(self) -> None:
        verdict = classify(snap(), snap(account_len=4), expected_account_len=4)
        self.assertEqual(verdict.code, "uncertain")
        self.assertTrue(verdict.retry_allowed)

    def test_input_rejected_without_uia(self) -> None:
        verdict = classify(snap(), snap(account_len=None), expected_account_len=None)
        self.assertEqual(verdict.code, "input_rejected_suspected")
        self.assertTrue(verdict.retry_allowed)

    def test_new_texts(self) -> None:
        before = snap(texts=("账号", "密码"))
        after = snap(texts=("账号", "密码", "密码错误"))
        self.assertEqual(new_texts(before, after), ("密码错误",))


if __name__ == "__main__":
    unittest.main()
