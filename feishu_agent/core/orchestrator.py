import logging
import copy
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from feishu_agent.config import Settings
from feishu_agent.core.router import CaseContext, extract_case_context, get_conversation_key, needs_clarification
from feishu_agent.core.post_mortem import build_post_mortem_from_result
from feishu_agent.protocols.actions import ACTION_READ_KNOWLEDGE, ACTION_REPORT, ACTION_SECURE_SSH_EXECUTE
from feishu_agent.protocols.schemas import OrchestratorRunResult, ReportResult, TraceEntry
from feishu_agent.core.session import SessionState, SessionStore
from feishu_agent.diagnostics import diagnose_route
from feishu_agent.observability.logger import log_case_end, log_case_start, log_provider_call, log_step
from feishu_agent.providers.base import ProviderRequest
from feishu_agent.providers.manager import ProviderManager
from feishu_agent.knowledge.index import select_relevant_docs
from feishu_agent.knowledge.loader import load_case_docs, load_knowledge_excerpt
from feishu_agent.output.formatter import format_case_report, format_clarification_reply, format_progress_reply
from feishu_agent.playbooks.amr import build_amr_playbook
from feishu_agent.playbooks.base import build_playbook, next_step, Playbook
from feishu_agent.playbooks.network import build_network_playbook
from feishu_agent.playbooks.rcs import build_rcs_playbook
from feishu_agent.ssh.collect import collect_amr_evidence, collect_evidence, collect_network_evidence, collect_rcs_evidence


def _build_doc_evidence(
    route: str,
    doc_paths: List[str],
    docs: Dict[str, str],
    settings: Optional[Settings] = None,
) -> List[str]:
    if not docs:
        return []

    evidence: List[str] = []
    per_doc_chars = int(os.getenv("FEISHU_DOC_EVIDENCE_CHARS", "320"))
    max_docs = int(os.getenv("FEISHU_DOC_EVIDENCE_COUNT", "20" if route == "knowledge" else "6"))
    selected_paths = doc_paths[:max_docs]

    if selected_paths:
        evidence.append("knowledge_candidates: " + ", ".join(selected_paths))

    for doc_path in selected_paths:
        content = docs.get(doc_path, "")
        if not content:
            continue
        excerpt, error = load_knowledge_excerpt(doc_path, max_chars=per_doc_chars, max_lines=8, settings=settings)
        if error:
            continue
        if excerpt:
            evidence.append(f"doc_excerpt[{doc_path}]: {excerpt}")

    return evidence


def _extract_prefixed_doc_paths(evidence: Sequence[str], prefix: str) -> List[str]:
    selected: List[str] = []
    for item in evidence:
        line = str(item).strip()
        if not line.startswith(prefix):
            continue
        payload = line[len(prefix):].strip()
        if prefix.endswith("["):
            end = payload.find("]")
            if end < 0:
                continue
            payload = payload[:end].strip()
        for doc_path in [part.strip() for part in payload.split(",") if part.strip()]:
            if doc_path not in selected:
                selected.append(doc_path)
    return selected


def _split_doc_tracking(evidence: Sequence[str], fallback_candidates: Sequence[str]) -> Tuple[List[str], List[str]]:
    candidate_docs = _extract_prefixed_doc_paths(evidence, "knowledge_candidates: ")
    if not candidate_docs:
        candidate_docs = list(fallback_candidates)
    read_docs = _extract_prefixed_doc_paths(evidence, "knowledge_read[")
    return candidate_docs, read_docs


def _provider_action_event_evidence(action_events: Sequence[object]) -> Tuple[List[str], List[str]]:
    evidence_lines: List[str] = []
    read_docs: List[str] = []

    for event in action_events:
        action_type = str(getattr(event, "type", "") or "")
        payload = getattr(event, "payload", {}) or {}
        if not isinstance(payload, dict):
            continue

        if action_type == ACTION_READ_KNOWLEDGE:
            path = str(payload.get("path") or "").strip()
            excerpt = str(payload.get("excerpt") or "").strip()
            if path:
                if path not in read_docs:
                    read_docs.append(path)
                evidence_lines.append(f"knowledge_read[{path}]: {excerpt[:400]}")
            continue

        if action_type == ACTION_SECURE_SSH_EXECUTE:
            command = str(payload.get("command") or "").strip()
            stdout = str(payload.get("stdout") or "").strip()
            stderr = str(payload.get("stderr") or "").strip()
            preview = stdout or stderr
            if command and preview:
                evidence_lines.append(f"provider_execute[{command}]: {preview[:400]}")
            continue

        if action_type == ACTION_REPORT:
            summary = str(payload.get("summary") or "").strip()
            if summary:
                evidence_lines.append(f"provider_report: {summary[:400]}")

    return evidence_lines, read_docs


