"""日志初始化与全局异常记录（全部经过脱敏）。

日志文件：``%LOCALAPPDATA%\\LoginAssistant\\logs\\app.log``（滚动 3 份）。
窗口模式下 ``sys.stderr`` 可能为 None，因此控制台 handler 是可选。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

from . import __version__
from .paths import ensure_app_dirs, log_path
from .security.redact import RedactingFilter, RedactingFormatter

_LOGGER_NAME = "login_assistant"
_CONFIGURED = False


def setup_logging(level: str = "INFO", target: Path | None = None) -> Path:
    global _CONFIGURED
    ensure_app_dirs()
    path = target or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if _CONFIGURED and logger.handlers:
        return path

    formatter = RedactingFormatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redactor = RedactingFilter()

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        file_handler = logging.NullHandler()
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    logger.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.addFilter(redactor)
        logger.addHandler(console)

    _CONFIGURED = True
    logger.info("日志初始化：%s", path)
    return path


def get_logger(name: str = "") -> logging.Logger:
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)


def log_startup_banner() -> None:
    logger = get_logger("app")
    logger.info("=== LoginAssistant %s 启动 ===", __version__)
    try:
        from .core import winapi

        logger.info("系统：%s | DPI 感知：%s", winapi.os_version_string(), winapi.set_dpi_awareness())
        logger.info("自身完整性：%s", winapi.self_integrity().label)
        fg = winapi.get_foreground_info(include_integrity=False)
        if fg:
            logger.info("当前前台：%s (0x%X, PID %d)", fg.title, fg.hwnd, fg.pid)
    except Exception as exc:  # pragma: no cover - 环境信息失败不影响启动
        logger.warning("记录系统信息失败：%s", type(exc).__name__)


def install_excepthooks() -> None:
    logger = get_logger("crash")

    def _handle(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕获异常：\n%s", text)

    def _thread_handle(args):  # type: ignore[no-untyped-def]
        text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        logger.critical("线程未捕获异常（%s）：\n%s", getattr(args.thread, "name", "?"), text)

    sys.excepthook = _handle
    try:
        threading.excepthook = _thread_handle
    except Exception:  # pragma: no cover
        pass
