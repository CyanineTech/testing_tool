from typing import Iterable, List, Mapping, Sequence
import ast
import json
import re

from feishu_agent.core.session import SessionState
from feishu_agent.playbooks.base import Playbook, next_step


_HIDDEN_EVIDENCE_PREFIXES = (
    "local_diag_summary:",
    "local_diag_executed:",
    "policy_warning:",
    "mcp_server_status:",
    "mcp_servers_loaded:",
    "provider_report:",
    "knowledge_candidates:",
    "doc_excerpt[",
    "knowledge_read[",
    "previous_evidence:",
)


def _provider_execute_summary(line: str) -> str:
    match = ast.literal_eval("{}") if False else None
    if not line.startswith("provider_execute["):
        return line
    closing = line.find("]:")
    if closing < 0:
        return line
    command = line[len("provider_execute["):closing].strip()
    payload = line[closing + 2 :].strip()
    if payload.startswith("rc="):
        first_space = payload.find(" ")
        if first_space >= 0:
            payload = payload[first_space + 1 :].strip()
    lowered = payload.lower()
    if "connection refused" in lowered and "127.0.0.1:3737" in command:
        return "后端 API 3737 端口连接被拒绝，说明服务当前未监听。"
    if "access denied" in lowered and "mysqladmin ping" in command:
        return "MySQL 容器在运行，但当前探活账号/认证方式不匹配。"
    if "running false 0" in lowered and "docker-mysql_5_7-1" in command:
        return "MySQL 容器状态为 running，未见容器退出。"
    if "start request repeated too quickly" in lowered:
        return "supervisor 或其托管服务存在频繁拉起失败迹象。"
    if "-- no entries --" in lowered and "journalctl -k" in command:
        return "kernel 日志未见明显系统级报错。"
    if "-- no entries --" in lowered and "journalctl -u docker" in command:
        return "docker 服务日志未见明显异常。"
    if "mobile_base.launch" in command and any(token in lowered for token in ("connection dropped", "reset embedded system", "cannot read eb", "cannot write eb", "can bus")):
        return "mobile_base.launch 在故障时段出现 CAN / EB / 驱动链路异常，优先指向底层通信失稳。"
    if "default.launch" in command and any(token in lowered for token in ("laser", "scan", "radar", "error_list timeout", "registererror2")):
        return "default.launch 在故障时段出现扫描链路或错误监控异常，需结合底层链路判断是否为派生表现。"
    if "state_monitor_wrapper.launch" in command and any(token in lowered for token in ("switch to manual", "manual", "recover", "resume", "retry", "release")):
        return "state_monitor_wrapper.launch 记录到手动 / 恢复 / 重试相关线索，应把它视为恢复动作而不是直接根因。"
    if "find /home/robot/autobag" in command and "caution_" in lowered:
        match = re.search(r"(caution_[^\s]+\.bag\.zip)", payload, re.IGNORECASE)
        if match:
            return f"同时间段存在 caution / bag 证据：{match.group(1)}，建议继续核对故障前后 20s~60s 的 /low_level_error、/scan、/amcl_pose、/odom、/motor_control/low_level_status。"
        return "同时间段存在 caution / bag 证据，建议继续核对故障前后 20s~60s 的 /low_level_error、/scan、/amcl_pose、/odom、/motor_control/low_level_status。"
    compact = payload.replace("`", "'")
    if len(compact) > 120:
        compact = compact[:117] + "..."
    return f"{command}: {compact}"


def _visible_evidence_lines(evidence: Iterable[str]) -> List[str]:
    lines: List[str] = []
    seen: List[str] = []
    for line in evidence:
        if not line or not str(line).strip():
            continue
        normalized = str(line).strip()
        if any(normalized.startswith(prefix) for prefix in _HIDDEN_EVIDENCE_PREFIXES):
            continue
        visible = _normalize_visible_evidence_line(normalized)
        if visible not in seen:
            seen.append(visible)
            lines.append(visible)
    return lines


