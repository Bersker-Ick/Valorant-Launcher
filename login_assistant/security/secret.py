"""明文缓冲的尽力覆写工具。

Python 的 ``str``/``bytes`` 不可变，无法真正擦除；因此本工具只接受
``bytearray`` 并在使用后立刻覆写。文档中明确说明这是“尽力而为”。
"""

from __future__ import annotations


def wipe(buf: bytearray | None) -> None:
    if buf is None:
        return
    try:
        for i in range(len(buf)):
            buf[i] = 0
        buf.clear()
    except Exception:  # pragma: no cover
        pass


def to_bytearray(data: str | bytes | bytearray) -> bytearray:
    if isinstance(data, bytearray):
        return data
    if isinstance(data, str):
        return bytearray(data.encode("utf-8"))
    return bytearray(data)
