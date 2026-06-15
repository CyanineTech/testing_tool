from typing import Iterable, List, Mapping, Sequence
import ast

from feishu_agent.core.session import SessionState
from feishu_agent.playbooks.base import Playbook, next_step


_HIDDEN_EVIDENCE_PREFIXES = (
    "local_diag_summary:",
    "local_diag_executed:",
    "policy_warning:",
    "mcp_server_status:",
    "mcp_servers_loaded:",
    "knowledge_candidates:",
    "doc_excerpt[",
    "knowledge_read[",
    "previous_evidence:",
)


def _visible_evidence_lines(evidence: Iterable[str]) -> List[str]:
    lines: List[str] = []
    for line in evidence:
        if not line or not str(line).strip():
            continue
        normalized = str(line).strip()
        if any(normalized.startswith(prefix) for prefix in _HIDDEN_EVIDENCE_PREFIXES):
            continue
        lines.append(_normalize_visible_evidence_line(normalized))
    return lines


def _normalize_visible_evidence_line(line: str) -> str:
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
    if not content:
        return line
    if item_type == "local_diag_summary":
        return f"本地诊断摘要：{content}"
    if item_type == "local_diag_executed":
        return f"本地诊断执行：{content}"
    if item_type == "knowledge_reference":
        return f"知识参考：{content}"
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
    lines: List[str] = [
        "## 诊断结果",
        f"**故障类别**：{route}",
        f"**目标**：{target or '未指定'}",
        f"**严重程度**：{severity}",
        f"**根因分析**：{root_cause}",
    ]

    lines.append("**已执行检查**：")
    if executed:
        for index, item in enumerate(executed, start=1):
            command = str(item.get("command", ""))
            returncode = item.get("returncode", "")
            lines.append(f"- {index}. `{command}` (rc={returncode})")
    else:
        lines.append("- 暂无自动执行检查，当前结论基于知识库与上下文。")

    evidence_lines = _visible_evidence_lines(evidence)
    if evidence_lines:
        lines.append("**证据摘要**：")
        for item in evidence_lines[-8:]:
            cleaned = item.replace("`", "'")
            lines.append(f"- {cleaned}")

    if provider_summary:
        lines.append("**补充判断**：")
        lines.append(provider_summary.replace("`", "'"))
        provider_next_steps_list = [item.strip() for item in provider_next_steps if item and str(item).strip()]
        if provider_next_steps_list:
            lines.append("- 建议继续：")
            for item in provider_next_steps_list:
                lines.append(f"  - {item}")
        provider_evidence_lines = _visible_evidence_lines(provider_evidence)
        if provider_evidence_lines:
            lines.append("- 补充证据：")
            for item in provider_evidence_lines[-4:]:
                cleaned_item = item.replace("`", "'")
                lines.append(f"  - {cleaned_item}")

    lines.extend([
        "**修复建议**：",
        _default_fix_line(route, 1),
        _default_fix_line(route, 2),
        _default_fix_line(route, 3),
        "**是否需要停机**：待评估",
        "**预计恢复时间**：待评估",
    ])
    return "\n".join(lines)


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
