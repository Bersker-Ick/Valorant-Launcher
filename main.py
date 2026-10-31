"""PyInstaller / 开发运行入口。

不能用 ``login_assistant/__main__.py`` 作为 PyInstaller 脚本入口：
它使用包内相对导入，作为顶层脚本运行时 ``__package__`` 为空。
"""

from __future__ import annotations

from login_assistant.app import main

if __name__ == "__main__":
    raise SystemExit(main())
