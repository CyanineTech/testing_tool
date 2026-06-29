import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feishu_agent.sandbox.ssh_executor import execute_readonly_action
from feishu_agent.ssh.policy import validate_command


class SandboxExecutorTests(unittest.TestCase):
    def test_local_execution_uses_parameterized_subprocess(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        with patch("feishu_agent.sandbox.ssh_executor.subprocess.run", return_value=completed) as mocked_run:
            result = execute_readonly_action("network", "", "ip a", timeout=5)

        self.assertEqual(result.mode, "local")
        self.assertEqual(result.stdout, "ok\n")
        self.assertEqual(mocked_run.call_args.args[0], ["ip", "a"])
        self.assertNotIn("shell", mocked_run.call_args.kwargs)
        self.assertEqual(mocked_run.call_args.kwargs["capture_output"], True)
        self.assertEqual(mocked_run.call_args.kwargs["timeout"], 5)

    def test_local_execution_rejects_shell_control_operators(self) -> None:
        with patch("feishu_agent.sandbox.ssh_executor.subprocess.run") as mocked_run:
            result = execute_readonly_action("network", "", "ip a | grep foo", timeout=5)

        self.assertEqual(result.returncode, 126)
        self.assertIn("shell control operators", result.stderr)
        mocked_run.assert_not_called()

    def test_amr_whitelist_allows_history_log_find_commands(self) -> None:
        self.assertTrue(
            validate_command(
                "amr",
                "find /home/robot/log/not_permanent -maxdepth 4 \\( -type f -o -type l \\) -name 'caution*'",
            )
        )
        self.assertTrue(validate_command("amr", "ls /home/robot/log/not_permanent"))
        self.assertTrue(validate_command("rcs", "grep mysql /var/log/syslog"))
        self.assertTrue(validate_command("rcs", "systemctl status supervisor --no-pager"))
        self.assertTrue(validate_command("rcs", "docker logs docker-mysql_5_7-1 --tail 80"))
        self.assertTrue(validate_command("rcs", "docker exec docker-mysql_5_7-1 mysqladmin ping -u root"))


if __name__ == "__main__":
    unittest.main()
