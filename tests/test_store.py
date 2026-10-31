from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from login_assistant.core.store import AccountStore, StoreError


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"
        self.password = b"Abc123!@#-very-secret"
        self.store = AccountStore(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_reload_decrypt(self) -> None:
        record = self.store.add("主账号", "user@example.com", self.password)
        self.assertEqual(record.account, "user@example.com")
        self.assertNotIn("Abc123", record.secret_b64)
        reloaded = AccountStore(self.path)
        reloaded.load()
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(bytes(reloaded.decrypt_password(record.id)), self.password)
        self.assertEqual(reloaded.get(record.id).name, "主账号")

    def test_file_contains_only_ciphertext(self) -> None:
        record = self.store.add("n", "a", self.password)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn(self.password.decode(), text)
        self.assertNotIn("Abc123", text)
        data = json.loads(text)
        self.assertEqual(data["app"], "LoginAssistant")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["records"][0]["id"], record.id)
        self.assertIn("secret", data["records"][0])
        self.assertNotIn("password", text.lower())

    def test_update_keep_or_change_password(self) -> None:
        record = self.store.add("n", "a", self.password)
        self.store.update(record.id, name="new name")
        self.assertEqual(self.store.get(record.id).name, "new name")
        self.assertEqual(bytes(self.store.decrypt_password(record.id)), self.password)
        new_password = b"Another!Pass9"
        self.store.update(record.id, new_password=new_password)
        self.assertEqual(bytes(self.store.decrypt_password(record.id)), new_password)
        self.assertNotEqual(self.store.get(record.id).secret_b64, record.secret_b64)

    def test_delete(self) -> None:
        record = self.store.add("n", "a", self.password)
        self.assertTrue(self.store.delete(record.id))
        self.assertFalse(self.store.delete(record.id))
        self.assertEqual(len(self.store), 0)
        self.assertFalse(self.path.read_text(encoding="utf-8").count("secret"))

    def test_find(self) -> None:
        self.store.add("工作", "work@example.com", self.password)
        self.store.add("娱乐", "play@example.com", self.password)
        self.assertEqual(len(self.store.find("工作")), 1)
        self.assertEqual(len(self.store.find("example.com")), 2)
        self.assertEqual(len(self.store.find("PLAY")), 1)
        self.assertEqual(len(self.store.find("")), 2)

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.store.add("", "a", self.password)
        with self.assertRaises(ValueError):
            self.store.add("n", "", self.password)
        with self.assertRaises(ValueError):
            self.store.add("n", "a", b"")
        with self.assertRaises(TypeError):
            self.store.add("n", "a", "string-password")  # type: ignore[arg-type]

    def test_corrupt_file_is_backed_up(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        store = AccountStore(self.path)
        store.load()
        self.assertEqual(len(store), 0)
        self.assertIsNotNone(store.warning)
        backups = list(self.path.parent.glob("accounts.json.corrupt-*"))
        self.assertEqual(len(backups), 1)

    def test_newer_version_read_only(self) -> None:
        self.path.write_text(
            json.dumps({"app": "LoginAssistant", "version": 99, "records": []}),
            encoding="utf-8",
        )
        store = AccountStore(self.path)
        store.load()
        self.assertTrue(store.read_only)
        self.assertIsNotNone(store.warning)
        with self.assertRaises(StoreError):
            store.save()

    def test_verify_decrypt(self) -> None:
        record = self.store.add("n", "a", self.password)
        self.assertEqual(self.store.verify_decrypt(record.id), len(self.password))

    def test_backup_before_overwrite(self) -> None:
        record = self.store.add("n", "a", self.password)
        self.store.update(record.id, name="renamed")
        self.assertTrue((self.path.parent / "accounts.json.bak").exists())


if __name__ == "__main__":
    unittest.main()
