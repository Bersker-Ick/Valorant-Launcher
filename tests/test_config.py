from __future__ import annotations

import unittest

from login_assistant.config import AppConfig, InputSettings


class ConfigTest(unittest.TestCase):
    def test_password_uia_flag_roundtrip(self) -> None:
        cfg = AppConfig()
        cfg.input.password_use_uia = True
        data = cfg.to_dict()
        self.assertTrue(data["input"]["password_use_uia"])
        loaded = AppConfig.from_dict(data)
        self.assertTrue(loaded.input.password_use_uia)

    def test_password_uia_default_false(self) -> None:
        self.assertFalse(InputSettings().password_use_uia)


if __name__ == "__main__":
    unittest.main()
