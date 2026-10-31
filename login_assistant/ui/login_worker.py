"""登录 Worker：所有 Win32/UIA/SendInput 调用都在这个线程内完成。

BlockInput 是线程级的：必须和 SendInput 在同一个线程，且由 finally 解除。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.automation import AutomationRequest, AutomationReport, run_login


class LoginWorker(QThread):
    progress = Signal(str)
    result = Signal(object)

    def __init__(self, request: AutomationRequest) -> None:
        super().__init__()
        self.request = request
        self.request.progress = self.progress.emit

    def run(self) -> None:
        report: AutomationReport
        try:
            report = run_login(self.request)
        except Exception as exc:  # run_login 已兜底，这里仅防线程崩溃
            report = AutomationReport(
                code="worker_crash",
                headline="登录线程崩溃",
                detail=f"登录线程发生未预期异常（{type(exc).__name__}），详情见脱敏日志。",
                ok_likely=False,
                attempts=0,
                steps=[],
                events_total=0,
                events_failed=0,
                verdict=None,
                duration_s=0.0,
                target_hwnd=self.request.hwnd,
                target_title="",
            )
        self.result.emit(report)

    def cancel(self) -> None:
        if self.request.cancel is not None:
            self.request.cancel.set()
