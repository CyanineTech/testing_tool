import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from feishu_agent.config import Settings, load_settings
from feishu_agent.knowledge.loader import load_knowledge_excerpt
from feishu_agent.protocols.actions import (
    ACTION_READ_KNOWLEDGE,
    ACTION_REPORT,
    ACTION_SECURE_SSH_EXECUTE,
    ActionEvent,
    build_action_event,
)
from feishu_agent.providers.base import ProviderRequest, ProviderResult, extract_json_object
from feishu_agent.ssh.collect import collect_on_demand_evidence

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised indirectly via available()
    OpenAI = None  # type: ignore[assignment]


SETTINGS: Optional[Settings] = None


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


def _is_previous_response_id_unsupported(error: BaseException) -> bool:
    message = str(error or "").lower()
    return "previous_response_id" in message and "only supported" in message


def _is_function_call_output_unsupported(error: BaseException) -> bool:
    message = str(error or "").lower()
    return "function_call_output" in message and "http requests" in message


_SEVERITY_ALIASES = {
    "critical": "critical",
    "error": "error",
    "warning": "warning",
    "warn": "warning",
    "info": "info",
    "unknown": "unknown",
    "严重": "critical",
    "错误": "error",
    "警告": "warning",
    "提示": "info",
    "信息": "info",
    "未知": "unknown",
}


