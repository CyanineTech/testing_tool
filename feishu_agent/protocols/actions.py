from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4


ACTION_READ_KNOWLEDGE = "read_knowledge"
ACTION_SECURE_SSH_EXECUTE = "secure_ssh_execute"
ACTION_REPORT = "report"

_VALID_ACTION_TYPES = {
    ACTION_READ_KNOWLEDGE,
    ACTION_SECURE_SSH_EXECUTE,
    ACTION_REPORT,
}


def is_valid_action_type(action_type: str) -> bool:
    return action_type in _VALID_ACTION_TYPES


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ActionEvent:
    type: str
    source: str
    payload: Dict[str, Any]
    action_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        if not is_valid_action_type(self.type):
            raise ValueError(f"unsupported action type: {self.type}")


def build_action_event(*, action_type: str, source: str, payload: Dict[str, Any]) -> ActionEvent:
    return ActionEvent(
        type=action_type,
        source=source,
        payload=dict(payload),
    )
