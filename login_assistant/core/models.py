"""跨模块共享的数据结构（不含任何明文密码字段）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Windows integrity RID -> 可读名称
INTEGRITY_NAMES = {
    0x0000: "不可信 (Untrusted)",
    0x1000: "低 (Low)",
    0x2000: "中 (Medium)",
    0x3000: "高 (High / 管理员)",
    0x4000: "系统 (System)",
    0x5000: "受保护 (Protected)",
}


def integrity_label(rid: int | None) -> str:
    if rid is None:
        return "未知"
    return INTEGRITY_NAMES.get(rid, f"自定义 (0x{rid:04X})")


@dataclass(frozen=True)
class IntegrityInfo:
    rid: int | None
    label: str
    error: int | None = None

    @property
    def known(self) -> bool:
        return self.rid is not None

    def higher_than(self, other: "IntegrityInfo") -> bool:
        if self.rid is None or other.rid is None:
            return False
        return self.rid > other.rid


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    exe: str = ""
    integrity: IntegrityInfo | None = None

    @property
    def hwnd_hex(self) -> str:
        return f"0x{self.hwnd:X}"

    @property
    def integrity_text(self) -> str:
        return self.integrity.label if self.integrity else "未知"

    @property
    def exe_name(self) -> str:
        if not self.exe:
            return "未知"
        return self.exe.rsplit("\\", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "class_name": self.class_name,
            "pid": self.pid,
            "exe": self.exe,
            "integrity_rid": self.integrity.rid if self.integrity else None,
        }


@dataclass(frozen=True)
class CalibrationPoint:
    """相对目标窗口客户区左上角的物理像素坐标。"""

    x: int
    y: int
    client_w: int
    client_h: int

    def to_dict(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "client_w": self.client_w,
            "client_h": self.client_h,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CalibrationPoint | None":
        if not isinstance(data, dict):
            return None
        try:
            point = cls(
                x=int(data["x"]),
                y=int(data["y"]),
                client_w=int(data["client_w"]),
                client_h=int(data["client_h"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not (0 <= point.x < max(1, point.client_w)):
            return None
        if not (0 <= point.y < max(1, point.client_h)):
            return None
        return point


@dataclass
class CalibrationSet:
    account: CalibrationPoint | None = None
    password: CalibrationPoint | None = None
    login: CalibrationPoint | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.account and self.password and self.login)

    @property
    def client_size(self) -> tuple[int, int] | None:
        for point in (self.account, self.password, self.login):
            if point:
                return (point.client_w, point.client_h)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict() if self.account else None,
            "password": self.password.to_dict() if self.password else None,
            "login": self.login.to_dict() if self.login else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CalibrationSet":
        result = cls()
        if not isinstance(data, dict):
            return result
        result.account = CalibrationPoint.from_dict(data.get("account"))
        result.password = CalibrationPoint.from_dict(data.get("password"))
        result.login = CalibrationPoint.from_dict(data.get("login"))
        return result


@dataclass(frozen=True)
class ManualTarget:
    """手动选定的目标窗口签名（HWND 会变，保存签名用于下次重找）。"""

    title: str
    class_name: str
    exe: str = ""

    def matches(self, window: WindowInfo) -> bool:
        return (
            window.title == self.title
            and window.class_name == self.class_name
        )

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "class_name": self.class_name, "exe": self.exe}

    @classmethod
    def from_dict(cls, data: Any) -> "ManualTarget | None":
        if not isinstance(data, dict):
            return None
        title = str(data.get("title") or "")
        class_name = str(data.get("class_name") or "")
        if not title and not class_name:
            return None
        return cls(title=title, class_name=class_name, exe=str(data.get("exe") or ""))


@dataclass(frozen=True)
class AccountRecord:
    id: str
    name: str
    account: str
    secret_b64: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "account": self.account,
            "secret": self.secret_b64,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "AccountRecord | None":
        if not isinstance(data, dict):
            return None
        try:
            record = cls(
                id=str(data["id"]),
                name=str(data["name"]),
                account=str(data["account"]),
                secret_b64=str(data["secret"]),
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not record.id or not record.name or not record.account or not record.secret_b64:
            return None
        return record

    @property
    def display_password(self) -> str:
        # 固定长度，不泄露真实密码长度
        return "••••••••"