def _normalize_severity(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return ""
    return _SEVERITY_ALIASES.get(candidate, candidate)


def _normalize_provider_evidence_lines(lines: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        normalized.append(text)
    return normalized


def _is_generic_rcs_root_cause(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    return normalized in {
        "RCS 主机关键服务链路异常。",
        "RCS 侧存在服务异常或端口不可用",
        "RCS 服务需要进一步核对",
    }


def _build_rcs_fallback_payload(evidence_lines: Sequence[str]) -> Dict[str, Any]:
    joined = "\n".join(evidence_lines)
    lower_joined = joined.lower()
    next_steps: List[str] = []
    evidence: List[str] = list(evidence_lines[:6])
    summary = "已根据远程取证补齐主机服务状态。"
    root_cause = "RCS 主机关键服务链路异常。"
    severity = "warning"
    confidence = "medium"

    backend_refused = "connection refused" in lower_joined or "后端 api 无响应" in lower_joined
    mysql_access_denied = "access denied for user 'root'@'localhost'" in lower_joined
    mysql_running = "docker-mysql_5_7-1" in lower_joined and "running false 0" in lower_joined
    supervisor_signal = "supervisord" in lower_joined or "supervisor" in lower_joined
    kernel_clean = "-- no entries --" in lower_joined and "journalctl -k" in lower_joined

    if backend_refused:
        severity = "error"
        root_cause = "RCS 主机后端 API 未监听，当前是主业务服务未拉起或已退出，不是单纯接口慢。"
        summary = "后端 3737 端口未监听，主业务服务当前未正常拉起。"
        next_steps.append("检查 master_backend / 调度相关服务进程是否存在，确认是谁没有拉起 3737 端口。")
    if mysql_running and mysql_access_denied:
        severity = "error" if severity != "error" else severity
        root_cause = (
            "MySQL 容器处于运行状态，但当前 root 无密码探活被拒；现阶段更像是探活鉴权不匹配，"
            "而不是 MySQL 容器本身已经停止。"
        )
        summary = "MySQL 容器在运行，但当前探活方式与现场鉴权不匹配。"
        next_steps.append("核对 MySQL 探活账号、密码和容器内认证方式，避免把鉴权失败误判成数据库故障。")
    if backend_refused and mysql_running and mysql_access_denied:
        summary = "后端 3737 未监听，且 MySQL 探活鉴权方式不匹配。"
        root_cause = (
            "RCS 主机当前更像是后端服务未监听 3737 端口，同时 MySQL 探活方式与现场认证不匹配；"
            "应优先排查 backend / supervisor 拉起链路，其次再核对数据库鉴权配置。"
        )
    if supervisor_signal:
        next_steps.append("直接核对 supervisor 日志中 master_backend、cbs_master_server 退出或等待结束的具体原因。")
    if kernel_clean:
        next_steps.append("当前 kernel / docker 日志未见明显系统级报错，优先聚焦应用层和守护进程链路。")
    if not next_steps:
        next_steps.extend(
            [
                "直接核对 supervisor、backend、mysql 的启动日志。",
                "确认 3737 端口由哪个服务负责拉起以及失败原因。",
            ]
        )

    return {
        "summary": summary,
        "root_cause": root_cause,
        "severity": severity,
        "next_steps": next_steps[:4],
        "evidence": evidence,
        "confidence": confidence,
    }


def _build_amr_fallback_payload(evidence_lines: Sequence[str]) -> Dict[str, Any]:
    joined = "\n".join(evidence_lines)
    lowered = joined.lower()
    next_steps: List[str] = []
    evidence: List[str] = list(evidence_lines[:8])
    summary = "已根据历史日志与远程取证补齐 AMR 故障证据。"
    root_cause = "AMR 历史故障仍需结合更多上下文继续复核。"
    severity = "warning"
    confidence = "medium"

    has_caution = "caution_" in lowered
    has_manual_recovery = any(token in lowered for token in ("switch to manual", "manual", "recover", "release", "retry", "切手动", "人工恢复"))
    has_low_level_chain = any(
        token in lowered
        for token in (
            "connection dropped",
            "reset embedded system",
            "cannot read eb",
            "cannot write eb",
            "can bus",
            "resume eb_interrupt",
            "can0",
            "pcan",
        )
    )
    front_scan_issue = re.search(r"laserscan.*front|front.*laserscan|front lidar|front radar|laser[a-z_ ]*front", joined, re.IGNORECASE)
    rear_scan_issue = re.search(r"laserscan.*rear|rear.*laserscan|rear lidar|rear radar|laser[a-z_ ]*rear", joined, re.IGNORECASE)
    low_level_unpublished = "/low_level_error 当前未发布" in joined or "topic [/low_level_error] does not appear to be published yet" in joined

    if front_scan_issue:
        severity = "error"
        root_cause = "故障时段前向扫描链路存在历史掉线或异常，优先核对前雷达及其上游 USB / 供电链路。"
        summary = "历史证据显示前向扫描链路在故障时段存在异常。"
        next_steps.append("继续核对前雷达对应的 default.launch、USB 枚举和上游供电链路。")
    elif rear_scan_issue:
        severity = "error"
        root_cause = "故障时段后向扫描链路存在历史掉线或异常，优先核对后雷达及其上游链路。"
        summary = "历史证据显示后向扫描链路在故障时段存在异常。"
        next_steps.append("继续核对后雷达对应的 launch 日志、USB 枚举和链路稳定性。")

    if has_low_level_chain:
        severity = "error"
        root_cause = "故障时段先出现底层嵌入式 / CAN 链路异常，扫描、定位或任务异常更像由底层通信失稳引发的派生表现。"
        summary = "历史证据显示首发异常更像底层嵌入式 / CAN 链路失稳。"
        next_steps.append("优先核对 mobile_base.launch 中的 CAN / EB / driver 异常与故障时间是否严格对齐。")

    if has_caution and "未找到" in root_cause:
        root_cause = "未找到对应 ROS 原始日志；但同时间段存在 caution 录包，建议继续结合 bag 前后状态变化定位首发异常。"
        summary = "ROS 原始日志不足，但同时间段存在 caution 录包可继续追根。"
        next_steps.append("优先下载同时间段 caution / bag，核对故障前后 20s~60s 的 /low_level_error、/scan、/amcl_pose、/odom、/motor_control/low_level_status 变化。")
    elif has_caution:
        next_steps.append("继续结合同时间段 caution / bag，核对故障前后 20s~60s 的 /low_level_error、/scan、/amcl_pose、/odom、/motor_control/low_level_status，确认首发异常与派生异常的先后顺序。")

    if has_manual_recovery:
        severity = "error" if severity == "error" else "warning"
        root_cause = "现场存在人工恢复或重试动作，这些更像掩盖首因的恢复手段；应优先回到第一次异常时间，结合底层链路与任务状态流判断首发根因。"
        summary = "历史证据显示现场存在人工恢复动作，首因可能被后续恢复操作掩盖。"
        next_steps.append("把人工切手动、重发任务、恢复操作的时间点单独列出，避免把恢复动作误判成根因。")

    if low_level_unpublished and not has_low_level_chain and not front_scan_issue and not rear_scan_issue:
        summary = "当前实时 /low_level_error 未提供补充错误码，仍应以故障时段历史 launch 日志为主证据。"
        root_cause = "当前实时 /low_level_error 未给出补充错误码，需优先依据历史 launch 与 bag 证据判断首发异常。"

    if not next_steps:
        next_steps.extend(
            [
                "优先回到故障第一次发生的时间点，核对开机目录下的 default.launch、mobile_base.launch、state_monitor_wrapper.launch。",
                "若同时间段存在 caution / bag，继续核对前后 20s~60s 的底层状态、扫描链路和任务状态变化。",
            ]
        )

    return {
        "summary": summary,
        "root_cause": root_cause,
        "severity": severity,
        "next_steps": next_steps[:4],
        "evidence": evidence,
        "confidence": confidence,
    }


@dataclass
class OpenAIProvider:
    name: str = "openai_sdk"
    settings: Optional[Settings] = None

    def _build_report_action_event(self, result: ProviderResult) -> ActionEvent:
        return build_action_event(
            action_type=ACTION_REPORT,
            source=self.name,
            payload={
                "summary": result.summary,
                "root_cause": result.root_cause,
                "severity": result.severity,
                "next_steps": list(result.next_steps),
                "evidence": list(result.evidence),
                "confidence": result.confidence,
            },
        )

    def _base_url(self) -> str:
        settings = _resolve_settings(self.settings)
        return os.getenv("OPENAI_BASE_URL", settings.llm.base_url).strip()

    def _api_key(self) -> str:
        settings = _resolve_settings(self.settings)
        return os.getenv(settings.llm.api_key_env, "").strip()

    def _model(self) -> str:
        settings = _resolve_settings(self.settings)
        return os.getenv("OPENAI_MODEL", settings.llm.model).strip()

    def available(self) -> bool:
        return bool(OpenAI is not None and self._api_key())

    def _client(self) -> Any:
        if OpenAI is None:
            raise RuntimeError("openai package is not available")
        return OpenAI(
            base_url=self._base_url(),
            api_key=self._api_key(),
        )

    def _build_instructions(self, request: ProviderRequest) -> str:
        base = (
            "你是 AMR/RCS 排障专家。"
            "请基于给定 route、target、context、evidence 输出结构化 JSON 诊断结果。"
            "顶层必须包含 summary、root_cause、severity、next_steps、evidence、confidence。"
            "不要输出 Markdown，不要输出代码块，不要输出额外解释。"
        )
        settings = _resolve_settings(self.settings)
        if settings.llm.enable_tool_calls:
            base += "必要时请通过函数调用申请 read_knowledge 或 secure_ssh_execute。"
        else:
            base += "本轮不要申请任何函数调用，只基于已有证据总结。"
        if request.route == "amr":
            base += (
                "如果需要查历史日志或录包路径，只能优先使用白名单内的只读命令。"
                "优先使用 /home/robot/log/not_permanent、/home/robot 下的 find/ls 命令，"
                "不要生成 bash -lc、管道、重定向、grep|head 组合，也不要扫描整个根目录。"
            )
        elif request.route == "rcs":
            base += (
                "如果证据里已经出现 supervisor 未运行、MySQL 异常、后端 API HTTP 000、死机后重启恢复 等信号，"
                "不要只停留在总结层，优先通过 secure_ssh_execute 继续核对 supervisor、mysql、backend、kernel 日志。"
                "优先使用 systemctl status、journalctl、docker logs、docker inspect、curl 这类白名单内只读命令。"
            )
        return base

    def _build_input(self, request: ProviderRequest) -> List[Dict[str, str]]:
        evidence_lines = [str(item).strip() for item in request.evidence if str(item).strip()]
        evidence_text = "\n".join(f"- {item}" for item in evidence_lines[:8]) or "- 暂无额外证据"
        content = "\n".join(
            [
                f"route: {request.route}",
                f"target: {request.target or '未指定'}",
                f"question: {request.question}",
                f"context: {request.context}",
                "evidence:",
                evidence_text,
                '请仅输出 JSON，对象键包含 summary、root_cause、severity、next_steps、evidence、confidence。',
            ]
        )
        return [{"role": "user", "content": content}]

    def _build_tool_result_followup_input(
        self,
        request: ProviderRequest,
        tool_outputs: Sequence[Dict[str, str]],
        action_events: Sequence[ActionEvent],
    ) -> List[Dict[str, str]]:
        evidence_lines = [str(item).strip() for item in request.evidence if str(item).strip()]
        for item in tool_outputs:
            output_text = str(item.get("output") or "").strip()
            if output_text:
                evidence_lines.append(f"tool_output: {output_text}")

        for event in action_events:
            if event.type == ACTION_READ_KNOWLEDGE:
                path = str(event.payload.get("path") or "").strip()
                excerpt = str(event.payload.get("excerpt") or "").strip()
                if path:
                    evidence_lines.append(f"knowledge_read[{path}]: {excerpt[:400]}")
            elif event.type == ACTION_SECURE_SSH_EXECUTE:
                command = str(event.payload.get("command") or "").strip()
                stdout = str(event.payload.get("stdout") or "").strip()
                stderr = str(event.payload.get("stderr") or "").strip()
                preview = stdout or stderr
                if command and preview:
                    evidence_lines.append(f"provider_execute[{command}]: {preview[:400]}")

        followup_request = ProviderRequest(
            route=request.route,
            question=request.question,
            context=request.context,
            evidence=tuple(evidence_lines),
            target=request.target,
        )
        return self._build_input(followup_request)

    def _extract_text_output(self, response: Any) -> str:
        output_text = getattr(response, "output_text", "") or ""
        if output_text:
            return str(output_text).strip()

        output = getattr(response, "output", None) or []
        text_parts: list[str] = []
        for item in output:
            for part in getattr(item, "content", None) or []:
                text_value = getattr(part, "text", None)
                if text_value:
                    text_parts.append(str(text_value))
        return "\n".join(part.strip() for part in text_parts if part).strip()

    def _parse_response_payload(self, raw_output: str) -> Dict[str, Any]:
        try:
            payload = json.loads(raw_output)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        payload = extract_json_object(raw_output)
        if payload:
            return payload
        return self._salvage_text_payload(raw_output)

    def _has_structured_json_payload(self, raw_output: str) -> bool:
        try:
            payload = json.loads(raw_output)
            return isinstance(payload, dict)
        except Exception:
            pass
        payload = extract_json_object(raw_output)
        return isinstance(payload, dict) and bool(payload)

    def _salvage_text_payload(self, raw_output: str) -> Dict[str, Any]:
        text = str(raw_output or "").strip()
        if not text:
            return {}

        lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
        if not lines:
            return {}

        payload: Dict[str, Any] = {
            "summary": "",
            "root_cause": "",
            "severity": "",
            "next_steps": [],
            "evidence": [],
            "confidence": "",
        }

        for line in lines:
            if not payload["summary"] and not any(token in line for token in ("root_cause", "severity", "confidence", "next_steps", "evidence")):
                payload["summary"] = line[:160]
            lowered = line.lower()
            if "root_cause" in lowered or "根因" in line:
                payload["root_cause"] = line.split(":", 1)[-1].strip() if ":" in line else line
            elif "severity" in lowered or "严重" in line:
                candidate = line.split(":", 1)[-1].strip() if ":" in line else line
                payload["severity"] = _normalize_severity(candidate)
            elif "confidence" in lowered or "置信" in line:
                payload["confidence"] = line.split(":", 1)[-1].strip() if ":" in line else line
            elif "next_steps" in lowered or "下一步" in line or "建议" in line:
                candidate = line.split(":", 1)[-1].strip() if ":" in line else line
                if candidate and candidate not in payload["next_steps"]:
                    payload["next_steps"].append(candidate)
            elif "evidence" in lowered or "证据" in line:
                candidate = line.split(":", 1)[-1].strip() if ":" in line else line
                if candidate and candidate not in payload["evidence"]:
                    payload["evidence"].append(candidate)

        if not payload["root_cause"]:
            payload["root_cause"] = lines[min(1, len(lines) - 1)][:240]
        if not payload["severity"]:
            payload["severity"] = "warning"
        if not payload["next_steps"]:
            bullet_lines = [
                line for line in lines
                if re.match(r"^(?:[0-9]+[.)]|[-*])\s*", line)
            ]
            payload["next_steps"] = [re.sub(r"^(?:[0-9]+[.)]|[-*])\s*", "", line).strip() for line in bullet_lines[:3] if line.strip()]
        if not payload["evidence"]:
            payload["evidence"] = lines[1:3]
        if not payload["confidence"]:
            payload["confidence"] = "medium"

        return payload

    def _fallback_payload_from_tool_evidence(
        self,
        request: ProviderRequest,
        action_events: Sequence[ActionEvent],
        raw_output: str,
    ) -> Dict[str, Any]:
        evidence_lines: List[str] = []
        for event in action_events:
            payload = getattr(event, "payload", {}) or {}
            if not isinstance(payload, dict):
                continue
            event_type = str(getattr(event, "type", "") or "")
            if event_type == ACTION_SECURE_SSH_EXECUTE:
                command = str(payload.get("command") or "").strip()
                stdout = str(payload.get("stdout") or "").strip()
                stderr = str(payload.get("stderr") or "").strip()
                preview = stdout or stderr
                if command and preview:
                    evidence_lines.append(f"provider_execute[{command}]: {preview[:500]}")
            elif event_type == ACTION_READ_KNOWLEDGE:
                path = str(payload.get("path") or "").strip()
                excerpt = str(payload.get("excerpt") or "").strip()
                if path and excerpt:
                    evidence_lines.append(f"knowledge_read[{path}]: {excerpt[:300]}")

        evidence_lines = _normalize_provider_evidence_lines(evidence_lines)
        if request.route == "amr" and evidence_lines:
            fallback = _build_amr_fallback_payload(evidence_lines)
            if raw_output.strip():
                fallback["summary"] = fallback.get("summary") or "模型未返回标准 JSON，已根据历史取证自动生成兜底结论。"
            return fallback
        if request.route == "rcs" and evidence_lines:
            fallback = _build_rcs_fallback_payload(evidence_lines)
            if raw_output.strip():
                fallback["summary"] = "模型未返回标准 JSON，已根据远程取证自动生成兜底结论。"
            return fallback
        return {}

    def _build_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "read_knowledge",
                "description": "读取 knowledge/ 下的单个 Markdown 文档摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "secure_ssh_execute",
                "description": "执行单条受控只读命令并返回输出",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        ]

    def _iter_function_calls(self, response: Any) -> List[Any]:
        output = getattr(response, "output", None) or []
        return [item for item in output if getattr(item, "type", "") == "function_call"]

    def _tool_output_item(self, call_id: str, output: str) -> Dict[str, str]:
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        }

    def _handle_tool_call(self, request: ProviderRequest, tool_call: Any) -> Tuple[Optional[Dict[str, str]], Optional[ActionEvent]]:
        call_id = str(getattr(tool_call, "call_id", "") or getattr(tool_call, "id", "") or "").strip()
        tool_name = str(getattr(tool_call, "name", "") or "").strip()
        raw_arguments = getattr(tool_call, "arguments", "") or "{}"

        try:
            arguments = json.loads(raw_arguments)
        except Exception:
            arguments = {}

        if tool_name == "read_knowledge":
            path = str(arguments.get("path") or "").strip()
            settings = _resolve_settings(self.settings)
            excerpt, error = load_knowledge_excerpt(path, max_chars=800, max_lines=12, settings=settings)
            payload = {"ok": not error, "path": path, "excerpt": excerpt, "error": error}
            return (
                self._tool_output_item(call_id, json.dumps(payload, ensure_ascii=False)),
                build_action_event(
                    action_type=ACTION_READ_KNOWLEDGE,
                    source=self.name,
                    payload={
                        "path": path,
                        "excerpt": excerpt,
                        "ok": not error,
                    },
                ),
            )

        if tool_name == "secure_ssh_execute":
            command = str(arguments.get("command") or "").strip()
            settings = _resolve_settings(self.settings)
            report = collect_on_demand_evidence(request.route, request.target, command, settings=settings)
            results = list(report.get("results") or [])
            result = results[0] if results else None
            payload = {
                "ok": bool(result and getattr(result, "returncode", 1) == 0),
                "command": command,
                "stdout": getattr(result, "stdout", "") if result else "",
                "stderr": getattr(result, "stderr", "") if result else "no result",
                "returncode": getattr(result, "returncode", 1) if result else 1,
            }
            return (
                self._tool_output_item(call_id, json.dumps(payload, ensure_ascii=False)),
                build_action_event(
                    action_type=ACTION_SECURE_SSH_EXECUTE,
                    source=self.name,
                    payload=payload,
                ),
            )

        return (
            self._tool_output_item(
                call_id,
                json.dumps(
                    {"ok": False, "error": f"unsupported tool: {tool_name}"},
                    ensure_ascii=False,
                ),
            ),
            None,
        )

    def _request_once(
        self,
        *,
        client: Any,
        request: ProviderRequest,
        input_items: Sequence[Dict[str, str]],
        previous_response_id: str = "",
    ) -> Any:
        settings = _resolve_settings(self.settings)
        kwargs: Dict[str, Any] = {
            "model": self._model(),
            "instructions": self._build_instructions(request),
            "input": list(input_items),
            "parallel_tool_calls": settings.llm.parallel_tool_calls,
            "store": settings.llm.store_responses,
        }
        if settings.llm.enable_tool_calls:
            kwargs["tools"] = self._build_tools()
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        return client.responses.create(**kwargs)

    def run(self, request: ProviderRequest) -> ProviderResult:
        if not self.available():
            result = ProviderResult(
                provider_name=self.name,
                summary="openai_sdk provider 当前不可用。",
                next_steps=(
                    "确认已安装 openai Python SDK。",
                    "确认 OPENAI_API_KEY 已设置。",
                    "确认 OPENAI_BASE_URL 与 OPENAI_MODEL 配置正确。",
                ),
                confidence="low",
            )
            return ProviderResult(
                provider_name=result.provider_name,
                summary=result.summary,
                next_steps=result.next_steps,
                root_cause=result.root_cause,
                severity=result.severity,
                evidence=result.evidence,
                action_events=(self._build_report_action_event(result),),
                confidence=result.confidence,
                raw_output=result.raw_output,
            )

        client = self._client()
        response = self._request_once(
            client=client,
            request=request,
            input_items=self._build_input(request),
        )
        settings = _resolve_settings(self.settings)
        function_calls = self._iter_function_calls(response) if settings.llm.enable_tool_calls else []
        action_events: List[ActionEvent] = []
        if function_calls:
            tool_outputs = []
            for tool_call in function_calls:
                tool_output, action_event = self._handle_tool_call(request, tool_call)
                if tool_output:
                    tool_outputs.append(tool_output)
                if action_event:
                    action_events.append(action_event)
            previous_response_id = str(getattr(response, "id", "") or "")
            try:
                response = self._request_once(
                    client=client,
                    request=request,
                    input_items=tool_outputs,
                    previous_response_id=previous_response_id,
                )
            except Exception as error:
                if previous_response_id and _is_previous_response_id_unsupported(error):
                    try:
                        response = self._request_once(
                            client=client,
                            request=request,
                            input_items=tool_outputs,
                        )
                    except Exception as retry_error:
                        if not _is_function_call_output_unsupported(retry_error):
                            raise
                        response = self._request_once(
                            client=client,
                            request=request,
                            input_items=self._build_tool_result_followup_input(request, tool_outputs, action_events),
                        )
                elif _is_function_call_output_unsupported(error):
                    response = self._request_once(
                        client=client,
                        request=request,
                        input_items=self._build_tool_result_followup_input(request, tool_outputs, action_events),
                    )
                else:
                    raise
        raw_output = self._extract_text_output(response)
        payload = self._parse_response_payload(raw_output)
        has_structured_json_payload = self._has_structured_json_payload(raw_output)
        if (
            action_events
            and (
                not has_structured_json_payload
                or (
                    has_structured_json_payload
                    and (
                        not str(payload.get("root_cause") or "").strip()
                        or _is_generic_rcs_root_cause(str(payload.get("root_cause") or ""))
                        or str(payload.get("summary") or "").strip() in {"", "openai_sdk 未返回结构化结论。"}
                    )
                )
            )
        ):
            fallback_payload = self._fallback_payload_from_tool_evidence(request, action_events, raw_output)
            if fallback_payload:
                merged_payload = dict(fallback_payload)
                for key, value in payload.items():
                    if not value:
                        continue
                    if key in {"summary", "root_cause", "severity"}:
                        continue
                    merged_payload[key] = value
                payload = merged_payload

        next_steps = payload.get("next_steps") or []
        evidence = payload.get("evidence") or []
        if isinstance(next_steps, str):
            next_steps = [next_steps]
        if isinstance(evidence, str):
            evidence = [evidence]

        result = ProviderResult(
            provider_name=self.name,
            summary=str(payload.get("summary") or raw_output or "openai_sdk 未返回结构化结论。"),
            next_steps=tuple(str(item) for item in next_steps if str(item).strip()),
            root_cause=str(payload.get("root_cause") or ""),
            severity=str(payload.get("severity") or ""),
            evidence=tuple(str(item) for item in evidence if str(item).strip()),
            action_events=tuple(action_events),
            confidence=str(payload.get("confidence") or ("medium" if raw_output else "low")),
            raw_output=raw_output,
        )
        return ProviderResult(
            provider_name=result.provider_name,
            summary=result.summary,
            next_steps=result.next_steps,
            root_cause=result.root_cause,
            severity=result.severity,
            evidence=result.evidence,
            action_events=tuple(list(result.action_events) + [self._build_report_action_event(result)]),
            confidence=result.confidence,
            raw_output=result.raw_output,
        )
