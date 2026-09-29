"""验证结构化日志脱敏以及成功、失败文件分流。"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from caption_cut_service.logging import configure_logging, log_event


class LoggingTest(unittest.TestCase):
    """检查两类终态事件只进入各自的 JSON 日志文件。"""

    def test_terminal_events_are_written_to_separate_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            configure_logging(level="INFO", log_dir=log_dir)
            logger = logging.getLogger("caption_cut_service.tests")

            log_event(logger, "caption_cut_succeeded", request_id="ok", api_key="secret-value")
            log_event(
                logger,
                "caption_cut_failed",
                level=logging.ERROR,
                request_id="failed",
                error="request failed?OSSAccessKeyId=visible&Signature=visible",
            )
            logging.shutdown()

            success = json.loads((log_dir / "success" / "caption-cut-success.log").read_text(encoding="utf-8"))
            failure = json.loads((log_dir / "failure" / "caption-cut-failure.log").read_text(encoding="utf-8"))

        self.assertEqual(success["event"], "caption_cut_succeeded")
        self.assertEqual(success["request_id"], "ok")
        self.assertEqual(success["api_key"], "***")
        self.assertEqual(failure["event"], "caption_cut_failed")
        self.assertEqual(failure["request_id"], "failed")
        self.assertNotIn("visible", failure["error"])


if __name__ == "__main__":
    unittest.main()