def _humanize_provider_text(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    candidate = raw
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate.strip("`").strip()

    payload = None
    try:
        payload = json.loads(candidate)
    except Exception:
        try:
            payload = ast.literal_eval(candidate)
        except Exception:
            payload = None

    if isinstance(payload, dict):
        lines: List[str] = []
        primary = str(payload.get("primary") or "").strip()
        if primary:
            lines.append(primary)
        category = str(payload.get("category") or "").strip()
        detail = str(payload.get("detail") or "").strip()
        if category and detail:
            lines.append(f"{category}：{detail}")
        elif detail:
            lines.append(detail)
        analysis = payload.get("analysis")
        if isinstance(analysis, (list, tuple)):
            for item in analysis:
                cleaned = str(item or "").strip()
                if cleaned:
                    lines.append(cleaned)
        elif analysis:
            cleaned = str(analysis).strip()
            if cleaned:
                lines.append(cleaned)
        if lines:
            return lines

    if isinstance(payload, list):
        lines = [str(item or "").strip() for item in payload if str(item or "").strip()]
        if lines:
            return lines

    return [raw]


def _append_unique_line(container: List[str], seen: List[str], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    if cleaned not in seen:
        seen.append(cleaned)
        container.append(cleaned)


def _merged_visible_evidence_lines(evidence: Iterable[str], provider_evidence: Iterable[str]) -> List[str]:
    merged: List[str] = []
    seen: List[str] = []
    for item in _visible_evidence_lines(evidence):
        _append_unique_line(merged, seen, item)
    for item in _visible_evidence_lines(provider_evidence):
        _append_unique_line(merged, seen, item)
    return merged


def _normalize_visible_evidence_line(line: str) -> str:
    if line.startswith("provider_execute["):
        return _provider_execute_summary(line)
    if not line.startswith("{") or not line.endswith("}"):
        return line
    try:
        payload = ast.literal_eval(line)
    except Exception:
        return line
    if not isinstance(payload, dict):
        return line
    item_type = str(payload.get("type") or "").strip()
    content = str(payload.get("content") or "").strip()
    detail = str(payload.get("detail") or "").strip()
    value = str(payload.get("value") or "").strip()
    if not content:
        content = detail or value
    if not content:
        return line
    if item_type == "local_diag_summary":
        return f"本地诊断摘要：{content}"
    if item_type == "local_diag_executed":
        return f"本地诊断执行：{content}"
    if item_type == "knowledge_reference":
        return f"知识参考：{content}"
    if item_type == "provider_execute":
        return content
    if "detail" in payload and str(payload.get("detail") or "").strip():
        return str(payload.get("detail") or "").strip()
    return content


def format_progress_reply(
    playbook: Playbook,
    step_index: int,
    include_first_check: bool = True,
    docs_override: Sequence[str] = (),
) -> str:
    lines = [
        f"已收到：{playbook.title}",
        f"摘要：{playbook.summary}",
    ]
    if include_first_check:
        lines.append(f"首查命令：{playbook.first_check}")
    lines.append(next_step(playbook, step_index))
    if playbook.steps and step_index + 1 < len(playbook.steps):
        lines.append("后续步骤：")
        for step in playbook.steps[step_index + 1 :]:
            lines.append(f"{step.index}. {step.text}")
    visible_docs = list(docs_override) if docs_override else list(playbook.docs)
    if visible_docs:
        lines.append(f"候选文档：{'、'.join(visible_docs)}")
    return "\n".join(lines)


def format_clarification_reply(route: str, missing_fields: list) -> str:
    if route in {"amr", "network"}:
        return "已收到，请补充设备/IP 或主机名、现象、发生时间、影响范围。收到后我按原排障流程继续。"
    if route == "unknown":
        return "请补充设备/IP 或主机名，以及现象、发生时间、影响范围，我再按对应排障流程继续。"
    return "请补充必要信息后继续。"


def format_final_report(session: SessionState) -> str:
    candidate_docs = session.last_doc_candidates or session.last_docs
    read_docs = session.last_read_docs
    lines = [
        f"故障类别：{session.route or '未分类'}",
        f"目标：{session.target or '未指定'}",
        f"严重程度：待后续结论",
        f"当前步骤：{session.step_index}",
        f"候选文档：{'、'.join(candidate_docs) if candidate_docs else '未加载'}",
        f"已读取文档：{'、'.join(read_docs) if read_docs else '未读取'}",
    ]
    if session.last_report:
        lines.append(session.last_report)
    return "\n".join(lines)


def format_case_report(
    *,
    route: str,
    target: str,
    severity: str,
    root_cause: str,
    executed: Sequence[Mapping[str, object]],
    evidence: Iterable[str],
    docs: Sequence[str],
    read_docs: Sequence[str] = (),
    provider_summary: str = "",
    provider_name: str = "",
    provider_confidence: str = "",
    provider_root_cause: str = "",
    provider_severity: str = "",
    provider_next_steps: Sequence[str] = (),
    provider_evidence: Iterable[str] = (),
) -> str:
    lines: List[str] = ["## 诊断结果"]

    lines.append("**1. 故障结论**")
    lines.append(f"- 对象：{route} / {target or '未指定'}")
    lines.append(f"- 严重程度：{severity}")
    lines.append(f"- 当前结论：{_build_conclusion_line(route, severity, root_cause)}")

    lines.append("**2. 根因**")
    lines.append(f"- {root_cause}")
    if provider_summary:
        provider_parts: List[str] = []
        if provider_root_cause and provider_root_cause.strip() and provider_root_cause.strip() != root_cause.strip():
            provider_parts.extend(_humanize_provider_text(provider_root_cause.strip().replace("`", "'")))
        provider_parts.extend(_humanize_provider_text(provider_summary.replace("`", "'")))
        deduped_provider_parts: List[str] = []
        provider_seen: List[str] = []
        for item in provider_parts:
            _append_unique_line(deduped_provider_parts, provider_seen, item)
        for idx, part in enumerate(deduped_provider_parts):
            prefix = "- " if idx == 0 else "  "
            lines.append(f"{prefix}{part}")

    lines.append("**3. 建议**")
    provider_next_steps_list = [item.strip() for item in provider_next_steps if item and str(item).strip()]
    if provider_next_steps_list:
        for index, item in enumerate(provider_next_steps_list, start=1):
            lines.append(f"- {index}. {item}")
    else:
        lines.append(f"- {_default_fix_line(route, 1)[3:]}")
        lines.append(f"- {_default_fix_line(route, 2)[3:]}")
        lines.append(f"- {_default_fix_line(route, 3)[3:]}")

    lines.append("**4. 证据**")
    if executed:
        for index, item in enumerate(executed, start=1):
            command = str(item.get("command", ""))
            returncode = item.get("returncode", "")
            lines.append(f"- 检查 {index}：`{command}` (rc={returncode})")
    else:
        lines.append("- 暂无自动执行检查，当前结论基于知识库与上下文。")

    merged_evidence_lines = _merged_visible_evidence_lines(evidence, provider_evidence)
    if merged_evidence_lines:
        for item in merged_evidence_lines[-8:]:
            cleaned = item.replace("`", "'")
            lines.append(f"- {cleaned}")

    return "\n".join(lines)


def _build_conclusion_line(route: str, severity: str, root_cause: str) -> str:
    route_titles = {
        "amr": "AMR 历史故障",
        "network": "网络历史故障",
        "rcs": "RCS 主机历史故障",
    }
    title = route_titles.get(route, "历史故障")
    if severity in {"错误", "严重", "error", "critical"}:
        return f"{title}已定位到高优先级异常，建议优先按首发异常继续收口。"
    if "未找到" in root_cause or "不足" in root_cause:
        return f"{title}已有初步方向，但现有证据仍不足以完全闭环。"
    return f"{title}已有明确排查方向，可继续围绕当前根因收口。"


def _default_fix_line(route: str, index: int) -> str:
    recommendations = {
        "amr": [
            "1. 先检查底层嵌入式、电机、CAN 和 USB 供电 / 连接是否稳定。",
            "2. 如果日志里持续出现 connection dropped / reset embedded system，优先处理 EB/CAN 侧，不要先把责任归到雷达节点。",
            "3. 若仍复现，再按对应时间点取 bag 和 default.launch / mobile_base.launch 深挖。",
        ],
        "network": [
            "1. 先确认目标可达性和 SSH 认证。",
            "2. 再检查 WiFi / Tailscale / 路由器链路。",
            "3. 如果网络能通但服务不通，再继续看端口和防火墙。",
        ],
        "rcs": [
            "1. 先检查主机服务和端口状态。",
            "2. 再看调度中心、数据库和任务队列。",
            "3. 如果服务反复抖动，再检查资源占用和容器日志。",
        ],
        "unknown": [
            "1. 先补充设备/IP 或主机名。",
            "2. 再补充现象、发生时间和影响范围。",
            "3. 补齐后再按对应场景继续排查。",
        ],
    }
    items = recommendations.get(route, recommendations["unknown"])
    if 1 <= index <= len(items):
        return items[index - 1]
    return items[-1]
