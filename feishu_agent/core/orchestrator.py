import logging
import copy
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from feishu_agent.config import Settings
from feishu_agent.core.router import CaseContext, extract_case_context, get_conversation_key, needs_clarification
from feishu_agent.core.post_mortem import build_post_mortem_from_result
from feishu_agent.protocols.actions import ACTION_READ_KNOWLEDGE, ACTION_REPORT, ACTION_SECURE_SSH_EXECUTE
from feishu_agent.protocols.schemas import OrchestratorRunResult, ReportResult, TraceEntry
from feishu_agent.core.session import SessionState, SessionStore
from feishu_agent.diagnostics import diagnose_route, extract_exact_time_anchor, extract_time_window, is_historical_rcs_request
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


def _format_follow_up_guardrail(previous_target: str, explicit_target: str) -> str:
    if previous_target and explicit_target and explicit_target != previous_target:
        return f"本轮文本出现了新的明确目标：{explicit_target}，仅当它是 IP 或主机名时才切换。"
    if previous_target:
        return (
            "本轮是同一会话的继续排查，默认沿用上一轮目标，不要因为出现 supervisor、mysql、"
            "backend、redis 这类症状词而切换目标。"
        )
    return "本轮是同一会话的继续排查，若未给出新的 IP 或主机名，请先沿用当前会话目标。"


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


def _should_collect_deeper_rcs_evidence(route: str, evidence: Sequence[str], request_text: str) -> bool:
    if route != "rcs":
        return False
    combined = "\n".join(str(item).strip() for item in evidence if str(item).strip())
    text = f"{request_text}\n{combined}".lower()
    return any(
        token in text
        for token in (
            "supervisor 未运行",
            "mysql 异常",
            "http状态码: 000",
            "后端 api 无响应",
            "死机",
            "重启才恢复",
        )
    )


def _should_collect_deeper_amr_evidence(route: str, request_text: str, root_cause: str) -> bool:
    if route != "amr":
        return False
    if extract_exact_time_anchor(request_text) or extract_time_window(request_text):
        return True
    normalized = f"{request_text}\n{root_cause}".lower()
    return any(
        token in normalized
        for token in (
            "掉线",
            "雷达",
            "激光",
            "laser",
            "scan",
            "low_level_error",
            "can",
            "usb",
            "未找到",
            "证据不足",
            "重启后恢复",
            "刚刚",
            "刚才",
        )
    )


def _should_collect_amr_stage3_evidence(route: str, request_text: str, evidence: Sequence[str]) -> bool:
    if route != "amr":
        return False
    normalized = f"{request_text}\n" + "\n".join(str(item).strip() for item in evidence if str(item).strip())
    lowered = normalized.lower()
    return any(
        token in lowered
        for token in (
            "caution",
            "bag",
            "切手动",
            "切自动",
            "手动恢复",
            "人工恢复",
            "人工干预",
            "重发任务",
            "release",
            "恢复后",
        )
    )


def _should_collect_amr_stage4_evidence(route: str, request_text: str) -> bool:
    if route != "amr":
        return False
    return bool(extract_exact_time_anchor(request_text))


def _should_collect_amr_stage5_evidence(route: str, request_text: str, evidence: Sequence[str]) -> bool:
    if route != "amr":
        return False
    if not extract_time_window(request_text):
        return False
    combined = "\n".join(str(item).strip() for item in evidence if str(item).strip()).lower()
    return any(
        token in combined
        for token in (
            "connection dropped",
            "reset embedded system",
            "can / eb / driver",
            "switch to manual",
            "manual",
            "recover",
            "resume",
            "retry",
            "caution_",
            "amr_timeline:",
        )
    )


def _resolve_amr_logdir_selector(request_text: str, time_key: str) -> str:
    exact_anchor = extract_exact_time_anchor(request_text)
    window = extract_time_window(request_text)
    if exact_anchor:
        target_key_expr = f'$(date -d "{exact_anchor}" +%Y_%m_%d-%H_%M_%S)'
        return f'$(ls -1 /home/robot/log/not_permanent/ | awk -v target="{target_key_expr}" \'$1 <= target\' | tail -1)'
    if window:
        target_key_expr = f'$(date -d "{window.end}" +%Y_%m_%d-%H_%M_%S)'
        return f'$(ls -1 /home/robot/log/not_permanent/ | awk -v target="{target_key_expr}" \'$1 <= target\' | tail -1)'
    if time_key:
        return f'$(ls -1 /home/robot/log/not_permanent/ | grep "{time_key}" | tail -1)'
    return '$(ls -1 /home/robot/log/not_permanent/ | tail -1)'


