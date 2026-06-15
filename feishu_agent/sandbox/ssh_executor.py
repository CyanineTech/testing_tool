import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from feishu_agent.config import Settings
from feishu_agent.ssh.client import SshResult, run_validated_ssh_command


@dataclass(frozen=True)
class SandboxResult:
    host: str
    command: str
    returncode: int
    stdout: str
    stderr: str
    mode: str


def _whitelist_path() -> Path:
    return Path(__file__).with_name("whitelist.json")


def load_whitelist() -> Dict[str, object]:
    return json.loads(_whitelist_path().read_text(encoding="utf-8"))


def _matches_any(patterns: List[str], command: str) -> bool:
    return any(re.search(pattern, command) for pattern in patterns)


_SHELL_CONTROL_RE = re.compile(r"(?:\|\||&&|[|;&<>`])|(?:\$\()")


def _contains_shell_controls(command: str) -> bool:
    return bool(_SHELL_CONTROL_RE.search(command))


def _parse_local_command(command: str) -> List[str]:
    normalized = command.strip()
    if not normalized:
        raise ValueError("local command is empty")
    if _contains_shell_controls(normalized):
        raise ValueError("shell control operators are not allowed in local sandbox commands")
    try:
        argv = shlex.split(normalized, posix=True)
    except ValueError as error:
        raise ValueError(f"invalid local command syntax: {error}") from error
    if not argv:
        raise ValueError("local command is empty")
    return argv


def _validate(route: str, mode: str, command: str) -> str:
    whitelist = load_whitelist()
    deny_patterns = [str(item) for item in whitelist.get("deny_patterns") or []]
    if _matches_any(deny_patterns, command):
        return "command denied by sandbox policy"

    if mode == "local" and _contains_shell_controls(command):
        return "shell control operators are not allowed in local sandbox commands"

    if mode == "local":
        allow_patterns = [str(item) for item in whitelist.get("local_allow_patterns") or []]
    else:
        route_map = whitelist.get("ssh_allow_patterns") or {}
        allow_patterns = [str(item) for item in (route_map.get(route) or [])]
    if not _matches_any(allow_patterns, command):
        return "command not allowed by whitelist"
    return ""


def _run_local_command(command: str, timeout: int) -> SandboxResult:
    try:
        argv = _parse_local_command(command)
    except ValueError as error:
        return SandboxResult(
            host="localhost",
            command=command,
            returncode=126,
            stdout="",
            stderr=str(error),
            mode="local",
        )

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return SandboxResult(
        host="localhost",
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        mode="local",
    )


def execute_readonly_action(
    route: str,
    target: str,
    command: str,
    timeout: int = 120,
    settings: Optional[Settings] = None,
) -> SandboxResult:
    normalized = command.strip()
    mode = "ssh"
    actual_command = normalized
    if normalized.startswith("local:"):
        mode = "local"
        actual_command = normalized.split(":", 1)[1].strip()
    elif normalized.startswith("ssh:"):
        mode = "ssh"
        actual_command = normalized.split(":", 1)[1].strip()
    elif not target:
        mode = "local"

    validation_error = _validate(route, mode, actual_command)
    if validation_error:
        return SandboxResult(
            host=target or "localhost",
            command=actual_command,
            returncode=126,
            stdout="",
            stderr=validation_error,
            mode=mode,
        )

    if mode == "local":
        return _run_local_command(actual_command, timeout=timeout)

    ssh_result: SshResult = run_validated_ssh_command(target, actual_command, timeout=timeout, settings=settings)
    return SandboxResult(
        host=ssh_result.host,
        command=ssh_result.command,
        returncode=ssh_result.returncode,
        stdout=ssh_result.stdout,
        stderr=ssh_result.stderr,
        mode="ssh",
    )
