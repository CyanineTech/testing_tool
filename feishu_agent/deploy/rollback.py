import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

from feishu_agent.config import Settings


@dataclass(frozen=True)
class DeployRecord:
    version: str
    deployed_at: str
    notes: str = ""


def _history_path(settings: Settings) -> Path:
    history_dir = settings.repo_root / ".feishu_agent"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / "deploy_history.jsonl"


def record_deploy(version: str, deployed_at: str, notes: str = "", *, settings: Settings) -> DeployRecord:
    record = DeployRecord(version=version, deployed_at=deployed_at, notes=notes)
    with _history_path(settings=settings).open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return record


def list_deploy_history(*, settings: Settings) -> List[DeployRecord]:
    history_file = _history_path(settings=settings)
    if not history_file.exists():
        return []
    records: List[DeployRecord] = []
    for line in history_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            records.append(DeployRecord(**payload))
        except Exception:
            continue
    return records


def rollback_to_version(version: str, *, settings: Settings) -> str:
    history = list_deploy_history(settings=settings)
    for record in reversed(history):
        if record.version == version:
            return f"rollback target found: {record.version} at {record.deployed_at}"
    return f"rollback target not found: {version}"
