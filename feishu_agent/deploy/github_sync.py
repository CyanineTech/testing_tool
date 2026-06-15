import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from feishu_agent.config import Settings
from feishu_agent.deploy.manifest import DeployManifest, load_manifest, validate_manifest


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    action: str
    local_version: str
    remote_version: str
    notes: List[str] = field(default_factory=list)


def _run_git(args: List[str], cwd: Optional[Path] = None, *, settings: Settings) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd or settings.repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    return output


def check_remote_version(*, settings: Settings) -> SyncResult:
    local_version = _run_git(["rev-parse", "HEAD"], cwd=settings.repo_root, settings=settings)
    remote_version = _run_git(["rev-parse", "@{u}"], cwd=settings.repo_root, settings=settings)
    notes: List[str] = []
    if "fatal" in remote_version.lower() or not remote_version:
        notes.append("未配置上游远端，无法直接比较远端版本。")
    return SyncResult(
        ok=bool(local_version),
        action="check_remote_version",
        local_version=local_version,
        remote_version=remote_version,
        notes=notes,
    )


def sync_from_github(dry_run: bool = True, *, settings: Settings) -> SyncResult:
    manifest = load_manifest()
    issues = validate_manifest(manifest)
    version_info = check_remote_version(settings=settings)
    notes = list(version_info.notes)
    notes.extend(issues)
    if dry_run:
        notes.append("当前为 dry-run，只生成同步计划，不执行拉取或覆盖。")
    return SyncResult(
        ok=not issues,
        action="sync_from_github",
        local_version=version_info.local_version,
        remote_version=version_info.remote_version,
        notes=notes,
    )


def push_to_github(dry_run: bool = True, *, settings: Settings) -> SyncResult:
    version_info = check_remote_version(settings=settings)
    notes = list(version_info.notes)
    if dry_run:
        notes.append("当前为 dry-run，只生成推送计划，不执行 git push。")
    return SyncResult(
        ok=bool(version_info.local_version),
        action="push_to_github",
        local_version=version_info.local_version,
        remote_version=version_info.remote_version,
        notes=notes,
    )