def _build_amr_logdir_locator_command(request_text: str, time_key: str) -> str:
    exact_anchor = extract_exact_time_anchor(request_text)
    window = extract_time_window(request_text)
    if exact_anchor:
        return f'ls -1 /home/robot/log/not_permanent/ | awk -v target="$(date -d "{exact_anchor}" +%Y_%m_%d-%H_%M_%S)" \'$1 <= target\' | tail -1'
    if window:
        return f'ls -1 /home/robot/log/not_permanent/ | awk -v target="$(date -d "{window.end}" +%Y_%m_%d-%H_%M_%S)" \'$1 <= target\' | tail -1'
    if time_key:
        return f"ls -1 /home/robot/log/not_permanent/ | grep '{time_key}' | tail -1"
    return "ls -1 /home/robot/log/not_permanent/ | tail -1"


def _extract_amr_logdir_name(results: Sequence[object]) -> str:
    for item in results:
        command_text = str(getattr(item, "command", "") or "").strip()
        if "/home/robot/log/not_permanent/" not in command_text:
            continue
        stdout = str(getattr(item, "stdout", "") or "").strip()
        if not stdout:
            continue
        lines = [line.strip().rstrip("/") for line in stdout.splitlines() if line.strip()]
        if not lines:
            continue
        candidate = lines[-1]
        if re.fullmatch(r"\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}", candidate):
            return candidate
    return ""


def _build_amr_deeper_commands(logdir_name: str) -> List[str]:
    if not logdir_name:
        return []
    base_dir = f"/home/robot/log/not_permanent/{logdir_name}"
    return [
        f"tail -n 120 {base_dir}/default.launch",
        f"tail -n 120 {base_dir}/mobile_base.launch",
        f"tail -n 120 {base_dir}/state_monitor_wrapper.launch",
        f"grep -i 'error\\|fail\\|exception\\|warn\\|laser\\|scan\\|lidar\\|radar\\|usb\\|can\\|eb\\|motor\\|connection dropped\\|reset embedded system' {base_dir}/default.launch | tail -n 120",
        f"grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' {base_dir}/mobile_base.launch | tail -n 120",
        f"grep -i 'error\\|fail\\|exception\\|warn\\|state\\|timeout\\|goal\\|fork\\|task' {base_dir}/state_monitor_wrapper.launch | tail -n 120",
    ]


def _resolve_amr_date_compact(request_text: str, time_key: str) -> str:
    exact_anchor = extract_exact_time_anchor(request_text)
    if exact_anchor:
        return exact_anchor[:10].replace("-", "")
    window = extract_time_window(request_text)
    if window and re.match(r"\d{4}-\d{2}-\d{2}", window.start):
        return window.start[:10].replace("-", "")
    return (time_key or "").replace("_", "")


def _build_amr_stage3_commands(logdir_name: str, date_compact: str) -> List[str]:
    commands: List[str] = []
    base_dir = f"/home/robot/log/not_permanent/{logdir_name}" if logdir_name else ""
    if date_compact:
        commands.append(f"find /home/robot/autobag -maxdepth 1 -type f | grep '{date_compact}' | tail -20")
    if base_dir:
        commands.extend(
            [
                f"grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' {base_dir}/state_monitor_wrapper.launch | tail -n 80",
                f"grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' {base_dir}/default.launch | tail -n 80",
            ]
        )
    return commands


def _resolve_amr_target_epoch(request_text: str) -> Optional[int]:
    exact_anchor = extract_exact_time_anchor(request_text)
    if not exact_anchor:
        return None
    try:
        return int(datetime.fromisoformat(exact_anchor).timestamp())
    except Exception:
        return None


