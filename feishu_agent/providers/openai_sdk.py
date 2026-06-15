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
