import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feishu_agent.ssh.backends import ParamikoSshBackend


class FakeStream:
    def __init__(self, payload, exit_status=0):
        self._payload = payload
        self.channel = SimpleNamespace(recv_exit_status=lambda: exit_status)

    def read(self):
        return self._payload


class FakeSSHClient:
    instances = []
    connect_error = None

    def __init__(self):
        self.load_system_host_keys_called = False
        self.policy = None
        self.connect_kwargs = None
        self.exec_command_args = None
        self.closed = False
        self.__class__.instances.append(self)

    def load_system_host_keys(self):
        self.load_system_host_keys_called = True

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        if self.__class__.connect_error is not None:
            raise self.__class__.connect_error

    def exec_command(self, command, timeout=None, get_pty=False):
        self.exec_command_args = (command, timeout, get_pty)
        return None, FakeStream(b"stdout\n", exit_status=0), FakeStream(b"\n", exit_status=0)

    def close(self):
        self.closed = True


def make_fake_paramiko_module():
    return SimpleNamespace(
        SSHClient=FakeSSHClient,
        RejectPolicy=type("RejectPolicy", (), {}),
        AutoAddPolicy=type("AutoAddPolicy", (), {}),
        BadHostKeyException=type("BadHostKeyException", (Exception,), {}),
        AuthenticationException=type("AuthenticationException", (Exception,), {}),
        UnableToAuthenticate=type("UnableToAuthenticate", (Exception,), {}),
        NoValidConnectionsError=type("NoValidConnectionsError", (Exception,), {}),
        SSHException=type("SSHException", (Exception,), {}),
    )


def make_settings(user="robot", timeout_seconds=10, reject_unknown_host_keys=True):
    return SimpleNamespace(
        ssh=SimpleNamespace(
            user=user,
            timeout_seconds=timeout_seconds,
            reject_unknown_host_keys=reject_unknown_host_keys,
        )
    )


class ParamikoSshBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSSHClient.instances = []
        FakeSSHClient.connect_error = None

    def tearDown(self) -> None:
        FakeSSHClient.instances = []
        FakeSSHClient.connect_error = None

    def test_paramiko_backend_reports_unavailable_when_import_fails(self) -> None:
        settings = make_settings()
        with patch("feishu_agent.ssh.backends.importlib.import_module", side_effect=ImportError("missing")):
            backend = ParamikoSshBackend(settings)
            result = backend.run("pl-1015", "systemctl status supervisor")

        self.assertEqual(result.returncode, 126)
        self.assertEqual(result.rejection_reason, "paramiko_not_installed")
        self.assertEqual(result.stderr, "paramiko_not_installed")

    def test_paramiko_backend_executes_command_and_closes_client(self) -> None:
        settings = make_settings(user="robot", timeout_seconds=10, reject_unknown_host_keys=True)
        fake_module = make_fake_paramiko_module()
        with patch("feishu_agent.ssh.backends.importlib.import_module", return_value=fake_module), patch.dict(
            "os.environ",
            {"SSH_USER": "robot", "SSH_PASSWORD": "secret"},
            clear=True,
        ):
            backend = ParamikoSshBackend(settings)
            result = backend.run("pl-1015", "rostopic echo /low_level_error -n1", timeout=7)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "stdout\n")
        self.assertEqual(result.stderr, "")

        client = FakeSSHClient.instances[-1]
        self.assertTrue(client.load_system_host_keys_called)
        self.assertTrue(client.closed)
        self.assertEqual(client.policy.__class__.__name__, "RejectPolicy")
        self.assertEqual(client.connect_kwargs["hostname"], "pl-1015")
        self.assertEqual(client.connect_kwargs["username"], "robot")
        self.assertEqual(client.connect_kwargs["password"], "secret")
        self.assertEqual(client.connect_kwargs["timeout"], 7)
        self.assertFalse(client.connect_kwargs["allow_agent"])
        self.assertFalse(client.connect_kwargs["look_for_keys"])
        self.assertEqual(client.exec_command_args[0], "timeout --signal=TERM 10s rostopic echo /low_level_error -n1")
        self.assertEqual(client.exec_command_args[1], 7)
        self.assertFalse(client.exec_command_args[2])

    def test_paramiko_backend_reports_unknown_host_key_rejection(self) -> None:
        settings = make_settings(reject_unknown_host_keys=True)
        fake_module = make_fake_paramiko_module()
        FakeSSHClient.connect_error = fake_module.BadHostKeyException("Server 'pl-1015' not found in known_hosts")
        with patch("feishu_agent.ssh.backends.importlib.import_module", return_value=fake_module), patch.dict(
            "os.environ",
            {"SSH_USER": "robot"},
            clear=True,
        ):
            backend = ParamikoSshBackend(settings)
            result = backend.run("pl-1015", "systemctl status supervisor", timeout=5)

        self.assertEqual(result.returncode, 255)
        self.assertEqual(result.rejection_reason, "unknown_host_key")
        self.assertIn("known_hosts", result.stderr)
        self.assertTrue(FakeSSHClient.instances[-1].closed)


if __name__ == "__main__":
    unittest.main()
