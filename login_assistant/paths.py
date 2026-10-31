"""应用数据路径。

默认全部位于 ``%LOCALAPPDATA%\\LoginAssistant``：

* ``config.json``  配置（不含密码）
* ``accounts.json`` 账号记录（密码字段仅含 DPAPI 密文 base64）
* ``logs/app.log`` 运行日志（已脱敏）

测试或便携运行时可用环境变量 ``LOGIN_ASSISTANT_HOME`` 覆盖根目录。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "LoginAssistant"


def app_home() -> Path:
    override = os.environ.get("LOGIN_ASSISTANT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".login_assistant"


def config_path() -> Path:
    return app_home() / "config.json"


def accounts_path() -> Path:
    return app_home() / "accounts.json"


def logs_dir() -> Path:
    return app_home() / "logs"


def log_path() -> Path:
    return logs_dir() / "app.log"


def ensure_app_dirs() -> Path:
    root = app_home()
    root.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    return root