def _build_amr_stage4_commands(logdir_name: str, request_text: str) -> List[str]:
    if not logdir_name:
        return []
    target_epoch = _resolve_amr_target_epoch(request_text)
    if target_epoch is None:
        return []
    start_epoch = target_epoch - 20
    end_epoch = target_epoch + 60
    base_dir = f"/home/robot/log/not_permanent/{logdir_name}"
    return [
        f"""awk 'match($0, /\\[[0-9]+\\.[0-9]+\\]/) {{ts=substr($0,RSTART+1,RLENGTH-2)+0; if (ts>={start_epoch} && ts<={end_epoch}) print}}' {base_dir}/mobile_base.launch | tail -n 120""",
        f"""awk 'match($0, /\\[[0-9]+\\.[0-9]+\\]/) {{ts=substr($0,RSTART+1,RLENGTH-2)+0; if (ts>={start_epoch} && ts<={end_epoch}) print}}' {base_dir}/default.launch | tail -n 120""",
        f"""awk 'match($0, /\\[[0-9]+\\.[0-9]+\\]/) {{ts=substr($0,RSTART+1,RLENGTH-2)+0; if (ts>={start_epoch} && ts<={end_epoch}) print}}' {base_dir}/state_monitor_wrapper.launch | tail -n 120""",
    ]


def _build_amr_permanent_logdir_expr(request_text: str, logdir_name: str) -> str:
    exact_anchor = extract_exact_time_anchor(request_text)
    window = extract_time_window(request_text)
    if exact_anchor:
        return f'$(ls -1 /home/robot/log/permanent/ | awk -v target="$(date -d "{exact_anchor}" +%Y_%m_%d-%H_%M_%S)" \'$1 <= target\' | tail -1)'
    if window:
        return f'$(ls -1 /home/robot/log/permanent/ | awk -v target="$(date -d "{window.end}" +%Y_%m_%d-%H_%M_%S)" \'$1 <= target\' | tail -1)'
    return logdir_name


def _build_amr_stage5_commands(logdir_name: str, request_text: str) -> List[str]:
    window = extract_time_window(request_text)
    if not window:
        return []
    commands = [
        f"journalctl -k --since '{window.start}' --until '{window.end}' --no-pager",
        f"journalctl --since '{window.start}' --until '{window.end}' --no-pager",
        "free -h",
        "swapon --show",
        "cat /proc/meminfo",
    ]
    if logdir_name:
        perm_dir_expr = _build_amr_permanent_logdir_expr(request_text, logdir_name)
        perm_dir = f"/home/robot/log/permanent/{perm_dir_expr}"
        target_epoch = _resolve_amr_target_epoch(request_text)
        if target_epoch is not None:
            start_epoch = target_epoch - 20
            end_epoch = target_epoch + 60
            commands.append(
                f"""find {perm_dir} -maxdepth 3 \\( -type f -o -type l \\) -name 'error_monitor_server.launch' -exec awk 'match($0, /\\[[0-9]+\\.[0-9]+\\]/) {{ts=substr($0,RSTART+1,RLENGTH-2)+0; if (ts>={start_epoch} && ts<={end_epoch}) print}}' {{}} \\; | tail -n 120"""
            )
        else:
            commands.append(
                f"""find {perm_dir} -maxdepth 3 \\( -type f -o -type l \\) -name 'error_monitor_server.launch' -exec tail -n 120 {{}} \\;"""
            )
    return commands


def _build_rcs_deeper_commands(request_text: str) -> List[str]:
    commands = [
        "systemctl status supervisor --no-pager",
        "journalctl -u supervisor -n 80 --no-pager",
        "docker logs docker-backend_1 --tail 80",
        "docker inspect -f '{{.State.Status}} {{.State.Restarting}} {{.State.ExitCode}}' docker-backend_1",
        "docker logs docker-mysql_5_7-1 --tail 80",
        "docker inspect -f '{{.State.Status}} {{.State.Restarting}} {{.State.ExitCode}}' docker-mysql_5_7-1",
        "docker exec docker-mysql_5_7-1 mysqladmin ping -u root",
        "curl -s -S -m 3 http://127.0.0.1:3737/infos/ros/",
        "journalctl -k -n 80 --no-pager",
    ]
    lowered = request_text.lower()
    if any(token in lowered for token in ("死机", "重启", "卡死")):
        commands.append("journalctl -u docker -n 80 --no-pager")
    return commands


