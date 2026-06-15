import importlib
import os
import shlex
import shutil
import socket
import subprocess
from abc import ABC, abstractmethod
from typing import List, Optional

from feishu_agent.config import Settings, load_settings
from feishu_agent.ssh.types import SshResult


SETTINGS: Optional[Settings] = None


_INTERACTIVE_BASH_NOISE_LINES = {
    "bash: cannot set terminal process group (-1): Inappropriate ioctl for device",
    "bash: no job control in this shell",
}


_HOST_KEY_ERROR_MARKERS = (
    "Host key verification failed",
    "REMOTE HOST IDENTIFICATION HAS CHANGED!",
    "No host key is known",
    "Offending",
    "not found in known_hosts",
    "not found in known hosts",
)


class SshBackend(ABC):
    @abstractmethod
    def run(self, host: str, command: str, timeout: int = 120) -> SshResult:
        raise NotImplementedError


class CliSshBackend(SshBackend):
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or _resolve_settings()

    def run(self, host: str, command: str, timeout: int = 120) -> SshResult:
        try:
            completed = subprocess.run(
                self._build_ssh_command(host, command),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as error:
            stdout = _coerce_output(error.output)
            stderr = _coerce_output(error.stderr)
            timeout_note = f"command timed out after {timeout}s"
            stderr = f"{stderr.rstrip()}\n{timeout_note}\n" if stderr.strip() else f"{timeout_note}\n"
            returncode = 124

        rejection_reason = "unknown_host_key" if _is_unknown_host_key(stderr) else ""
        return SshResult(
            host=host,
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=self._strip_interactive_bash_noise(stderr),
            rejection_reason=rejection_reason,
        )

    def _build_ssh_command(self, host: str, command: str) -> List[str]:
        user = os.getenv("SSH_USER", self.settings.ssh.user)
        password = os.getenv("SSH_PASSWORD", "qweasdzxc")
        strict_host_key_checking = "yes" if self.settings.ssh.reject_unknown_host_keys else "accept-new"
        remote_shell_command = (
            "bash -ic "
            f"{shlex.quote(self._wrap_remote_command(command))}"
        )
        ssh_base = [
            "ssh",
            "-T",
            "-o",
            f"StrictHostKeyChecking={strict_host_key_checking}",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ServerAliveInterval=3",
            "-o",
            "ServerAliveCountMax=1",
            f"{user}@{host}",
            remote_shell_command,
        ]
        if shutil.which("sshpass") and password:
            return [
                "sshpass",
                "-p",
                password,
                *ssh_base[:2],
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "NumberOfPasswordPrompts=1",
                *ssh_base[2:],
            ]

        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            *ssh_base[1:],
        ]

    def _wrap_remote_command(self, command: str) -> str:
        normalized = command.strip()
        if normalized.startswith("rostopic echo "):
            timeout_seconds = max(1, int(os.getenv("FEISHU_SSH_ROSTOPIC_TIMEOUT_SECONDS", str(self.settings.ssh.timeout_seconds))))
            return f"timeout --signal=TERM {timeout_seconds}s {normalized}"
        return normalized

    @staticmethod
    def _strip_interactive_bash_noise(stderr: str) -> str:
        if not stderr:
            return ""

        filtered_lines = [
            line for line in stderr.splitlines() if line.strip() and line.strip() not in _INTERACTIVE_BASH_NOISE_LINES
        ]
        if not filtered_lines:
            return ""
        return "\n".join(filtered_lines) + ("\n" if stderr.endswith("\n") else "")


