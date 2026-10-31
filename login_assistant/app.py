"""应用入口。"""

from __future__ import annotations

import logging
import os
import sys
import time

from . import __version__


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    if sys.platform != "win32":
        print("登录助手仅支持 Windows 10/11。", file=sys.stderr)
        return 2

    raw_argv = list(argv if argv is not None else sys.argv)
    smoke_test = "--smoke-test" in raw_argv
    if smoke_test:
        raw_argv = [item for item in raw_argv if item != "--smoke-test"]
        if "LOGIN_ASSISTANT_HOME" not in os.environ:
            import tempfile

            os.environ["LOGIN_ASSISTANT_HOME"] = tempfile.mkdtemp(prefix="la_smoke_")

    # DPI 感知必须在任何窗口（包括 Qt 的）创建之前设置。
    from .core import winapi

    dpi_mode = winapi.set_dpi_awareness()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    try:
        from PySide6.QtCore import (
            QCoreApplication,
            QLockFile,
            Qt,
            QtMsgType,
            QTimer,
            qInstallMessageHandler,
        )
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(
            "缺少 PySide6。请先运行：py -3.13 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 3

    from .config import load_config
    from .core.store import AccountStore
    from .logging_setup import install_excepthooks, log_startup_banner, setup_logging
    from .paths import app_home, ensure_app_dirs
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    ensure_app_dirs()
    config, config_warnings = load_config()
    log_file = setup_logging(config.log_level)
    install_excepthooks()

    QCoreApplication.setOrganizationName("LoginAssistant")
    QCoreApplication.setApplicationName("LoginAssistant")
    QCoreApplication.setApplicationVersion(__version__)
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(raw_argv)
    app.setApplicationDisplayName("登录助手")
    apply_theme(app)

    from .ui.icon import app_icon

    icon = app_icon()
    app.setWindowIcon(icon)

    _base_excepthook = sys.excepthook

    def _gui_excepthook(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
        try:
            _base_excepthook(exc_type, exc_value, exc_tb)
        except Exception:
            pass
        try:
            QMessageBox.critical(
                None,
                "登录助手",
                f"程序遇到未处理的异常（{exc_type.__name__}）。\n"
                "详情已写入脱敏日志；请重启程序。",
            )
        except Exception:
            pass

    sys.excepthook = _gui_excepthook

    def _qt_handler(mode, _context, message):  # type: ignore[no-untyped-def]
        logger = logging.getLogger("login_assistant.qt")
        mapping = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }
        logger.log(mapping.get(mode, logging.INFO), "Qt: %s", message)

    qInstallMessageHandler(_qt_handler)

    lock = QLockFile(str(app_home() / "app.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        QMessageBox.information(None, "登录助手", "登录助手已经在运行。")
        return 0

    log_startup_banner()
    logging.getLogger("login_assistant.app").info(
        "DPI 感知：%s；日志：%s；配置：%s", dpi_mode, log_file, app_home() / "config.json"
    )

    store = AccountStore()
    store.load()
    window = MainWindow(config, store, config_warnings)
    window.setWindowIcon(icon)
    window.show()
    logging.getLogger("login_assistant.app").info(
        "主界面已显示，应用初始化耗时 %.0f ms", (time.perf_counter() - started) * 1000.0
    )
    if smoke_test:
        logging.getLogger("login_assistant.app").info("SMOKE TEST OK")
        print("SMOKE TEST OK")
        QTimer.singleShot(900, app.quit)

    try:
        exit_code = app.exec()
    finally:
        lock.unlock()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
