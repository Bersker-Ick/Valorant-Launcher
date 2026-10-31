from __future__ import annotations

import io
import logging
import unittest

from login_assistant.security.redact import (
    MASK,
    RedactingFilter,
    RedactingFormatter,
    redact_text,
)


class RedactTest(unittest.TestCase):
    def test_key_value_patterns(self) -> None:
        cases = [
            "password=Abc123!@#",
            "password: Abc123!@#",
            "PASSWORD = Abc123!@#",
            "pwd=Abc123!@#",
            "secret: Abc123!@#",
            "token=Abc123!@#",
            "密码：Abc123!@#",
            "口令=Abc123!@#",
            "password is Abc123!@#",
        ]
        for text in cases:
            with self.subTest(text=text):
                result = redact_text(text)
                self.assertNotIn("Abc123!@#", result)
                self.assertIn(MASK, result)

    def test_plain_text_untouched(self) -> None:
        self.assertEqual(redact_text("hello world"), "hello world")
        self.assertEqual(redact_text("secretary"), "secretary")

    def test_logging_formatter(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(message)s"))
        handler.addFilter(RedactingFilter())
        logger = logging.getLogger("login_assistant.test_redact")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.info("login with password=%s", "Abc123!@#")
        logger.info("密码：Abc123!@#")
        output = stream.getvalue()
        self.assertNotIn("Abc123!@#", output)
        self.assertIn(MASK, output)

    def test_traceback_redacted(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(message)s"))
        logger = logging.getLogger("login_assistant.test_redact_exc")
        logger.handlers = [handler]
        logger.propagate = False
        try:
            raise ValueError("password=Abc123!@#")
        except ValueError:
            logger.exception("failed")
        self.assertNotIn("Abc123!@#", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
