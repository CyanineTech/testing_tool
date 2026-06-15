import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feishu_agent.main import main as run_main


class MainTests(unittest.TestCase):
    def test_main_starts_listener_from_bootstrap(self) -> None:
        fake_orchestrator = object()
        fake_components = SimpleNamespace(orchestrator=fake_orchestrator)
        fake_listener = SimpleNamespace(start=Mock())

        with patch("feishu_agent.main.create_app", return_value=fake_components), patch(
            "feishu_agent.main.FeishuListener", return_value=fake_listener
        ) as mocked_listener:
            run_main()

        mocked_listener.assert_called_once_with(orchestrator=fake_orchestrator)
        fake_listener.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
