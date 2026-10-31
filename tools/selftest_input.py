"""命令行记事本自检（阶段 1 验证输入层用）。

用法（在仓库根目录）::

    py -3.13 tools\\selftest_input.py

注意：SendInput 只会发送到当前前台窗口。本脚本会启动记事本并尝试抢焦点；
如果当前前台是全屏游戏/受保护窗口，Windows 可能拒绝切换前台，脚本会明确报错。
正常使用请从「登录助手」界面点击“记事本自检”（那时本程序是前台进程）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from login_assistant.core.input import InputDiagnostics  # noqa: E402
from login_assistant.core.selftest import DEFAULT_TEST_TEXT, run_notepad_selftest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="登录助手 - 记事本 SendInput 自检")
    parser.add_argument("--text", default=DEFAULT_TEST_TEXT, help="测试字符串（默认 Abc123!@#）")
    parser.add_argument("--block-input", action="store_true", help="自检期间调用 BlockInput")
    parser.add_argument("--delay-min", type=int, default=40)
    parser.add_argument("--delay-max", type=int, default=80)
    args = parser.parse_args(argv)

    diagnostics = InputDiagnostics()
    result = run_notepad_selftest(
        test_text=args.text,
        block_input=args.block_input,
        delay_min_ms=args.delay_min,
        delay_max_ms=args.delay_max,
        diagnostics=diagnostics,
    )
    print("=" * 60)
    print(result.headline)
    print(result.detail)
    print(f"期望: {result.expected!r}")
    print(f"实际: {result.actual!r}")
    print(f"事件: {result.events_total} 次，失败 {result.events_failed} 次")
    for step in result.steps:
        print(f"  - {step}")
    print("=" * 60)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
