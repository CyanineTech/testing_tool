from dataclasses import dataclass
from typing import Optional

from feishu_agent import ws_agent
from feishu_agent.config import Settings, load_settings
from feishu_agent.core.orchestrator import Orchestrator
from feishu_agent.core.session import SessionStore


@dataclass(frozen=True)
class AppComponents:
    settings: Settings
    session_store: SessionStore
    orchestrator: Orchestrator


def build_components(settings: Optional[Settings] = None) -> AppComponents:
    resolved_settings = settings or load_settings()
    session_store = SessionStore()
    orchestrator = Orchestrator(session_store=session_store, settings=resolved_settings)
    configured_orchestrator = ws_agent.configure_runtime(orchestrator)
    return AppComponents(
        settings=resolved_settings,
        session_store=session_store,
        orchestrator=configured_orchestrator,
    )
