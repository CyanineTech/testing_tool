from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple
import os
import logging
import re


try:
    import yaml
except Exception:  # pragma: no cover - yaml import is exercised by tests
    yaml = None  # type: ignore[assignment]


_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SSH_BACKEND_CHOICES = {"cli", "paramiko"}


@dataclass(frozen=True)
class ProviderSettings:
    mode: str = "openai_sdk"
    fallback_mode: str = "copilot_cli"


@dataclass(frozen=True)
class LlmSettings:
    base_url: str = "https://pikachu.claudecode.love"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4.1"
    store_responses: bool = False
    parallel_tool_calls: bool = False
    enable_tool_calls: bool = False


@dataclass(frozen=True)
class SshSettings:
    user: str = "robot"
    timeout_seconds: int = 10
    reject_unknown_host_keys: bool = True
    backend: str = "paramiko"


@dataclass(frozen=True)
class SystemSettings:
    knowledge_root_name: str = "knowledge"
    drafts_root_name: str = "knowledge/_ai_drafts"
    log_root_name: str = "logs"


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    knowledge_root: Path
    prompts_root: Path
    deploy_root: Path
    default_routes: Tuple[str, ...] = ("amr", "network", "rcs")
    provider: ProviderSettings = ProviderSettings()
    llm: LlmSettings = LlmSettings()
    ssh: SshSettings = SshSettings()
    system: SystemSettings = SystemSettings()


def _load_yaml_config(config_path: Path) -> Dict[str, Any]:
    if yaml is None or not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    return payload if isinstance(payload, dict) else {}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_name(value: object, default: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return default
    if _ENV_NAME_RE.fullmatch(candidate):
        return candidate
    logging.warning("invalid env var name in config: %s, falling back to %s", candidate, default)
    return default


def _ssh_backend_name(value: object, default: str = "paramiko") -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return default
    if candidate in _SSH_BACKEND_CHOICES:
        return candidate
    logging.warning("invalid ssh backend in config: %s, falling back to %s", candidate, default)
    return default


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(os.getenv("FEISHU_CONFIG_PATH", str(repo_root / "config.yaml"))).expanduser()
    config = _load_yaml_config(config_path)

    provider_payload = config.get("provider") if isinstance(config.get("provider"), dict) else {}
    llm_payload = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    ssh_payload = config.get("ssh") if isinstance(config.get("ssh"), dict) else {}
    system_payload = config.get("system") if isinstance(config.get("system"), dict) else {}

    provider = ProviderSettings(
        mode=os.getenv("PROVIDER_MODE", str(provider_payload.get("mode", "openai_sdk"))),
        fallback_mode=os.getenv("PROVIDER_FALLBACK_MODE", str(provider_payload.get("fallback_mode", "copilot_cli"))),
    )
    llm = LlmSettings(
        base_url=os.getenv("OPENAI_BASE_URL", str(llm_payload.get("base_url", "https://pikachu.claudecode.love"))),
        api_key_env=_env_name(llm_payload.get("api_key_env"), "OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", str(llm_payload.get("model", "gpt-4.1"))),
        store_responses=_bool_env("OPENAI_STORE_RESPONSES", bool(llm_payload.get("store_responses", False))),
        parallel_tool_calls=_bool_env("OPENAI_PARALLEL_TOOL_CALLS", bool(llm_payload.get("parallel_tool_calls", False))),
        enable_tool_calls=_bool_env("OPENAI_ENABLE_TOOL_CALLS", bool(llm_payload.get("enable_tool_calls", False))),
    )
    ssh = SshSettings(
        user=os.getenv("SSH_USER", str(ssh_payload.get("user", "robot"))),
        timeout_seconds=int(os.getenv("SSH_TIMEOUT_SECONDS", str(ssh_payload.get("timeout_seconds", 10)))),
        reject_unknown_host_keys=_bool_env(
            "SSH_REJECT_UNKNOWN_HOST_KEYS",
            bool(ssh_payload.get("reject_unknown_host_keys", True)),
        ),
        backend=_ssh_backend_name(os.getenv("SSH_BACKEND", ssh_payload.get("backend", "paramiko"))),
    )
    system = SystemSettings(
        knowledge_root_name=str(system_payload.get("knowledge_root", "knowledge")),
        drafts_root_name=str(system_payload.get("drafts_root", "knowledge/_ai_drafts")),
        log_root_name=str(system_payload.get("log_root", "logs")),
    )

    return Settings(
        repo_root=repo_root,
        knowledge_root=repo_root / system.knowledge_root_name,
        prompts_root=repo_root / "prompts",
        deploy_root=repo_root / "feishu_agent" / "deploy",
        provider=provider,
        llm=llm,
        ssh=ssh,
        system=system,
    )
