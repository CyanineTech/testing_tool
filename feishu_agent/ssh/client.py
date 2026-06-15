from typing import List, Optional, Sequence

from feishu_agent.config import Settings, load_settings
from feishu_agent.ssh.backends import CliSshBackend, ParamikoSshBackend
from feishu_agent.ssh.policy import validate_command
from feishu_agent.ssh.types import SshResult


SETTINGS: Optional[Settings] = None


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


def _select_backend(settings: Optional[Settings] = None) -> object:
    resolved = _resolve_settings(settings)
    backend = (resolved.ssh.backend or "cli").strip().lower()
    if backend == "paramiko":
        return ParamikoSshBackend(resolved)
    return CliSshBackend(resolved)


def run_ssh_command(
    route: str,
    host: str,
    command: str,
    timeout: int = 120,
    settings: Optional[Settings] = None,
) -> SshResult:
    if not validate_command(route, command):
        return SshResult(host=host, command=command, returncode=126, stdout="", stderr="command not allowed")

    return run_validated_ssh_command(host=host, command=command, timeout=timeout, settings=settings)


def run_validated_ssh_command(
    host: str,
    command: str,
    timeout: int = 120,
    settings: Optional[Settings] = None,
) -> SshResult:
    backend = _select_backend(settings)
    return backend.run(host=host, command=command, timeout=timeout)


def _build_ssh_command(host: str, command: str) -> List[str]:
    return CliSshBackend(_resolve_settings())._build_ssh_command(host, command)


def _wrap_remote_command(command: str) -> str:
    return CliSshBackend(_resolve_settings())._wrap_remote_command(command)


def _strip_interactive_bash_noise(stderr: str) -> str:
    return CliSshBackend._strip_interactive_bash_noise(stderr)


def run_ssh_batch(
    route: str,
    host: str,
    commands: Sequence[str],
    timeout: int = 120,
    settings: Optional[Settings] = None,
) -> List[SshResult]:
    results: List[SshResult] = []
    for command in commands:
        results.append(run_ssh_command(route, host, command, timeout=timeout, settings=settings))
    return results