def _format_remote_result_evidence(command_text: str, stdout: str, stderr: str, returncode: object) -> str:
    preview = (stdout or stderr).strip()
    if not command_text or not preview:
        return ""
    compact = re.sub(r"\s+", " ", preview)[:400]
    return f"provider_execute[{command_text}]: rc={returncode} {compact}"


def _refine_historical_amr_root_cause(root_cause: str, evidence: Sequence[str]) -> str:
    filtered_lines = [
        str(item).strip()
        for item in evidence
        if str(item).strip() and "command denied by sandbox policy" not in str(item).lower()
    ]
    combined = "\n".join(filtered_lines)
    lowered = combined.lower()
    if any(token in lowered for token in ("connection dropped", "reset embedded system", "cannot read eb", "cannot write eb", "can bus停止发布数据", "resume eb_interrupt")):
        return "故障时段先出现底层嵌入式 / CAN 链路异常，扫描、定位或任务异常更像由底层通信失稳引发的派生表现。"
    if any(token in lowered for token in ("uvcvideo", "usb disconnect", "usb reset", "device descriptor", "pcan")) and any(token in lowered for token in ("can", "eb", "motor")):
        return "故障时段存在 USB 总线异常，并继续扩散到 CAN / 嵌入式链路，优先按公共总线或供电级联问题处理。"
    if re.search(r"laserscan.*front|front.*laserscan|front lidar|front radar", combined, re.IGNORECASE):
        return "故障时段前向扫描链路存在历史掉线或异常，优先核对前雷达及其上游 USB / 供电链路。"
    if re.search(r"laserscan.*rear|rear.*laserscan|rear lidar|rear radar", combined, re.IGNORECASE):
        return "故障时段后向扫描链路存在历史掉线或异常，优先核对后雷达及其上游链路。"
    if "/low_level_error 当前未发布" in combined and "rosnode list" in combined:
        return "故障时段相关历史日志已定位，但当前实时 /low_level_error 未提供补充错误码，仍应以对应时间窗口内的 launch 与底层链路日志为主证据。"
    return root_cause


def _refine_historical_amr_root_cause_stage3(root_cause: str, request_text: str, evidence: Sequence[str]) -> str:
    combined = "\n".join(str(item).strip() for item in evidence if str(item).strip())
    lowered = combined.lower()
    request_lowered = (request_text or "").lower()
    if any(token in request_lowered for token in ("切手动", "切自动", "人工恢复", "手动恢复", "重发任务", "release")):
        return "现场存在人工恢复或重试动作，这些更像掩盖首因的恢复手段；应优先回到第一次异常时间，结合底层链路与任务状态流判断首发根因。"
    if "caution_" in lowered and any(token in lowered for token in ("connection dropped", "reset embedded system", "can", "usb", "laserscan")):
        return "同时间段已存在 caution / bag 线索，且底层链路异常与扫描异常相互印证；应优先按首发底层异常解释本次故障，而不是只看恢复后的状态。"
    if "caution_" in lowered and "未找到" in root_cause:
        return f"{root_cause}；但同时间段存在 caution 录包，建议继续结合 bag 前后状态变化定位首发异常。"
    return root_cause


def _refine_historical_amr_root_cause_stage5(root_cause: str, evidence: Sequence[str]) -> str:
    payload_lines: List[str] = []
    for item in evidence:
        text = str(item).strip()
        if not text:
            continue
        if text.startswith("provider_execute["):
            closing = text.find("]:")
            payload = text[closing + 2 :] if closing >= 0 else text
            if payload.startswith("rc="):
                first_space = payload.find(" ")
                if first_space >= 0:
                    payload = payload[first_space + 1 :]
            text = payload.strip()
        payload_lines.append(text)
    combined = "\n".join(payload_lines)
    lowered = combined.lower()
    has_low_level_chain = any(
        token in lowered
        for token in (
            "connection dropped",
            "reset embedded system",
            "cannot read eb",
            "cannot write eb",
            "can bus",
            "resume eb_interrupt",
        )
    )
    has_memory_pressure = any(
        token in lowered
        for token in (
            "out of memory",
            "oom",
            "killed process",
            "kswapd",
            "page allocation failure",
            "allocstall",
            "compact_stall",
        )
    )
    if has_low_level_chain and has_memory_pressure:
        return (
            f"{root_cause} 同时间窗口还出现了内存 / swap 压力线索，需并列核对资源抖动是否放大了 CAN / EB 通信失稳；"
            "但在现有证据里，底层通信异常仍然先于恢复动作暴露。"
        )
    if has_low_level_chain and not has_memory_pressure:
        return f"{root_cause} 同时间窗口未见 OOM / swap / 明显内存压力证据，现有证据不支持把 swap 作为首发根因。"
    return root_cause


