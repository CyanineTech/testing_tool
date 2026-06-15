import signal
import subprocess
import unittest
from unittest.mock import patch

from feishu_agent.providers.base import run_provider_command


class _TimeoutProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.returncode = None
        self._communicate_calls = 0

    def communicate(self, input=None, timeout=None):
        self._communicate_calls += 1
        if self._communicate_calls == 1:
            raise subprocess.TimeoutExpired(
                cmd=["copilot", "-p", "payload"],
                timeout=timeout,
                output='{"type":"assistant.message_delta","data":{"deltaContent":"partial"}}\n',
                stderr='warning-before-timeout\n',
            )
        self.returncode = -signal.SIGTERM
        return ('{"type":"assistant.message","data":{"content":"done"}}\n', 'warning-after-timeout\n')


class ProviderBaseTests(unittest.TestCase):
    def test_run_provider_command_preserves_partial_output_on_timeout(self) -> None:
        process = _TimeoutProcess()

        with patch("feishu_agent.providers.base.subprocess.Popen", return_value=process), patch(
            "feishu_agent.providers.base.os.killpg"
        ) as mocked_killpg:
            returncode, stdout, stderr, timed_out = run_provider_command(["copilot", "-p", "payload"], None, 3)

        mocked_killpg.assert_called_once_with(process.pid, signal.SIGTERM)
        self.assertEqual(returncode, -signal.SIGTERM)
        self.assertTrue(timed_out)
        self.assertIn('assistant.message_delta', stdout)
        self.assertIn('assistant.message', stdout)
        self.assertIn('warning-before-timeout', stderr)
        self.assertIn('warning-after-timeout', stderr)


if __name__ == "__main__":
    unittest.main()