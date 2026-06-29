import unittest
import subprocess
from unittest.mock import patch

from feishu_agent.ssh import client as ssh_client


class SshClientTests(unittest.TestCase):
    def test_build_ssh_command_uses_config_default_user(self) -> None:
        with patch("feishu_agent.ssh.client.SETTINGS") as mocked_settings, patch(
            "feishu_agent.ssh.backends.shutil.which", return_value=None
        ), patch.dict("os.environ", {}, clear=True):
            mocked_settings.ssh.user = "robot"
            mocked_settings.ssh.timeout_seconds = 10
            mocked_settings.ssh.reject_unknown_host_keys = True
            command = ssh_client._build_ssh_command("leefung-s1", "systemctl status supervisor")

        self.assertIn("robot@leefung-s1", command)
        self.assertIn("StrictHostKeyChecking=yes", command)

    def test_build_ssh_command_allows_accept_new_when_host_key_rejection_is_disabled(self) -> None:
        with patch("feishu_agent.ssh.client.SETTINGS") as mocked_settings, patch(
            "feishu_agent.ssh.backends.shutil.which", return_value=None
        ), patch.dict("os.environ", {}, clear=True):
            mocked_settings.ssh.user = "robot"
            mocked_settings.ssh.timeout_seconds = 10
            mocked_settings.ssh.reject_unknown_host_keys = False
            command = ssh_client._build_ssh_command("leefung-s1", "systemctl status supervisor")

        self.assertIn("StrictHostKeyChecking=accept-new", command)

    def test_select_backend_uses_configured_paramiko_backend(self) -> None:
        with patch("feishu_agent.ssh.client.SETTINGS") as mocked_settings:
            mocked_settings.ssh.backend = "paramiko"
            backend = ssh_client._select_backend()

        self.assertEqual(type(backend).__name__, "ParamikoSshBackend")

    def test_wrap_remote_command_uses_config_timeout_default(self) -> None:
        with patch("feishu_agent.ssh.client.SETTINGS") as mocked_settings, patch.dict("os.environ", {}, clear=True):
            mocked_settings.ssh.timeout_seconds = 10
            wrapped = ssh_client._wrap_remote_command("rostopic echo /low_level_error -n1")

        self.assertIn("10s", wrapped)
        self.assertIn("source /opt/ros/noetic/setup.bash", wrapped)

    def test_run_validated_ssh_command_marks_unknown_host_key_rejection(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=255,
            stdout="",
            stderr="Host key verification failed\n",
        )

        with patch("feishu_agent.ssh.backends.subprocess.run", return_value=completed), patch(
            "feishu_agent.ssh.client.SETTINGS"
        ) as mocked_settings:
            mocked_settings.ssh.backend = "cli"
            mocked_settings.ssh.user = "robot"
            mocked_settings.ssh.timeout_seconds = 10
            mocked_settings.ssh.reject_unknown_host_keys = True
            result = ssh_client.run_validated_ssh_command("leefung-s1", "systemctl status supervisor", timeout=5)

        self.assertEqual(result.rejection_reason, "unknown_host_key")
        self.assertEqual(result.returncode, 255)
        self.assertIn("Host key verification failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