def _extract_amr_timeline_summary(evidence: Sequence[str]) -> List[str]:
    summaries: List[str] = []
    seen: List[str] = []
    for item in evidence:
        line = str(item).strip()
        if not line.startswith("provider_execute[awk "):
            continue
        closing = line.find("]:")
        if closing < 0:
            continue
        command = line[len("provider_execute["):closing].strip()
        payload = line[closing + 2 :].strip()
        if payload.startswith("rc="):
            first_space = payload.find(" ")
            if first_space >= 0:
                payload = payload[first_space + 1 :].strip()
        if not payload:
            continue
        label = ""
        if "mobile_base.launch" in command or "awk mobile_base exact" in command:
            label = "mobile_base"
        elif "default.launch" in command or "awk default exact" in command:
            label = "default"
        elif "state_monitor_wrapper.launch" in command or "awk state_monitor exact" in command:
            label = "state_monitor"
        if not label:
            continue
        for segment in payload.split(" ["):
            snippet = segment.strip()
            if not snippet:
                continue
            lowered = snippet.lower()
            if label == "mobile_base" and any(token in lowered for token in ("connection dropped", "reset embedded system", "can", "driver", "eb")):
                summary = f"首发候选：{snippet[:180]}"
            elif label == "state_monitor" and any(token in lowered for token in ("manual", "pause", "recover", "resume", "retry")):
                summary = f"恢复/暂停线索：{snippet[:180]}"
            elif label == "default" and any(token in lowered for token in ("laser", "scan", "radar", "error_list", "registererror2")):
                summary = f"扫描链路线索：{snippet[:180]}"
            else:
                continue
            if summary not in seen:
                seen.append(summary)
                summaries.append(summary)
    return summaries[:4]


def _extract_bracketed_segments(payload: str) -> List[str]:
    segments: List[str] = []
    for match in re.finditer(r"(\[[0-9]+\.[0-9]+\][^\[]*)", payload):
        segment = str(match.group(1) or "").strip()
        if segment:
            segments.append(segment)
    return segments


