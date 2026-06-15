from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class DeployManifest:
    include_paths: List[str] = field(default_factory=list)
    local_only_paths: List[str] = field(default_factory=list)
    confirm_required_paths: List[str] = field(default_factory=list)


def load_manifest() -> DeployManifest:
    return DeployManifest(
        include_paths=[
            "feishu_agent/**/*.py",
            "knowledge/**/*.md",
            "prompts/**/*.md",
            "README.md",
            "AGENTS.md",
            ".github/copilot-instructions.md",
        ],
        local_only_paths=[
            ".env",
            ".venv/**",
            "**/*.log",
            "**/autobag/**",
            "**/bag/**",
            "**/collect/**",
        ],
        confirm_required_paths=[
            "knowledge/**/*.md",
            "feishu_agent/playbooks/**/*.py",
            "feishu_agent/providers/**/*.py",
            "feishu_agent/ssh/**/*.py",
        ],
    )


def validate_manifest(manifest: DeployManifest) -> List[str]:
    issues: List[str] = []
    include_set = set(manifest.include_paths)
    local_only_set = set(manifest.local_only_paths)
    overlap = sorted(include_set.intersection(local_only_set))
    if overlap:
        issues.append(f"同步清单与仅本地清单有重叠：{', '.join(overlap)}")
    if not manifest.include_paths:
        issues.append("没有配置任何可同步路径")
    return issues


def manifest_root_path(path_text: str) -> Path:
    return Path(path_text).expanduser().resolve()