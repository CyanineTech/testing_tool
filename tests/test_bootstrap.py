import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_agent.bootstrap import build_components
from feishu_agent.config import LlmSettings, ProviderSettings, Settings, SshSettings, SystemSettings


class BootstrapTests(unittest.TestCase):
    def test_build_components_configures_runtime_once(self) -> None:
        fake_settings = Settings(
            repo_root=Path("/tmp/fake_repo"),
            knowledge_root=Path("/tmp/fake_repo/knowledge"),
            prompts_root=Path("/tmp/fake_repo/prompts"),
            deploy_root=Path("/tmp/fake_repo/feishu_agent/deploy"),
            provider=ProviderSettings(),
            llm=LlmSettings(),
            ssh=SshSettings(),
            system=SystemSettings(),
        )
        fake_session_store = object()

        with patch("feishu_agent.bootstrap.load_settings", return_value=fake_settings), patch(
            "feishu_agent.bootstrap.SessionStore", return_value=fake_session_store
        ), patch("feishu_agent.bootstrap.Orchestrator") as mocked_orchestrator, patch(
            "feishu_agent.bootstrap.ws_agent.configure_runtime",
            return_value=mocked_orchestrator.return_value,
        ) as mocked_configure:
            components = build_components()

        self.assertIs(components.settings, fake_settings)
        self.assertIs(components.session_store, fake_session_store)
        self.assertIs(components.orchestrator, mocked_orchestrator.return_value)
        mocked_orchestrator.assert_called_once_with(session_store=fake_session_store, settings=fake_settings)
        mocked_configure.assert_called_once_with(mocked_orchestrator.return_value)


if __name__ == "__main__":
    unittest.main()
