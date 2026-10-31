from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "login_assistant"

# 只检查 import 语句，避免误伤文档/注释中的 URL。
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z0-9_\.]+)", re.MULTILINE)
FORBIDDEN_PREFIXES = (
    "requests",
    "urllib",
    "http.client",
    "socket",
    "aiohttp",
    "websocket",
    "websockets",
    "selenium",
    "PySide6.QtNetwork",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
)


class NoNetworkTest(unittest.TestCase):
    def test_runtime_package_has_no_network_imports(self) -> None:
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for module in IMPORT_RE.findall(text):
                if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES):
                    offenders.append(f"{path.relative_to(ROOT)}: {module}")
        self.assertEqual(offenders, [], "运行时代码不允许导入网络库：" + "; ".join(offenders))

    def test_requirements_only_gui_dependency(self) -> None:
        lines = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(lines)
        for line in lines:
            self.assertIn("PySide6", line)


if __name__ == "__main__":
    unittest.main()