def _extract_amr_auto_closure(evidence: Sequence[str]) -> Dict[str, str]:
    mobile_event = ""
    state_event = ""
    error_event = ""
    low_level_event = ""
    for item in evidence:
        line = str(item).strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = ast.literal_eval(line)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                payload_type = str(payload.get("type") or "").strip()
                detail = str(payload.get("detail") or "").strip()
                value = str(payload.get("value") or "").strip()
                source = str(payload.get("source") or "").strip()
                text_value = detail or value
                if payload_type == "provider_execute" and text_value:
                    lowered_text_value = text_value.lower()
                    if not low_level_event and any(token in lowered_text_value for token in ("low_level_error", "topic [/low_level_error]", "未发布")):
                        low_level_event = text_value
                if source.endswith("rostopic echo /low_level_error -n1]") and text_value:
                    low_level_event = text_value
                if payload_type in {"local_diag_summary", "provider_execute"}:
                    continue
        if not line.startswith("provider_execute["):
            continue
        closing = line.find("]:")
        if closing < 0:
            continue
        command = line[len("provider_execute["):closing].strip()
        payload = line[closing + 2 :].strip()
        if payload.startswith("rc="):
            first_space = payload.find(" ")
            if first_space >= 0:
                payload = payload[first_space + 1 :].strip()
        lowered_command = command.lower()
        lowered_payload = payload.lower()
        segments = _extract_bracketed_segments(payload)
        if not segments:
            lines = [segment.strip() for segment in payload.splitlines() if segment.strip()]
            segments = lines or [payload]
        for segment in segments:
            lowered_segment = segment.lower()
            if (not mobile_event and ("mobile_base.launch" in lowered_command or "awk mobile_base exact" in lowered_command) and any(token in lowered_segment for token in ("connection dropped", "reset embedded system", "can", "eb", "driver", "motor"))):
                mobile_event = segment
            if (not state_event and ("state_monitor_wrapper.launch" in lowered_command or "awk state_monitor exact" in lowered_command) and any(token in lowered_segment for token in ("manual", "recover", "resume", "pause", "retry", "release"))):
                state_event = segment
            if (not error_event and ("error_monitor_server.launch" in lowered_command or "find /home/robot/log/permanent/" in lowered_command) and any(token in lowered_segment for token in ("register id", "code=", "trigger", "cleared", "abort", "aborted"))):
                error_event = segment
        if not low_level_event and "rostopic echo /low_level_error -n1" in lowered_command and payload:
            low_level_event = payload
        if not mobile_event and ("mobile_base.launch" in lowered_command or "awk mobile_base exact" in lowered_command):
            for segment in [segment.strip() for segment in payload.splitlines() if segment.strip()]:
                lowered_segment = segment.lower()
                if any(token in lowered_segment for token in ("connection dropped", "reset embedded system", "can", "eb", "driver", "motor")):
                    mobile_event = segment[:220]
                    break
        if not state_event and ("state_monitor_wrapper.launch" in lowered_command or "awk state_monitor exact" in lowered_command):
            for segment in [segment.strip() for segment in payload.splitlines() if segment.strip()]:
                lowered_segment = segment.lower()
                if any(token in lowered_segment for token in ("manual", "recover", "resume", "pause", "retry", "release")):
                    state_event = segment[:220]
                    break
        if not error_event and ("error_monitor_server.launch" in lowered_command or "find /home/robot/log/permanent/" in lowered_command):
            for segment in [segment.strip() for segment in payload.splitlines() if segment.strip()]:
                lowered_segment = segment.lower()
                if any(token in lowered_segment for token in ("register id", "code=", "trigger", "cleared", "abort", "aborted")):
                    error_event = segment[:220]
                    break
    if not mobile_event or not state_event:
        return {}
    summary = f"首发异常：{mobile_event}"
    summary += f"；随后派生状态：{state_event}"
    if error_event:
        summary += f"；同窗错误码/任务旁证：{error_event}"
    return {
        "summary": summary,
        "mobile_event": mobile_event,
        "state_event": state_event,
        "error_event": error_event,
        "low_level_event": low_level_event,
    }


def _refine_historical_amr_root_cause_auto_closure(root_cause: str, evidence: Sequence[str], request_text: str) -> str:
    closure = _extract_amr_auto_closure(evidence)
    if not closure:
        return root_cause
    mobile_event = closure.get("mobile_event", "")
    state_event = closure.get("state_event", "")
    error_event = closure.get("error_event", "")
    low_level_event = closure.get("low_level_event", "")
    exact_anchor = extract_exact_time_anchor(request_text) or extract_time_window(request_text).label if extract_time_window(request_text) else ""
    prefix = f"{exact_anchor} 前后自动收口显示：" if exact_anchor else "自动收口显示："
    cause = (
        f"{prefix}先出现 `{mobile_event}`，随后出现 `{state_event}`，"
        "说明首发更像底盘底层 CAN / EB / driver 通信异常，手动 / 恢复 / 暂停属于后续保护性派生状态。"
    )
    if error_event:
        cause += f" 同窗还出现 `{error_event}`，可作为任务或错误码侧旁证。"
    if low_level_event:
        lowered_low_level = low_level_event.lower()
        if "does not appear to be published yet" in lowered_low_level or "未发布" in low_level_event:
            cause += " 当前抓取时 /low_level_error 未发布，这不推翻历史首发判断，只说明事后现场未保留实时报码。"
        else:
            cause += f" 同时抓到 /low_level_error 线索：`{low_level_event[:160]}`。"
    if "不支持把 swap 作为首发根因" in root_cause:
        cause += " 当前证据不支持把 swap 作为首发根因。"
    if "人工恢复或重试动作" in root_cause or "恢复手段" in root_cause:
        cause += " 其中手动 / 恢复动作应视为掩盖首因的派生过程，而不是最初根因。"
    return cause


