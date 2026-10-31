"""统一的日志脱敏。

原则：代码路径从不把密码传给 logger；本模块是最后一道防线，
对已经格式化好的整条日志（含 traceback）做模式替换。
"""

from __future__ import annotations

import logging
import re

MASK = "***REDACTED***"

# password=xxx / 密码：xxx / "secret": "xxx"
_SECRET_PAIR_RE = re.compile(
    r"""(?ix)
    (?P<key>\b(?:password|passwd|pwd|secret|passphrase|token|api[_-]?key|密码|口令)\b)
    (?P<sep>\s*(?:[:=：]|\bis\b)\s*)
    (?P<quote>["']?)
    (?P<value>[^\s,;}\]"']+)
    (?P=quote)
    """
)


def redact_text(text: str) -> str:
    if not text:
        return text

    def _pair(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('sep')}{MASK}"

    text = _SECRET_PAIR_RE.sub(_pair, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        return redact_text(super().format(record))


class RedactingFilter(logging.Filter):
    """在 record 进入 handler 前先粗粒度替换参数中的键值对。

    注意：当 ``record.args`` 非空时不能改 ``record.msg``，否则 ``%s`` 占位符
    会被替换掉、args 数量对不上，logging 会抛格式化错误。此时只脱敏 args，
    最终格式化结果由 ``RedactingFormatter`` 再兜底。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: redact_text(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(
                        redact_text(a) if isinstance(a, str) else a
                        for a in record.args
                    )
            elif isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
        except Exception:  # pragma: no cover - 永不因脱敏自身失败而丢日志
            pass
        return True
