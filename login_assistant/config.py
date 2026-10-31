"""配置读写（%LOCALAPPDATA%\\LoginAssistant\\config.json）。

配置中**不含任何密码**；只保存匹配规则、延时、调试开关、校准坐标、
手动目标签名和上次选中的账号 ID。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.models import CalibrationSet, ManualTarget
from .core.windowmatch import WindowMatchConfig, WindowMatchError
from .paths import config_path, ensure_app_dirs

CONFIG_VERSION = 1


class ConfigError(ValueError):
    pass


@dataclass
class InputSettings:
    delay_min_ms: int = 40
    delay_max_ms: int = 80
    block_input: bool = False
    auto_enter: bool = True
    input_only_no_click: bool = False
    verify_wait_ms: int = 3500
    retry_cooldown_ms: int = 1200
    focus_timeout_ms: int = 800
    max_attempts: int = 2  # 最多 1 次自动重试

    def to_dict(self) -> dict[str, Any]:
        return {
            "delay_min_ms": self.delay_min_ms,
            "delay_max_ms": self.delay_max_ms,
            "block_input": self.block_input,
            "auto_enter": self.auto_enter,
            "input_only_no_click": self.input_only_no_click,
            "verify_wait_ms": self.verify_wait_ms,
            "retry_cooldown_ms": self.retry_cooldown_ms,
            "focus_timeout_ms": self.focus_timeout_ms,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, data: object) -> "InputSettings":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg
        for name in ("delay_min_ms", "delay_max_ms", "verify_wait_ms", "retry_cooldown_ms", "focus_timeout_ms", "max_attempts"):
            if isinstance(data.get(name), int):
                setattr(cfg, name, int(data[name]))
        for name in ("block_input", "auto_enter", "input_only_no_click"):
            if isinstance(data.get(name), bool):
                setattr(cfg, name, data[name])
        return cfg

    def normalize(self) -> None:
        self.delay_min_ms = max(0, min(int(self.delay_min_ms), 1000))
        self.delay_max_ms = max(0, min(int(self.delay_max_ms), 1000))
        if self.delay_min_ms > self.delay_max_ms:
            self.delay_min_ms, self.delay_max_ms = self.delay_max_ms, self.delay_min_ms
        self.verify_wait_ms = max(800, min(int(self.verify_wait_ms), 15000))
        self.retry_cooldown_ms = max(300, min(int(self.retry_cooldown_ms), 10000))
        self.focus_timeout_ms = max(100, min(int(self.focus_timeout_ms), 3000))
        self.max_attempts = max(1, min(int(self.max_attempts), 2))


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    window_match: WindowMatchConfig = field(default_factory=WindowMatchConfig)
    input: InputSettings = field(default_factory=InputSettings)
    calibration: CalibrationSet = field(default_factory=CalibrationSet)
    manual_target: ManualTarget | None = None
    last_selected_id: str | None = None
    window_geometry_b64: str = ""
    log_level: str = "INFO"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "window_match": self.window_match.to_dict(),
            "input": self.input.to_dict(),
            "calibration": self.calibration.to_dict(),
            "manual_target": self.manual_target.to_dict() if self.manual_target else None,
            "last_selected_id": self.last_selected_id,
            "window_geometry_b64": self.window_geometry_b64,
            "log_level": self.log_level,
        }

    @classmethod
    def from_dict(cls, data: object) -> "AppConfig":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg
        if isinstance(data.get("version"), int):
            cfg.version = data["version"]
        cfg.window_match = WindowMatchConfig.from_dict(data.get("window_match"))
        cfg.input = InputSettings.from_dict(data.get("input"))
        cfg.calibration = CalibrationSet.from_dict(data.get("calibration"))
        cfg.manual_target = ManualTarget.from_dict(data.get("manual_target"))
        if isinstance(data.get("last_selected_id"), str):
            cfg.last_selected_id = data["last_selected_id"]
        if isinstance(data.get("window_geometry_b64"), str):
            cfg.window_geometry_b64 = data["window_geometry_b64"]
        if isinstance(data.get("log_level"), str):
            cfg.log_level = data["log_level"].upper()
        return cfg

    def normalize(self) -> None:
        self.version = CONFIG_VERSION
        self.window_match.validate()
        self.input.normalize()
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            self.log_level = "INFO"


def load_config(path: Path | None = None) -> tuple[AppConfig, list[str]]:
    """返回 (配置, 警告列表)。损坏的配置会备份后用默认值。"""
    ensure_app_dirs()
    target = path or config_path()
    warnings: list[str] = []
    if not target.exists():
        return AppConfig(), warnings
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        backup = _backup_corrupt(target)
        warnings.append(
            f"配置文件无法读取（{type(exc).__name__}），已备份到 {backup.name if backup else '无'}，使用默认配置"
        )
        return AppConfig(), warnings
    if not isinstance(data, dict):
        backup = _backup_corrupt(target)
        warnings.append(f"配置文件格式无效，已备份到 {backup.name if backup else '无'}，使用默认配置")
        return AppConfig(), warnings
    version = data.get("version")
    if isinstance(version, int) and version > CONFIG_VERSION:
        warnings.append(
            f"配置文件版本 {version} 高于本程序支持的 {CONFIG_VERSION}，已按兼容模式读取；"
            "建议升级程序，避免覆盖新配置"
        )
    cfg = AppConfig.from_dict(data)
    try:
        cfg.normalize()
    except WindowMatchError as exc:
        warnings.append(f"窗口匹配正则无效（{exc}），已恢复默认规则")
        cfg.window_match = WindowMatchConfig()
        cfg.normalize()
    return cfg, warnings


def _backup_corrupt(path: Path) -> Path | None:
    if not path.exists():
        return None
    import time

    backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        os.replace(path, backup)
        return backup
    except OSError:
        return None


def save_config(config: AppConfig, path: Path | None = None) -> None:
    ensure_app_dirs()
    target = path or config_path()
    config.normalize()
    payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
