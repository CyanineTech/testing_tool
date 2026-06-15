from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized not in {"", "0", "false", "no", "none"}


@dataclass(frozen=True)
class RouteResult:
    domain: str
    sop_path: str
    sop_text: str
    matched_keywords: List[str] = field(default_factory=list)
    route_reason: str = ""


@dataclass(frozen=True)
class TraceEntry:
    timestamp: str
    type: str
    route: str
    target: str
    provider: str = ""
    provider_confidence: str = ""
    action_type: str = ""
    success: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TraceEntry":
        data = dict(payload)
        timestamp = str(data.pop("timestamp", "") or _utc_now_iso())
        trace_type = str(data.pop("type", "") or data.pop("kind", "") or "")
        route = str(data.pop("route", "") or "")
        target = str(data.pop("target", "") or "")
        provider = str(data.pop("provider", "") or "")
        provider_confidence = str(data.pop("provider_confidence", "") or "")
        action_type = str(data.pop("action_type", "") or "")
        success = _coerce_bool(data.pop("success", True))
        return cls(
            timestamp=timestamp,
            type=trace_type,
            route=route,
            target=target,
            provider=provider,
            provider_confidence=provider_confidence,
            action_type=action_type,
            success=success,
            details=data,
        )


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    type: str
    command: str
    stdout: str
    stderr: str
    return_code: int
    duration_ms: int
    provider: str
    matched_rule: str = ""
    host: str = ""
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class ReportResult:
    summary: str
    root_cause: str
    severity: str
    next_steps: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    human_intervention_required: bool = False
    knowledge_used: List[str] = field(default_factory=list)
    commands_used: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DraftResult:
    draft_path: str
    title: str
    source_sop: str
    created_at: str = field(default_factory=_utc_now_iso)


@dataclass(frozen=True)
class OrchestratorRunResult:
    final_answer: str
    messages: List[Dict[str, str]]
    trace: List[TraceEntry]
    sop_path: str
    domain: str
    reply_kind: str = "text"
    route: str = ""
    target: str = ""
    time_key: str = ""
    conversation_key: str = ""
    step_index: int = 0
    report_result: Optional[ReportResult] = None
    draft_result: Optional[DraftResult] = None

    @property
    def reply_text(self) -> str:
        return self.final_answer

    def to_conversation_state(self) -> Dict[str, str]:
        draft_path = ""
        if self.draft_result is not None:
            draft_path = str(self.draft_result.draft_path or "")

        return {
            "route": self.route,
            "target": self.target,
            "time_key": self.time_key,
            "step_index": self.step_index,
            "reply_kind": self.reply_kind,
            "domain": self.domain,
            "sop_path": self.sop_path,
            "draft_path": draft_path,
        }
