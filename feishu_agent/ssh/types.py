from dataclasses import dataclass


@dataclass(frozen=True)
class SshResult:
    host: str
    command: str
    returncode: int
    stdout: str
    stderr: str
    rejection_reason: str = ""