class ParamikoSshBackend(SshBackend):
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or _resolve_settings()
        self._missing_reason = "paramiko_backend_unavailable"
        self._paramiko = None
        try:
            self._paramiko = importlib.import_module("paramiko")
        except ImportError:
            self._missing_reason = "paramiko_not_installed"

    def run(self, host: str, command: str, timeout: int = 120) -> SshResult:
        if self._paramiko is None:
            return SshResult(
                host=host,
                command=command,
                returncode=126,
                stdout="",
                stderr=self._missing_reason,
                rejection_reason=self._missing_reason,
            )

        client = None
        try:
            wrapped_command = CliSshBackend(self.settings)._wrap_remote_command(command)
            username = os.getenv("SSH_USER", self.settings.ssh.user)
            password = os.getenv("SSH_PASSWORD", "qweasdzxc")
            client = self._paramiko.SSHClient()
            try:
                client.load_system_host_keys()
            except Exception:
                pass

            if self.settings.ssh.reject_unknown_host_keys:
                client.set_missing_host_key_policy(self._paramiko.RejectPolicy())
            else:
                client.set_missing_host_key_policy(self._paramiko.AutoAddPolicy())

            client.connect(
                hostname=host,
                username=username,
                password=password or None,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                channel_timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            stdin, stdout, stderr = client.exec_command(wrapped_command, timeout=timeout, get_pty=False)
            stdout_text = _coerce_output(stdout.read())
            stderr_text = _coerce_output(stderr.read())
            returncode = _recv_exit_status(stdout)

            return SshResult(
                host=host,
                command=command,
                returncode=returncode,
                stdout=stdout_text,
                stderr=CliSshBackend._strip_interactive_bash_noise(stderr_text),
                rejection_reason="",
            )
        except Exception as error:
            return self._handle_paramiko_error(host, command, error, timeout)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def _handle_paramiko_error(self, host: str, command: str, error: BaseException, timeout: int) -> SshResult:
        paramiko_module = self._paramiko
        if isinstance(error, (socket.timeout, TimeoutError)):
            return SshResult(
                host=host,
                command=command,
                returncode=124,
                stdout="",
                stderr=_timeout_stderr(timeout, error),
                rejection_reason="",
            )

        if paramiko_module is not None:
            bad_host_key = getattr(paramiko_module, "BadHostKeyException", None)
            auth_exception = getattr(paramiko_module, "AuthenticationException", None)
            unable_to_authenticate = getattr(paramiko_module, "UnableToAuthenticate", None)
            no_valid_connections = getattr(paramiko_module, "NoValidConnectionsError", None)
            ssh_exception = getattr(paramiko_module, "SSHException", None)

            if bad_host_key is not None and isinstance(error, bad_host_key):
                return _error_result(host, command, error, "unknown_host_key")

            if (
                (auth_exception is not None and isinstance(error, auth_exception))
                or (unable_to_authenticate is not None and isinstance(error, unable_to_authenticate))
            ):
                return _error_result(host, command, error, "authentication_failed")

            if no_valid_connections is not None and isinstance(error, no_valid_connections):
                return _error_result(host, command, error, "connection_failed")

            if ssh_exception is not None and isinstance(error, ssh_exception):
                rejection_reason = "unknown_host_key" if self.settings.ssh.reject_unknown_host_keys and _is_unknown_host_key(str(error)) else "ssh_error"
                return _error_result(host, command, error, rejection_reason)

        rejection_reason = "unknown_host_key" if self.settings.ssh.reject_unknown_host_keys and _is_unknown_host_key(str(error)) else "ssh_error"
        return _error_result(host, command, error, rejection_reason)


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _is_unknown_host_key(stderr: str) -> bool:
    normalized = (stderr or "").strip()
    if not normalized:
        return False
    return any(marker.lower() in normalized.lower() for marker in _HOST_KEY_ERROR_MARKERS)


def _timeout_stderr(timeout: int, error: Optional[BaseException] = None) -> str:
    note = f"command timed out after {timeout}s"
    if error is not None:
        detail = str(error).strip()
        if detail:
            return f"{detail}\n{note}\n"
    return f"{note}\n"


def _recv_exit_status(stdout: object) -> int:
    channel = getattr(stdout, "channel", None)
    if channel is not None:
        recv_exit_status = getattr(channel, "recv_exit_status", None)
        if callable(recv_exit_status):
            try:
                return int(recv_exit_status())
            except Exception:
                return 255
    return 0


def _error_result(host: str, command: str, error: BaseException, rejection_reason: str) -> SshResult:
    stderr = str(error).strip() or rejection_reason
    return SshResult(
        host=host,
        command=command,
        returncode=255,
        stdout="",
        stderr=stderr,
        rejection_reason=rejection_reason,
    )


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS
