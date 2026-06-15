import os
import tempfile
import unittest
from unittest.mock import patch

from feishu_agent.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_load_settings_reads_yaml_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="config_yaml_") as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "\n".join(
                        [
                            "provider:",
                            "  mode: openai_sdk",
                            "llm:",
                            "  base_url: https://example.invalid",
                            "  api_key_env: TEST_OPENAI_KEY",
                            "  model: gpt-test",
                            "  store_responses: false",
                            "  parallel_tool_calls: false",
                            "  enable_tool_calls: false",
                            "ssh:",
                            "  user: robot",
                            "  timeout_seconds: 10",
                            "  backend: paramiko",
                            "system:",
                            "  knowledge_root: knowledge",
                            "  drafts_root: knowledge/_ai_drafts",
                            "  log_root: logs",
                        ]
                    )
                )

            with patch.dict("os.environ", {"FEISHU_CONFIG_PATH": config_path}, clear=False):
                settings = load_settings()

        self.assertEqual(settings.llm.base_url, "https://example.invalid")
        self.assertEqual(settings.llm.api_key_env, "TEST_OPENAI_KEY")
        self.assertEqual(settings.llm.model, "gpt-test")
        self.assertFalse(settings.llm.enable_tool_calls)
        self.assertEqual(settings.ssh.backend, "paramiko")

    def test_load_settings_allows_env_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="config_yaml_") as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "\n".join(
                        [
                            "llm:",
                            "  base_url: https://example.invalid",
                            "  api_key_env: TEST_OPENAI_KEY",
                            "  model: gpt-test",
                        ]
                    )
                )

            with patch.dict(
                "os.environ",
                {
                    "FEISHU_CONFIG_PATH": config_path,
                    "OPENAI_BASE_URL": "https://override.invalid",
                    "OPENAI_MODEL": "gpt-override",
                    "SSH_BACKEND": "paramiko",
                },
                clear=False,
            ):
                settings = load_settings()

        self.assertEqual(settings.llm.base_url, "https://override.invalid")
        self.assertEqual(settings.llm.model, "gpt-override")
        self.assertEqual(settings.ssh.backend, "paramiko")

    def test_load_settings_falls_back_for_invalid_api_key_env_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="config_yaml_") as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "\n".join(
                        [
                            "llm:",
                            "  api_key_env: invalid-env-name",
                        ]
                    )
                )

            with patch.dict("os.environ", {"FEISHU_CONFIG_PATH": config_path}, clear=False):
                settings = load_settings()

        self.assertEqual(settings.llm.api_key_env, "OPENAI_API_KEY")

    def test_load_settings_falls_back_for_invalid_ssh_backend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="config_yaml_") as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as fh:
                fh.write(
                    "\n".join(
                        [
                            "ssh:",
                            "  backend: invalid-backend",
                        ]
                    )
                )

            with patch.dict("os.environ", {"FEISHU_CONFIG_PATH": config_path}, clear=False):
                settings = load_settings()

        self.assertEqual(settings.ssh.backend, "paramiko")


if __name__ == "__main__":
    unittest.main()
