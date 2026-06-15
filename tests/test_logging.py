import logging
import os
import tempfile
import unittest
from pathlib import Path

from feishu_agent.providers.base import _write_provider_trace
from feishu_agent.observability.logger import setup_logging


class LoggingTests(unittest.TestCase):
    def test_setup_logging_writes_to_file(self) -> None:
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        original_level = root_logger.level
        original_configured = getattr(root_logger, "_feishu_logging_configured", False)
        original_log_file = getattr(root_logger, "_feishu_log_file", "")

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                log_file = Path(tmp_dir) / "feishu_agent.log"
                setup_logging(str(log_file), force=True)

                test_logger = logging.getLogger("feishu_agent.test")
                test_logger.info("file logging smoke test")

                for handler in logging.getLogger().handlers:
                    try:
                        handler.flush()
                    except Exception:
                        pass

                self.assertTrue(log_file.exists())
                self.assertIn("file logging smoke test", log_file.read_text(encoding="utf-8"))
        finally:
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
            for handler in original_handlers:
                root_logger.addHandler(handler)
            root_logger.setLevel(original_level)
            if original_configured:
                root_logger._feishu_logging_configured = original_configured
            elif hasattr(root_logger, "_feishu_logging_configured"):
                delattr(root_logger, "_feishu_logging_configured")
            if original_log_file:
                root_logger._feishu_log_file = original_log_file
            elif hasattr(root_logger, "_feishu_log_file"):
                delattr(root_logger, "_feishu_log_file")

    def test_provider_trace_writes_read_knowledge_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_file = Path(tmp_dir) / "provider_trace.log"
            original_trace_file = os.environ.get("FEISHU_PROVIDER_TRACE_FILE")
            os.environ["FEISHU_PROVIDER_TRACE_FILE"] = str(trace_file)
            try:
                _write_provider_trace(
                    "pty_read_knowledge",
                    "copilot --pty",
                    path="knowledge/error-codes.md",
                    success=True,
                )
            finally:
                if original_trace_file is None:
                    os.environ.pop("FEISHU_PROVIDER_TRACE_FILE", None)
                else:
                    os.environ["FEISHU_PROVIDER_TRACE_FILE"] = original_trace_file

            content = trace_file.read_text(encoding="utf-8")
            self.assertIn('"stage": "pty_read_knowledge"', content)
            self.assertIn('"path": "knowledge/error-codes.md"', content)


if __name__ == "__main__":
    unittest.main()