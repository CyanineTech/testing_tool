import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from feishu_agent.config import Settings, load_settings


SETTINGS: Optional[Settings] = None
_ASCII_COMMAND_RE = re.compile(r"^[A-Za-z0-9_./:-]+(?:\s+[A-Za-z0-9_./:=|<>-]+)+$")
_KNOWLEDGE_PATH_ALIASES = {
    "knowledge/usb-device-troubleshooting.md": "knowledge/hardware_bus/usb-device-troubleshooting.md",
    "knowledge/can-eb-communication-abnormal.md": "knowledge/hardware_bus/can-eb-communication-abnormal.md",
    "knowledge/network-connectivity-failure.md": "knowledge/network/network-connectivity-failure.md",
    "knowledge/service-timeout.md": "knowledge/backend/service-timeout.md",
    "knowledge/rcs-backend-service-failure.md": "knowledge/backend/rcs-backend-service-failure.md",
    "knowledge/python-ros-call-chain-monitoring.md": "knowledge/backend/python-ros-call-chain-monitoring.md",
    "knowledge/rcs-task-system.md": "knowledge/task_dispatch/rcs-task-system.md",
    "knowledge/rcs-task-dispatch-failure.md": "knowledge/task_dispatch/rcs-task-dispatch-failure.md",
    "knowledge/fork-pickup-misalignment.md": "knowledge/task_dispatch/fork-pickup-misalignment.md",
    "knowledge/navigation-route-rules.md": "knowledge/cbs/navigation-route-rules.md",
    "knowledge/location-loss.md": "knowledge/ros/location-loss.md",
}


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


def _knowledge_root(settings: Optional[Settings] = None) -> Path:
    resolved = _resolve_settings(settings)
    return (resolved.repo_root / "knowledge").resolve()


def normalize_knowledge_path(relative_path: str, settings: Optional[Settings] = None) -> Tuple[str, str]:
    normalized = (relative_path or "").strip().replace("\\", "/")
    if not normalized:
        return "", "knowledge path is empty"
    if not normalized.startswith("knowledge/"):
        return "", "knowledge path must stay under knowledge/"
    if not normalized.endswith(".md"):
        return "", "knowledge path must point to a markdown file"

    normalized = _KNOWLEDGE_PATH_ALIASES.get(normalized, normalized)

    resolved = _resolve_settings(settings)
    candidate = (resolved.repo_root / normalized).resolve()
    knowledge_root = _knowledge_root(resolved)
    try:
        candidate.relative_to(knowledge_root)
    except ValueError:
        return "", "knowledge path escapes knowledge/"
    if not candidate.exists():
        return "", "knowledge document not found"
    return normalized, ""


def load_md(relative_path: str, settings: Optional[Settings] = None) -> str:
    resolved = _resolve_settings(settings)
    path = resolved.repo_root / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_case_docs(doc_paths: Iterable[str], settings: Optional[Settings] = None) -> Dict[str, str]:
    return {doc_path: load_md(doc_path, settings=settings) for doc_path in doc_paths}


def load_knowledge_bundle(route: str, doc_paths: Iterable[str], settings: Optional[Settings] = None) -> Dict[str, str]:
    return load_case_docs(doc_paths, settings=settings)


def load_knowledge_excerpt(
    relative_path: str,
    max_chars: int = 1200,
    max_lines: int = 12,
    settings: Optional[Settings] = None,
) -> Tuple[str, str]:
    normalized, error = normalize_knowledge_path(relative_path, settings=settings)
    if error:
        return "", error
    content = load_md(normalized, settings=settings)
    if not content:
        return "", "knowledge document is empty"

    lines = []
    total = 0
    in_code_block = False
    heading_one_seen = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not line or in_code_block or line.startswith("|"):
            continue
        if line.startswith("# "):
            if heading_one_seen:
                continue
            heading_one_seen = True
        if _looks_like_shell_command(line):
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        chunk = line[:remaining]
        lines.append(chunk)
        total += len(chunk)
        if total >= max_chars or len(lines) >= max_lines:
            break
    return "\n".join(lines).strip(), ""


def _looks_like_shell_command(line: str) -> bool:
    if not line:
        return False
    if line.startswith(("#", "##", "###", "- ", "* ")):
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in line):
        return False
    return bool(_ASCII_COMMAND_RE.match(line))
