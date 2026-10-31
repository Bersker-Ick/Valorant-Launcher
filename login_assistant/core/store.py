"""账号存储：JSON 文件 + Windows DPAPI 密文。

落盘结构（密码字段只有 base64 密文）::

    {
      "app": "LoginAssistant",
      "version": 1,
      "records": [
        {"id": "...", "name": "主账号", "account": "user@example.com",
         "secret": "AQAAANCMnd8BFdERjHoAwE/Cl+...", "created_at": "...",
         "updated_at": "..."}
      ]
    }

明文密码只在 ``add``/``update``/``decrypt_password`` 的调用栈里短暂存在，
不写日志、不进异常消息；调用方负责对返回的 bytearray 调用 ``wipe``。
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import AccountRecord
from ..paths import accounts_path, ensure_app_dirs
from ..security.dpapi import DPAPIError, decrypt_b64, encrypt_b64
from ..security.secret import wipe

STORE_VERSION = 1
STORE_APP = "LoginAssistant"


class StoreError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_valid_secret_b64(value: str) -> bool:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return False
    return len(raw) > 0


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else accounts_path()
        self._records: list[AccountRecord] = []
        self.warning: str | None = None
        self.read_only = False
        self._loaded = False

    # -- lifecycle ---------------------------------------------------------
    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            backup = self._backup_corrupt()
            self.warning = (
                f"账号文件无法读取（{type(exc).__name__}），"
                f"已备份为 {backup.name if backup else '（备份失败）'}，当前列表为空"
            )
            return
        if not isinstance(data, dict):
            backup = self._backup_corrupt()
            self.warning = f"账号文件格式无效，已备份为 {backup.name if backup else '（备份失败）'}"
            return
        version = data.get("version")
        if isinstance(version, int) and version > STORE_VERSION:
            backup = self._copy_backup("newer")
            self.read_only = True
            self.warning = (
                f"账号文件版本 {version} 高于本程序支持的 {STORE_VERSION}，"
                f"原文件未修改，副本：{backup.name if backup else '（复制失败）'}；"
                "请升级程序后再使用"
            )
            return
        records = data.get("records")
        if not isinstance(records, list):
            backup = self._backup_corrupt()
            self.warning = f"账号文件缺少 records，已备份为 {backup.name if backup else '（备份失败）'}"
            return

        seen: set[str] = set()
        skipped = 0
        for item in records:
            record = AccountRecord.from_dict(item)
            if (
                record is None
                or record.id in seen
                or not _is_valid_secret_b64(record.secret_b64)
            ):
                skipped += 1
                continue
            seen.add(record.id)
            self._records.append(record)
        if skipped:
            self.warning = f"已跳过 {skipped} 条损坏/重复的账号记录（原文件未修改）"

    # -- queries -----------------------------------------------------------
    @property
    def records(self) -> tuple[AccountRecord, ...]:
        self.load()
        return tuple(self._records)

    def get(self, record_id: str) -> AccountRecord | None:
        self.load()
        for record in self._records:
            if record.id == record_id:
                return record
        return None

    def find(self, query: str) -> list[AccountRecord]:
        self.load()
        needle = query.strip().casefold()
        if not needle:
            return list(self._records)
        return [
            record
            for record in self._records
            if needle in record.name.casefold() or needle in record.account.casefold()
        ]

    def __len__(self) -> int:
        self.load()
        return len(self._records)

    # -- mutations ---------------------------------------------------------
    def add(self, name: str, account: str, password: bytes | bytearray) -> AccountRecord:
        self.load()
        name = (name or "").strip()
        account = (account or "").strip()
        if not name:
            raise ValueError("备注名不能为空")
        if not account:
            raise ValueError("账号不能为空")
        if not password:
            raise ValueError("密码不能为空")
        if isinstance(password, str):  # 防御性：绝不接受 str 直接落盘
            raise TypeError("password 必须是 bytes/bytearray")
        secret = encrypt_b64(bytes(password))
        now = _utc_now()
        record = AccountRecord(
            id=uuid.uuid4().hex,
            name=name,
            account=account,
            secret_b64=secret,
            created_at=now,
            updated_at=now,
        )
        previous = list(self._records)
        self._records.append(record)
        try:
            self.save()
        except Exception:
            self._records = previous
            raise
        return record

    def update(
        self,
        record_id: str,
        *,
        name: str | None = None,
        account: str | None = None,
        new_password: bytes | bytearray | None = None,
    ) -> AccountRecord:
        self.load()
        current = self.get(record_id)
        if current is None:
            raise StoreError("记录不存在")
        if new_password is not None:
            if isinstance(new_password, str):
                raise TypeError("new_password 必须是 bytes/bytearray")
            if not new_password:
                raise ValueError("新密码不能为空")
            secret = encrypt_b64(bytes(new_password))
        else:
            secret = current.secret_b64
        new_name = current.name if name is None else name.strip()
        new_account = current.account if account is None else account.strip()
        if not new_name:
            raise ValueError("备注名不能为空")
        if not new_account:
            raise ValueError("账号不能为空")
        updated = AccountRecord(
            id=current.id,
            name=new_name,
            account=new_account,
            secret_b64=secret,
            created_at=current.created_at,
            updated_at=_utc_now(),
        )
        previous = list(self._records)
        self._records = [updated if record.id == record_id else record for record in self._records]
        try:
            self.save()
        except Exception:
            self._records = previous
            raise
        return updated

    def delete(self, record_id: str) -> bool:
        self.load()
        previous = list(self._records)
        remaining = [record for record in self._records if record.id != record_id]
        if len(remaining) == len(self._records):
            return False
        self._records = remaining
        try:
            self.save()
        except Exception:
            self._records = previous
            raise
        return True

    # -- secrets -----------------------------------------------------------
    def decrypt_password(self, record_id: str) -> bytearray:
        """返回明文 bytearray；调用方必须尽快 ``wipe``。"""
        record = self.get(record_id)
        if record is None:
            raise StoreError("记录不存在")
        try:
            raw = decrypt_b64(record.secret_b64)
        except DPAPIError:
            raise
        return bytearray(raw)

    def verify_decrypt(self, record_id: str) -> int:
        data = self.decrypt_password(record_id)
        try:
            return len(data)
        finally:
            wipe(data)

    # -- persistence -------------------------------------------------------
    def save(self) -> None:
        self.load()
        if self.read_only:
            raise StoreError("账号文件为只读（版本较新），拒绝覆盖")
        payload = {
            "app": STORE_APP,
            "version": STORE_VERSION,
            "records": [record.to_dict() for record in self._records],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ensure_app_dirs()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            # 覆盖前保留一份密文备份；即使有记录被跳过也仍可人工恢复
            try:
                import shutil

                shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak"))
            except OSError:
                pass
        fd, tmp_name = tempfile.mkstemp(prefix=".accounts-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- corruption backups ------------------------------------------------
    def _backup_corrupt(self) -> Path | None:
        if not self.path.exists():
            return None
        backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
        try:
            os.replace(self.path, backup)
            return backup
        except OSError:
            return None

    def _copy_backup(self, tag: str) -> Path | None:
        if not self.path.exists():
            return None
        backup = self.path.with_name(f"{self.path.name}.{tag}-{int(time.time())}")
        try:
            import shutil

            shutil.copy2(self.path, backup)
            return backup
        except OSError:
            return None