def _build_trace_entries(
    *,
    route: str,
    target: str,
    docs: Sequence[str],
    executed: Sequence[Dict[str, object]],
    provider_name: str,
    provider_confidence: str,
    provider_action_events: Sequence[object],
) -> List[Dict[str, object]]:
    trace: List[Dict[str, object]] = []

    if docs:
        trace.append(
            {
                "type": "knowledge_candidates",
                "route": route,
                "target": target,
                "count": len(docs),
                "items": list(docs),
            }
        )

    for item in executed:
        trace.append(
            {
                "type": "local_execution",
                "route": route,
                "target": target,
                "command": str(item.get("command", "")),
                "returncode": item.get("returncode", ""),
            }
        )

    for event in provider_action_events:
        trace.append(
            {
                "type": "provider_action",
                "route": route,
                "target": target,
                "provider": provider_name,
                "provider_confidence": provider_confidence,
                "action_type": str(getattr(event, "type", "") or ""),
                "action_id": str(getattr(event, "action_id", "") or ""),
                "payload": dict(getattr(event, "payload", {}) or {}),
            }
        )

    return trace


def _build_trace_entries_structured(
    *,
    route: str,
    target: str,
    docs: Sequence[str],
    executed: Sequence[Dict[str, object]],
    provider_name: str,
    provider_confidence: str,
    provider_action_events: Sequence[object],
) -> List[TraceEntry]:
    raw_entries = _build_trace_entries(
        route=route,
        target=target,
        docs=docs,
        executed=executed,
        provider_name=provider_name,
        provider_confidence=provider_confidence,
        provider_action_events=provider_action_events,
    )
    structured: List[TraceEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        trace_type = str(raw_entry.get("type", "") or "")
        details = dict(raw_entry)
        details.pop("type", None)
        route_value = str(details.pop("route", "") or route)
        target_value = str(details.pop("target", "") or target)
        provider_value = str(details.pop("provider", "") or provider_name)
        provider_confidence_value = str(details.pop("provider_confidence", "") or provider_confidence)
        action_type_value = str(details.pop("action_type", "") or "")
        details["type"] = trace_type
        details["route"] = route_value
        details["target"] = target_value
        details["provider"] = provider_value
        details["provider_confidence"] = provider_confidence_value
        details["action_type"] = action_type_value
        details["success"] = True
        structured.append(TraceEntry.from_mapping(details))
    return structured


def _pty_route_active(route: str) -> bool:
    if os.getenv("COPILOTCLI_ENABLE_PTY_PROTOCOL", "0") != "1":
        return False
    enabled_routes = {
        item.strip()
        for item in os.getenv("COPILOTCLI_PTY_ROUTES", "").split(",")
        if item.strip()
    }
    return route in enabled_routes


def _format_provider_context(playbook: Playbook, step_index: int, target: str, compact: bool) -> str:
    if compact:
        return "\n".join(
            [
                f"已收到：{playbook.title}",
                f"目标：{target or '未指定'}",
                next_step(playbook, step_index),
            ]
        )
    return format_progress_reply(playbook, step_index, include_first_check=False)


def _compact_provider_evidence(evidence: Sequence[str], compact: bool) -> List[str]:
    cleaned = [str(item).strip() for item in evidence if str(item).strip()]
    if not compact:
        return cleaned

    max_items = int(os.getenv("FEISHU_PTY_PROVIDER_EVIDENCE_COUNT", "3"))
    knowledge_candidates = [item for item in cleaned if item.startswith("knowledge_candidates:")]
    doc_excerpts = [item for item in cleaned if item.startswith("doc_excerpt[")]
    remote_observations = [item for item in cleaned if item.startswith("remote[")]
    others = [
        item
        for item in cleaned
        if item not in knowledge_candidates and item not in doc_excerpts and item not in remote_observations
    ]

    compact_items: List[str] = []
    if knowledge_candidates:
        compact_items.append(knowledge_candidates[0])
    payload_budget = max_items
    for item in remote_observations:
        if len(compact_items) - len(knowledge_candidates[:1]) >= payload_budget:
            break
        compact_items.append(item)
    if doc_excerpts and len(compact_items) - len(knowledge_candidates[:1]) < payload_budget and not remote_observations:
        compact_items.append(doc_excerpts[0])
    for item in others:
        if len(compact_items) - len(knowledge_candidates[:1]) >= payload_budget:
            break
        compact_items.append(item)
    return compact_items[: payload_budget + (1 if knowledge_candidates else 0)]


def _minimal_amr_prefetch_commands(text: str) -> List[str]:
    normalized = (text or "").lower()
    commands: List[str] = []
    if "/low_level_error" in normalized or "low_level_error" in normalized:
        commands.append("rostopic echo /low_level_error -n1")
    if "rosnode" in normalized:
        commands.append("rosnode list")
    return commands


def _format_remote_prefetch_evidence(command_text: str, stdout: str, stderr: str, returncode: Optional[int]) -> str:
    command_text = (command_text or "").strip()
    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    combined = "\n".join(part for part in [stdout, stderr] if part).strip()
    lowered_stderr = stderr.lower()

    if command_text == "rosnode list":
        if stdout:
            nodes = [line.strip() for line in stdout.splitlines() if line.strip()]
            sample = ", ".join(nodes[:4])
            return f"remote[{command_text}]: rosnode list 成功，检测到 {len(nodes)} 个节点；示例: {sample}"
        if stderr:
            return f"remote[{command_text}]: rosnode list 执行失败: {stderr[:240]}"
        if returncode not in (None, 0):
            return f"remote[{command_text}]: rosnode list 执行失败，返回码 {returncode}"
        return ""

    if command_text == "rostopic echo /low_level_error -n1":
        if stdout:
            preview = " ".join(line.strip() for line in stdout.splitlines() if line.strip())
            return f"remote[{command_text}]: /low_level_error 已读到实时消息: {preview[:240]}"
        if "does not appear to be published yet" in lowered_stderr:
            return f"remote[{command_text}]: /low_level_error 当前未发布，暂未读到实时错误消息"
        if "command timed out" in lowered_stderr:
            return f"remote[{command_text}]: /low_level_error 命令已超时结束，当前未读到单条错误消息"
        if stderr:
            return f"remote[{command_text}]: /low_level_error 检查失败: {stderr[:240]}"
        if returncode not in (None, 0):
            return f"remote[{command_text}]: /low_level_error 检查失败，返回码 {returncode}"
        return ""

    if combined:
        return f"remote[{command_text}]: {combined[:400]}"
    if returncode not in (None, 0):
        return f"remote[{command_text}]: 返回码 {returncode}"
    return ""


def _format_knowledge_reply(provider_summary: str) -> str:
    try:
        payload = json.loads(provider_summary)
    except Exception:
        return provider_summary

    if not isinstance(payload, dict):
        return provider_summary

    summary = str(payload.get("summary") or "").strip()
    root_cause = str(payload.get("root_cause") or "").strip()
    severity = str(payload.get("severity") or "").strip()
    next_steps = [str(item).strip() for item in payload.get("next_steps") or [] if str(item).strip()]

    lines: List[str] = []
    if summary:
        lines.append(summary)
    if root_cause:
        lines.append(f"说明：{root_cause}")
    if severity:
        lines.append(f"级别：{severity}")
    if next_steps:
        lines.append("建议阅读顺序：")
        for index, item in enumerate(next_steps, start=1):
            lines.append(f"{index}. {item}")

    return "\n".join(lines) or provider_summary


def _format_provider_reply(
    *,
    route: str,
    summary: str,
    root_cause: str,
    severity: str,
    next_steps: List[str],
) -> str:
    route_titles = {
        "amr": "AMR 机器人问题",
        "network": "网络问题",
        "rcs": "RCS 系统问题",
    }

    lines: List[str] = [f"已收到：{route_titles.get(route, '排障问题')}"]
    clean_summary = summary.strip()
    clean_root_cause = root_cause.strip()
    clean_severity = severity.strip()
    clean_next_steps = [item.strip() for item in next_steps if str(item).strip()]

    if clean_summary:
        lines.append(f"摘要：{clean_summary}")
    if clean_root_cause:
        lines.append(f"根因判断：{clean_root_cause}")
    if clean_severity:
        lines.append(f"严重程度：{clean_severity}")
    if clean_next_steps:
        lines.append("建议下一步：")
        for index, item in enumerate(clean_next_steps, start=1):
            lines.append(f"{index}. {item}")

    return "\n".join(lines)

def _provider_reply_title(route: str) -> str:
    return {
        "amr": "AMR 机器人问题",
        "network": "网络问题",
        "rcs": "RCS 系统问题",
    }.get(route, "排障问题")


def _is_brief_follow_up_text(text: str) -> bool:
    stripped = text.strip()
    return stripped in {"继续", "继续下一步", "下一步", "接着查", "再往下", "然后呢", "怎么查", "查什么", "再看"}


def _should_force_local_diag_on_follow_up(session: SessionState, route: str, request_text: str) -> bool:
    if route not in {"amr", "network", "rcs"}:
        return False
    if not _is_brief_follow_up_text(request_text):
        return False

    last_report = (session.last_report or "").strip()
    return "Copilot 月度额度已用尽" in last_report or "copilot_quota_exhausted" in "\n".join(session.evidence)


def _build_auto_diag_ack_for_plan(route: str, target: str, previous_state: Dict[str, object]) -> str:
    previous_route = str(previous_state.get("route") or "")
    previous_step_index = int(previous_state.get("step_index") or 0)
    if previous_route == route and previous_step_index >= 0:
        step_label = previous_step_index + 1
        if target:
            return f"已收到：{route.upper()} {target}，正在继续上一条会话第 {step_label} 步排障，请稍等。"
        return f"已收到：{route.upper()} 问题，正在继续上一条会话第 {step_label} 步排障，请稍等。"
    if target:
        return f"已收到：{route.upper()} {target}，正在执行本地排障，请稍等。"
    return f"已收到：{route.upper()} 问题，正在执行本地排障，请稍等。"

@dataclass(frozen=True)
class CaseRequest:
    text: str
    payload: Dict[str, object]
    sender_open_id: str
    sender_display_name: str
    message_id: str


@dataclass(frozen=True)
class CaseResponse:
    reply_text: str
    route: str
    target: str
    time_key: str
    conversation_key: str
    step_index: int
    reply_kind: str = "text"
    report_result: Optional[ReportResult] = None
    trace: List[Dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_run_result(cls, result: OrchestratorRunResult) -> "CaseResponse":
        trace_payload = [
            {
                "timestamp": item.timestamp,
                "type": item.type,
                "route": item.route,
                "target": item.target,
                "provider": item.provider,
                "provider_confidence": item.provider_confidence,
                "action_type": item.action_type,
                "success": item.success,
                **dict(item.details or {}),
            }
            for item in result.trace
        ]
        return cls(
            reply_text=result.final_answer,
            route=result.route,
            target=result.target,
            time_key=result.time_key,
            conversation_key=result.conversation_key,
            step_index=result.step_index,
            reply_kind=result.reply_kind,
            report_result=result.report_result,
            trace=trace_payload,
        )


@dataclass(frozen=True)
class DispatchPlan:
    route: str
    target: str
    time_key: str
    conversation_key: str
    should_ack: bool
    ack_text: str = ""
    should_background: bool = False
    requires_worker: bool = False


class Orchestrator:
    def __init__(self, session_store: Optional[SessionStore] = None, settings: Optional[Settings] = None) -> None:
        self.session_store = session_store or SessionStore()
        self.settings = settings
        self.provider_manager = ProviderManager(settings=settings)

    def _build_playbook(self, route: str) -> Playbook:
        if route == "knowledge":
            return build_playbook("knowledge")
        if route == "amr":
            return build_amr_playbook()
        if route == "network":
            return build_network_playbook()
        if route == "rcs":
            return build_rcs_playbook()
        return build_playbook("unknown")

    def _resolve_domain(self, route: str) -> str:
        if route in {"knowledge", "amr", "network", "rcs"}:
            return route
        return "unknown"

    def _resolve_sop_path(self, route: str, report_result: Optional[ReportResult]) -> str:
        if report_result and report_result.knowledge_used:
            first_known_doc = str(report_result.knowledge_used[0]).strip()
            if first_known_doc:
                return first_known_doc

        playbook = self._build_playbook(route)
        if playbook.docs:
            return playbook.docs[0]
        return "knowledge/README.md"

    def _build_run_messages(
        self,
        *,
        request: CaseRequest,
        route: str,
        target: str,
        sop_path: str,
        domain: str,
        report_result: Optional[ReportResult],
        final_answer: str,
    ) -> List[Dict[str, str]]:
        playbook = self._build_playbook(route)
        system_lines = [
            f"domain: {domain}",
            f"route: {route}",
            f"sop_path: {sop_path}",
            f"target: {target or '未指定'}",
            f"playbook: {playbook.title}",
            f"playbook_summary: {playbook.summary}",
        ]
        if report_result:
            system_lines.append(f"report_summary: {report_result.summary}")
            system_lines.append(f"report_root_cause: {report_result.root_cause}")

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "\n".join(system_lines)},
            {"role": "user", "content": request.text},
            {"role": "assistant", "content": final_answer},
        ]
        return messages

    def _build_run_trace(self, trace: Sequence[Dict[str, object]]) -> List[TraceEntry]:
        structured_trace: List[TraceEntry] = []
        for item in trace:
            if isinstance(item, dict):
                structured_trace.append(TraceEntry.from_mapping(item))
        return structured_trace

    def _assemble_run_result(
        self,
        *,
        request: CaseRequest,
        reply_text: str,
        route: str,
        target: str,
        time_key: str,
        conversation_key: str,
        step_index: int,
        reply_kind: str,
        report_result: Optional[ReportResult],
        trace: Sequence[Dict[str, object]],
    ) -> OrchestratorRunResult:
        sop_path = self._resolve_sop_path(route, report_result)
        domain = self._resolve_domain(route)
        messages = self._build_run_messages(
            request=request,
            route=route,
            target=target,
            sop_path=sop_path,
            domain=domain,
            report_result=report_result,
            final_answer=reply_text,
        )
        structured_trace = self._build_run_trace(trace)
        draft_result = None
        base_result = OrchestratorRunResult(
            final_answer=reply_text,
            messages=messages,
            trace=structured_trace,
            sop_path=sop_path,
            domain=domain,
            reply_kind=reply_kind,
            route=route,
            target=target,
            time_key=time_key,
            conversation_key=conversation_key,
            step_index=step_index,
            report_result=report_result,
        )
        if reply_kind == "progress":
            try:
                draft_result = build_post_mortem_from_result(base_result, settings=self.settings)
            except Exception:
                logging.exception("post mortem generation failed route=%s target=%s", route, target)
                draft_result = None
        if draft_result is None:
            return base_result
        return OrchestratorRunResult(
            final_answer=base_result.final_answer,
            messages=base_result.messages,
            trace=base_result.trace,
            sop_path=base_result.sop_path,
            domain=base_result.domain,
            reply_kind=base_result.reply_kind,
            route=base_result.route,
            target=base_result.target,
            time_key=base_result.time_key,
            conversation_key=base_result.conversation_key,
            step_index=base_result.step_index,
            report_result=base_result.report_result,
            draft_result=draft_result,
        )

    def _finalize_case(self, request: CaseRequest) -> OrchestratorRunResult:
        session_ttl_seconds = int(os.getenv("FEISHU_SESSION_TTL_SECONDS", "21600"))
        self.session_store.prune_expired(session_ttl_seconds)
        session_snapshot = self.session_store.get(
            get_conversation_key(request.payload, request.sender_open_id)
        )
        enriched_payload = copy.deepcopy(request.payload)
        event = enriched_payload.setdefault("event", {})
        message = event.setdefault("message", {})
        message["state"] = {
            "route": session_snapshot.route,
            "target": session_snapshot.target,
            "time_key": session_snapshot.time_key,
            "step_index": session_snapshot.step_index,
        }

        context: CaseContext = extract_case_context(request.text, enriched_payload, request.sender_open_id)
        session = self.session_store.get(context.conversation_key)

        route = context.route if context.route in {"knowledge", "amr", "network", "rcs"} else "unknown"
        log_case_start(route, context.target or "", request.message_id)
        if route == "unknown":
            reply_text = format_clarification_reply(route, context.missing_fields)
            self.session_store.update(
                context.conversation_key,
                route=route,
                target=context.target,
                time_key=context.time_key,
                step_index=0,
                last_report=reply_text,
                last_reply_kind="clarification",
                last_payload=request.payload,
            )
            log_case_end(route, context.target or "", [])
            return self._assemble_run_result(
                request=request,
                reply_text=reply_text,
                route=route,
                target=context.target,
                time_key=context.time_key,
                conversation_key=context.conversation_key,
                step_index=0,
                reply_kind="clarification",
                report_result=None,
                trace=[],
            )

        if route in {"amr", "network"} and not context.target and not session.target:
            reply_text = format_clarification_reply(route, context.missing_fields)
            self.session_store.update(
                context.conversation_key,
                route=route,
                target="",
                time_key=context.time_key,
                step_index=0,
                last_report=reply_text,
                last_reply_kind="clarification",
                last_payload=request.payload,
            )
            log_case_end(route, context.target or "", [])
            return self._assemble_run_result(
                request=request,
                reply_text=reply_text,
                route=route,
                target="",
                time_key=context.time_key,
                conversation_key=context.conversation_key,
                step_index=0,
                reply_kind="clarification",
                report_result=None,
                trace=[],
            )

        playbook = self._build_playbook(route)
        max_candidate_docs = int(os.getenv("FEISHU_TOPK_DOCS", "8"))
        combined_docs = select_relevant_docs(request.text, route, limit=max_candidate_docs)
        docs = load_case_docs(combined_docs, settings=self.settings)
        doc_evidence = _build_doc_evidence(route, combined_docs, docs, settings=self.settings)
        if context.is_follow_up and session.route == route:
            step_index = session.step_index + 1
        else:
            step_index = 0

        reply_text = format_progress_reply(playbook, step_index, docs_override=combined_docs)
        evidence: List[str] = []
        executed: List[Dict[str, object]] = []
        final_severity = "待确认"
        final_root_cause = "当前基于知识库与上下文进行排障"
        provider_summary = ""
        provider_name = ""
        provider_confidence = ""
        provider_root_cause = ""
        provider_severity = ""
        provider_next_steps: List[str] = []
        provider_evidence: List[str] = []
        provider_user_visible = False
        provider_action_events: List[object] = []
        effective_time_key = context.time_key or session.time_key
        historical_amr_diag_enabled = route == "amr" and bool(effective_time_key)
        force_local_diag_follow_up = _should_force_local_diag_on_follow_up(session, route, request.text)
        auto_diag_enabled = (
            os.getenv("FEISHU_ENABLE_LOCAL_DIAG", "0") == "1"
            or historical_amr_diag_enabled
            or force_local_diag_follow_up
        )
        if auto_diag_enabled:
            diag_report = diagnose_route(route, request.text, context.target or session.target or None, effective_time_key or None)
            if diag_report.get("need_more_info"):
                reply_text = format_clarification_reply(route, [])
                self.session_store.update(
                    context.conversation_key,
                    route=route,
                    target=context.target or session.target or "",
                    time_key=context.time_key or session.time_key,
                    step_index=0,
                    evidence=evidence,
                    last_report=reply_text,
                    last_doc_candidates=combined_docs,
                    last_read_docs=[],
                    last_docs=combined_docs,
                    last_reply_kind="clarification",
                    last_payload=request.payload,
                )
                log_step(route, 0, reply_text)
                log_case_end(route, context.target or session.target, evidence)
                return self._assemble_run_result(
                    request=request,
                    reply_text=reply_text,
                    route=route,
                    target=context.target or session.target or "",
                    time_key=context.time_key or session.time_key,
                    conversation_key=context.conversation_key,
                    step_index=0,
                    reply_kind="clarification",
                    report_result=None,
                    trace=[],
                )
            executed = list(diag_report.get("executed", []))
            final_severity = str(diag_report.get("severity", "警告"))
            final_root_cause = str(diag_report.get("root_cause", "未明确"))
            evidence.append(f"local_diag_summary: severity={final_severity}; root_cause={final_root_cause}")
            if executed:
                executed_preview = "; ".join(
                    f"{str(item.get('command', ''))} (rc={item.get('returncode', '')})"
                    for item in executed[:4]
                )
                if executed_preview:
                    evidence.append(f"local_diag_executed: {executed_preview}")
            diag_evidence = str(diag_report.get("evidence") or "").strip()
            if diag_evidence:
                evidence.append(diag_evidence[:800])

        for item in doc_evidence:
            if item:
                evidence.append(item)

        if _pty_route_active(route) and route == "amr" and context.target:
            prefetch_commands = _minimal_amr_prefetch_commands(request.text)
            if prefetch_commands:
                remote_report = collect_evidence(
                    route,
                    context.target,
                    commands=prefetch_commands,
                    settings=self.settings,
                )
                for item in remote_report.get("results", []):
                    command_text = (getattr(item, "command", "") or "").strip()
                    stdout = (getattr(item, "stdout", "") or "").strip()
                    stderr = (getattr(item, "stderr", "") or "").strip()
                    returncode = getattr(item, "returncode", None)
                    preview = _format_remote_prefetch_evidence(command_text, stdout, stderr, returncode)
                    if preview:
                        evidence.append(preview)

        if os.getenv("FEISHU_ENABLE_REMOTE_COLLECT", "0") == "1" and context.target:
            if route == "amr":
                remote_report = collect_amr_evidence(context.target, settings=self.settings)
            elif route == "network":
                remote_report = collect_network_evidence(context.target, settings=self.settings)
            else:
                remote_report = collect_rcs_evidence(context.target, settings=self.settings)
            for item in remote_report.get("results", []):
                stdout = (getattr(item, "stdout", "") or "").strip()
                stderr = (getattr(item, "stderr", "") or "").strip()
                preview = stdout or stderr
                if preview:
                    evidence.append(preview[:400])

        provider_review_enabled = (
            os.getenv("FEISHU_ENABLE_PROVIDER_REVIEW", "0") == "1" or self.provider_manager.select_provider() is not None
        )
        if provider_review_enabled and not force_local_diag_follow_up:
            provider_question = request.text
            compact_provider_input = _pty_route_active(route)
            provider_context = _format_provider_context(
                playbook,
                step_index,
                context.target or session.target or "",
                compact=compact_provider_input,
            )
            provider_request_evidence = _compact_provider_evidence(evidence, compact=compact_provider_input)
            if context.is_follow_up and session.route == route:
                if _is_brief_follow_up_text(request.text):
                    follow_up_docs = session.last_read_docs or session.last_doc_candidates or combined_docs
                    provider_question = f"按当前步骤继续排查：{next_step(playbook, step_index)}"
                    provider_context = "\n".join(
                        [
                            f"已收到：{_provider_reply_title(route)}",
                            next_step(playbook, step_index),
                            f"目标：{context.target or session.target or '未指定'}",
                            f"已读取文档：{'、'.join(follow_up_docs[:4])}" if follow_up_docs else "已读取文档：无",
                        ]
                    )
                    provider_request_evidence = _compact_provider_evidence(
                        evidence[:4],
                        compact=compact_provider_input,
                    )
                else:
                    previous_report = (session.last_report or "").strip()
                    if previous_report and "超时后已终止" not in previous_report:
                        provider_context = f"{provider_context}\n\n上一轮回复：\n{previous_report[:400]}"
                    for item in session.evidence[:2]:
                        cleaned_item = str(item).strip()
                        if cleaned_item:
                            provider_request_evidence.append(f"previous_evidence: {cleaned_item[:200]}")
            provider_result = self.provider_manager.run_review(
                ProviderRequest(
                    route=route,
                    question=provider_question,
                    context=provider_context,
                    evidence=provider_request_evidence,
                    target=context.target or session.target,
                )
            )
            log_provider_call(provider_result.provider_name, route)
            fallback_provider_summary = (provider_result.summary or "").strip()
            provider_user_visible = not (
                provider_result.confidence == "low"
                and fallback_provider_summary in {
                    "copilotcli 超时后已终止。",
                    "copilotcli 未返回结果。",
                    "copilotcli 未返回可解析诊断结果。",
                }
            )
            if provider_user_visible:
                provider_name = provider_result.provider_name
                provider_confidence = provider_result.confidence
                provider_root_cause = provider_result.root_cause
                provider_severity = provider_result.severity
                provider_next_steps = list(provider_result.next_steps)
                provider_evidence = list(provider_result.evidence)
                provider_action_events = list(provider_result.action_events)
                if provider_result.summary:
                    provider_summary = provider_result.summary if route == "knowledge" else provider_result.summary[:500]
            local_evidence_insufficient = any(token in final_root_cause for token in ("无法", "不足", "未找到"))
            if provider_result.root_cause and (
                final_root_cause == "当前基于知识库与上下文进行排障"
                or provider_result.confidence == "high"
                or (provider_result.confidence == "medium" and not local_evidence_insufficient)
            ):
                final_root_cause = provider_result.root_cause
            if provider_result.severity and (final_severity == "待确认" or provider_result.severity in {"错误", "严重"}):
                final_severity = provider_result.severity
            action_event_evidence, action_event_read_docs = _provider_action_event_evidence(provider_result.action_events)
            for item in action_event_evidence:
                cleaned_item = str(item).strip()
                if cleaned_item:
                    evidence.append(cleaned_item[:400])
            if provider_user_visible:
                for item in provider_evidence:
                    cleaned_item = str(item).strip()
                    if cleaned_item:
                        evidence.append(cleaned_item[:400])

        if route == "knowledge" and not auto_diag_enabled and provider_summary:
            reply_text = _format_knowledge_reply(provider_summary)
        elif route in {"amr", "network", "rcs"} and not auto_diag_enabled:
            provider_reply = _format_provider_reply(
                route=route,
                summary=provider_summary,
                root_cause=provider_root_cause,
                severity=provider_severity,
                next_steps=provider_next_steps,
            )
            if provider_reply.strip() != f"已收到：{_provider_reply_title(route)}":
                reply_text = provider_reply

        if auto_diag_enabled:
            reply_text = format_case_report(
                route=route,
                target=context.target or session.target or "",
                severity=final_severity,
                root_cause=final_root_cause,
                executed=executed,
                evidence=evidence,
                docs=combined_docs,
                read_docs=_extract_prefixed_doc_paths(evidence, "knowledge_read["),
                provider_summary=provider_summary,
                provider_name=provider_name,
                provider_confidence=provider_confidence,
                provider_root_cause=provider_root_cause,
                provider_severity=provider_severity,
                provider_next_steps=provider_next_steps,
                provider_evidence=provider_evidence,
            )

        session_doc_candidates, session_read_docs = _split_doc_tracking(evidence, combined_docs)
        trace = _build_trace_entries(
            route=route,
            target=context.target or session.target or "",
            docs=combined_docs,
            executed=executed,
            provider_name=provider_name,
            provider_confidence=provider_confidence,
            provider_action_events=provider_action_events,
        )
        report_summary = provider_summary.strip() if provider_summary.strip() else final_root_cause[:160]
        report_result = ReportResult(
            summary=report_summary,
            root_cause=final_root_cause,
            severity=final_severity,
            next_steps=list(provider_next_steps),
            evidence=[str(item) for item in evidence[-8:]],
            confidence=0.0,
            human_intervention_required=final_severity in {"错误", "严重"},
            knowledge_used=list(session_read_docs),
            commands_used=[str(item.get("command", "")) for item in executed if str(item.get("command", "")).strip()],
        )

        self.session_store.update(
            context.conversation_key,
            route=route,
            target=context.target or session.target,
            time_key=context.time_key or session.time_key,
            step_index=step_index,
            evidence=evidence,
            last_report=reply_text,
            last_doc_candidates=session_doc_candidates,
            last_read_docs=session_read_docs,
            last_docs=combined_docs,
            last_reply_kind="progress",
            last_payload=request.payload,
        )
        log_step(route, step_index, reply_text)
        log_case_end(route, context.target or session.target, evidence)

        _ = docs
        return self._assemble_run_result(
            request=request,
            reply_text=reply_text,
            route=route,
            target=context.target or session.target,
            time_key=context.time_key or session.time_key,
            conversation_key=context.conversation_key,
            step_index=step_index,
            reply_kind="progress",
            report_result=report_result,
            trace=trace,
        )

    def build_dispatch_plan(
        self,
        *,
        route: str,
        target: str,
        time_key: str,
        conversation_key: str,
        previous_state: Dict[str, object],
    ) -> DispatchPlan:
        auto_diag_enabled = os.getenv("FEISHU_ENABLE_LOCAL_DIAG", "0") == "1"
        background_processing_enabled = any(
            os.getenv(env_name, "0") == "1"
            for env_name in (
                "FEISHU_BACKGROUND_CASE_PROCESSING",
                "FEISHU_ENABLE_PROVIDER_REVIEW",
                "FEISHU_ENABLE_LOCAL_DIAG",
                "FEISHU_ENABLE_REMOTE_COLLECT",
            )
        )

        if auto_diag_enabled and route in {"amr", "network"} and not target:
            return DispatchPlan(
                route=route,
                target=target,
                time_key=time_key,
                conversation_key=conversation_key,
                should_ack=False,
                should_background=background_processing_enabled,
                requires_worker=True,
            )

        if auto_diag_enabled and route in {"amr", "network", "rcs"}:
            return DispatchPlan(
                route=route,
                target=target,
                time_key=time_key,
                conversation_key=conversation_key,
                should_ack=True,
                ack_text=_build_auto_diag_ack_for_plan(route, target, previous_state),
                should_background=background_processing_enabled,
                requires_worker=True,
            )

        return DispatchPlan(
            route=route,
            target=target,
            time_key=time_key,
            conversation_key=conversation_key,
            should_ack=False,
            should_background=background_processing_enabled,
            requires_worker=True,
        )

    def handle_case(self, request: CaseRequest) -> CaseResponse:
        return CaseResponse.from_run_result(self.run(request))

    def run(self, request: CaseRequest) -> OrchestratorRunResult:
        return self._finalize_case(request)