def _build_amr_auto_closure_next_steps(evidence: Sequence[str]) -> List[str]:
    closure = _extract_amr_auto_closure(evidence)
    if not closure:
        return []
    steps = [
        "优先排查 CAN / EB / driver 硬件链路，包括 USB-CAN、线束、接插件、供电与接地稳定性。",
        "复查底盘驱动与电机控制器保护记录，重点确认是否存在瞬时 bus-off、驱动复位、使能抖动或急停链路触发。",
        "若再次复现，第一时间保留首条 mobile_base 异常行、state_monitor 切换行和 error_monitor 触发记录，不要只看恢复后的暂停状态。",
        "若有录包或 bag，优先核对 01:14:10-01:14:25 内底盘控制、里程计、急停、模式切换及相关状态话题，确认异常扩散顺序。",
    ]
    if closure.get("low_level_event"):
        lowered = closure["low_level_event"].lower()
        if "does not appear to be published yet" in lowered or "未发布" in closure["low_level_event"]:
            steps.append("若现场可重现，需在 ROS 环境完整时同步抓取 /low_level_error，避免再次缺失首发报码。")
    return steps


def _has_amr_auto_closure(evidence: Sequence[str]) -> bool:
    closure = _extract_amr_auto_closure(evidence)
    return bool(closure.get("mobile_event") and closure.get("state_event"))


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
        historical_amr_diag_enabled = route == "amr" and bool(effective_time_key or extract_time_window(request.text))
        historical_rcs_diag = route == "rcs" and is_historical_rcs_request(request.text, effective_time_key or None)
        force_local_diag_follow_up = _should_force_local_diag_on_follow_up(session, route, request.text)
        auto_diag_enabled = (
            os.getenv("FEISHU_ENABLE_LOCAL_DIAG", "0") == "1"
            or historical_amr_diag_enabled
            or historical_rcs_diag
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
            if context.target and historical_amr_diag_enabled and _should_collect_deeper_amr_evidence(route, request.text, final_root_cause):
                locator_report = collect_evidence(
                    route,
                    context.target or session.target or "",
                    commands=[
                        "rostopic echo /low_level_error -n1",
                        "rosnode list",
                        "ip -s -d link show can0",
                        "lsusb -t",
                        _build_amr_logdir_locator_command(request.text, effective_time_key or ""),
                    ],
                    settings=self.settings,
                )
                locator_results = list(locator_report.get("results", []))
                for item in locator_results:
                    command_text = (getattr(item, "command", "") or "").strip()
                    stdout = (getattr(item, "stdout", "") or "").strip()
                    stderr = (getattr(item, "stderr", "") or "").strip()
                    returncode = getattr(item, "returncode", "")
                    preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                    if preview:
                        evidence.append(preview)
                logdir_name = _extract_amr_logdir_name(locator_results)
                if logdir_name:
                    evidence.append(f"amr_logdir: /home/robot/log/not_permanent/{logdir_name}")
                    deeper_report = collect_evidence(
                        route,
                        context.target or session.target or "",
                        commands=_build_amr_deeper_commands(logdir_name),
                        settings=self.settings,
                    )
                    for item in deeper_report.get("results", []):
                        command_text = (getattr(item, "command", "") or "").strip()
                        stdout = (getattr(item, "stdout", "") or "").strip()
                        stderr = (getattr(item, "stderr", "") or "").strip()
                        returncode = getattr(item, "returncode", "")
                        preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                        if preview:
                            evidence.append(preview)
                if _should_collect_amr_stage3_evidence(route, request.text, evidence):
                    stage3_report = collect_evidence(
                        route,
                        context.target or session.target or "",
                        commands=_build_amr_stage3_commands(logdir_name, _resolve_amr_date_compact(request.text, effective_time_key or "")),
                        settings=self.settings,
                    )
                    for item in stage3_report.get("results", []):
                        command_text = (getattr(item, "command", "") or "").strip()
                        stdout = (getattr(item, "stdout", "") or "").strip()
                        stderr = (getattr(item, "stderr", "") or "").strip()
                        returncode = getattr(item, "returncode", "")
                        preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                        if preview:
                            evidence.append(preview)
                if logdir_name and _should_collect_amr_stage4_evidence(route, request.text):
                    stage4_report = collect_evidence(
                        route,
                        context.target or session.target or "",
                        commands=_build_amr_stage4_commands(logdir_name, request.text),
                        settings=self.settings,
                    )
                    for item in stage4_report.get("results", []):
                        command_text = (getattr(item, "command", "") or "").strip()
                        stdout = (getattr(item, "stdout", "") or "").strip()
                        stderr = (getattr(item, "stderr", "") or "").strip()
                        returncode = getattr(item, "returncode", "")
                        preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                        if preview:
                            evidence.append(preview)
                    for timeline_item in _extract_amr_timeline_summary(evidence):
                        evidence.append(f"amr_timeline: {timeline_item}")
                if _should_collect_amr_stage5_evidence(route, request.text, evidence):
                    stage5_report = collect_evidence(
                        route,
                        context.target or session.target or "",
                        commands=_build_amr_stage5_commands(logdir_name, request.text),
                        settings=self.settings,
                    )
                    for item in stage5_report.get("results", []):
                        command_text = (getattr(item, "command", "") or "").strip()
                        stdout = (getattr(item, "stdout", "") or "").strip()
                        stderr = (getattr(item, "stderr", "") or "").strip()
                        returncode = getattr(item, "returncode", "")
                        preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                        if preview:
                            evidence.append(preview)
                final_root_cause = _refine_historical_amr_root_cause(final_root_cause, evidence)
                final_root_cause = _refine_historical_amr_root_cause_stage3(final_root_cause, request.text, evidence)
                final_root_cause = _refine_historical_amr_root_cause_stage5(final_root_cause, evidence)
                final_root_cause = _refine_historical_amr_root_cause_auto_closure(final_root_cause, evidence, request.text)
            if context.target and not historical_rcs_diag and _should_collect_deeper_rcs_evidence(route, evidence, request.text):
                deeper_report = collect_evidence(
                    route,
                    context.target or session.target or "",
                    commands=_build_rcs_deeper_commands(request.text),
                    settings=self.settings,
                )
                for item in deeper_report.get("results", []):
                    command_text = (getattr(item, "command", "") or "").strip()
                    stdout = (getattr(item, "stdout", "") or "").strip()
                    stderr = (getattr(item, "stderr", "") or "").strip()
                    returncode = getattr(item, "returncode", "")
                    preview = _format_remote_result_evidence(command_text, stdout, stderr, returncode)
                    if preview:
                        evidence.append(preview)

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
            provider_target = context.target or session.target or ""
            if provider_target and f"目标：{provider_target}" not in provider_context:
                provider_context = f"{provider_context}\n目标：{provider_target}"
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
                            _format_follow_up_guardrail(session.target or context.target or "", context.target or ""),
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
                    provider_context = f"{provider_context}\n\n{_format_follow_up_guardrail(session.target or context.target or '', context.target or '')}"
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
            provider_has_execute_evidence = any(
                str(item).strip().startswith("provider_execute[")
                for item in list(provider_result.evidence) + list(provider_evidence)
            ) or any(
                str(getattr(event, "type", "") or "") == ACTION_SECURE_SSH_EXECUTE
                for event in provider_result.action_events
            )
            if provider_result.root_cause and (
                final_root_cause == "当前基于知识库与上下文进行排障"
                or (provider_result.confidence == "high" and route != "amr")
                or (provider_result.confidence == "medium" and not local_evidence_insufficient and not historical_rcs_diag and not historical_amr_diag_enabled)
                or (provider_has_execute_evidence and route == "rcs" and not historical_rcs_diag)
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
        if auto_diag_enabled and route == "amr":
            closure_next_steps = _build_amr_auto_closure_next_steps(evidence)
            if closure_next_steps:
                provider_next_steps = closure_next_steps
            if historical_amr_diag_enabled and _has_amr_auto_closure(evidence):
                provider_root_cause = ""
                provider_summary = ""

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
