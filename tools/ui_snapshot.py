"""开发用：离屏渲染主窗口截图（不会在桌面显示窗口）。

用法::

    set QT_QPA_PLATFORM=offscreen
    py -3.13 tools\\ui_snapshot.py out.png
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("LOGIN_ASSISTANT_HOME", tempfile.mkdtemp(prefix="la_ui_"))

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from login_assistant.config import AppConfig  # noqa: E402
from login_assistant.core.models import ManualTarget  # noqa: E402
from login_assistant.core.store import AccountStore  # noqa: E402
from login_assistant.logging_setup import setup_logging  # noqa: E402
from login_assistant.ui.icon import app_icon  # noqa: E402
from login_assistant.ui.main_window import MainWindow  # noqa: E402
from login_assistant.ui.theme import apply_theme  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_snapshot.png")
    setup_logging("WARNING")
    app = QApplication(sys.argv[:1])
    for font_path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        QFontDatabase.addApplicationFont(font_path)
    apply_theme(app)
    app.setWindowIcon(app_icon())
    store = AccountStore()
    store.load()
    if len(store) == 0:
        store.add("主账号", "player@example.com", b"Abc123!@#")
        store.add("小号", "alt-account@example.com", b"Another!Pass9")
        store.add("备用", "backup@example.com", b"Test#2026")
    config = AppConfig()
    # 仅用于离屏截图：把桌面窗口作为“手动目标”，展示已找到状态；不进行任何点击/输入。
    from login_assistant.core import winapi

    for info in winapi.enum_top_windows(include_tool_windows=False):
        if info.class_name == "Progman" and info.title:
            config.manual_target = ManualTarget(
                title=info.title, class_name=info.class_name, exe=info.exe
            )
            break
    window = MainWindow(config, store, [])
    window.resize(1120, 780)
    window.show()
    for _ in range(5):
        app.processEvents()
    pixmap = window.grab()
    pixmap.save(str(out), "PNG")
    print(out)
    window.tabs.setCurrentIndex(1)
    for _ in range(5):
        app.processEvents()
    diag = out.with_name(out.stem + "_diag" + out.suffix)
    window.grab().save(str(diag), "PNG")
    print(diag)
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
