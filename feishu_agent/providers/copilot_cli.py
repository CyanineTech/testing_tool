import json
import os
import logging
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from feishu_agent.core.cli_wrapper import CliObservation, PtyCliWrapper
from feishu_agent.knowledge.loader import load_knowledge_excerpt
from feishu_agent.protocols.actions import (
    ACTION_READ_KNOWLEDGE,
    ACTION_REPORT,
    ACTION_SECURE_SSH_EXECUTE,
    ActionEvent,
    build_action_event,
)
from feishu_agent.providers.base import (
    ProviderRequest,
    ProviderResult,
    _write_provider_trace,
    build_interactive_protocol_prompt,
    build_provider_prompt,
    extract_json_object,
    parse_provider_output,
    run_provider_command,
)
from feishu_agent.ssh.collect import collect_on_demand_evidence


@dataclass
class CopilotCliProvider:
    name: str = "copilotcli"
    _PTY_FALLBACK_EVIDENCE = {"pty_stalled_no_blocks", "pty_partial_report_timeout"}

    _AUTH_ERROR_MARKERS = (
        "Error: No authentication information found.",
        "Copilot can be authenticated with GitHub",
        "Start 'copilot' and run the '/login' command",
    )
    _QUOTA_ERROR_MARKERS = (
        "You have exceeded your monthly quota",
        "AI Credits: 0",
        "quota exceeded",
    )

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

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        payload = extract_json_object(text)
        if isinstance(payload, dict) and (payload.get("summary") or payload.get("answer")):
            return payload
        return {}

    def _extract_assistant_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()

        if isinstance(payload, list):
            parts = [self._extract_assistant_text(item) for item in payload]
            return "\n".join(part for part in parts if part).strip()

        if not isinstance(payload, dict):
            return ""

        for key in ("deltaContent", "content", "text", "message", "value", "parts", "items"):
            value = payload.get(key)
            extracted = self._extract_assistant_text(value)
            if extracted:
                return extracted
        return ""

    def _normalize_mcp_path(self, configured: str) -> str:
        if not configured:
            return ""
        path = configured[1:] if configured.startswith("@") else configured
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded) and os.access(expanded, os.R_OK):
            return f"@{expanded}"
        logging.warning("copilot provider ignored unreadable MCP config %s", configured)
        return ""

    def _resolve_additional_mcp(self) -> str:
        configured = os.getenv("COPILOTCLI_ADDITIONAL_MCP", "").strip()
        if configured:
            normalized = self._normalize_mcp_path(configured)
            if normalized:
                return normalized

        default_paths = (
            "/etc/copilot/mcp-config.json",
            os.path.expanduser("~/.copilot/mcp-config.json"),
            "/home/robot/.copilot/mcp-config.json",
        )
        for path in default_paths:
            if os.path.isfile(path) and os.access(path, os.R_OK):
                return f"@{path}"
        return ""

    def available(self) -> bool:
        return bool(os.getenv("COPILOTCLI_COMMAND", ""))

    def _interactive_command(self, command: str, prompt: str) -> List[str]:
        interactive_command = os.getenv("COPILOTCLI_INTERACTIVE_COMMAND", "").strip() or command
        interactive_args = os.getenv("COPILOTCLI_INTERACTIVE_ARGS", "").strip()
        parts = shlex.split(interactive_command)
        if interactive_args:
            parts.extend(shlex.split(interactive_args))
        else:
            parts.extend([
                "-i",
                "--no-color",
                "--stream",
                "off",
                "--no-custom-instructions",
                "--disable-builtin-mcps",
                "--available-tools=",
            ])
        return parts

    def _run_interactive_protocol(self, command: str, request: ProviderRequest, timeout_seconds: int) -> ProviderResult:
        wrapper = PtyCliWrapper()
        prompt = build_interactive_protocol_prompt(request)
        interactive_command = self._interactive_command(command, prompt)
        # Copilot CLI interactive mode expects the prompt on stdin. Passing the
        # full prompt as an extra CLI argument causes the session to hang or fail.
        cmd_display = " ".join(interactive_command)
        _write_provider_trace(
            "pty_prompt_ready",
            cmd_display,
            timeout_seconds=timeout_seconds,
            prompt_length=len(prompt),
            prompt_preview=prompt[:800],
        )

        def handle_action(action) -> CliObservation:
            action_body = action.body.strip()
            if action.kind == "read_knowledge":
                excerpt, error = load_knowledge_excerpt(action_body, max_chars=260, max_lines=8)
                if not error and any(token in request.question for token in ("不要 execute", "不要执行", "无需执行", "不要跑命令")):
                    excerpt = (
                        f"{excerpt}\n"
                        "系统提示：本轮禁止 execute；你已经完成本轮第一份知识读取。"
                        "除非你明确需要第二份 knowledge，否则下一条必须直接输出 report。"
                    )
                _write_provider_trace(
                    "pty_read_knowledge",
                    cmd_display,
                    path=action_body,
                    success=not error,
                    excerpt_preview=excerpt[:400],
                    error=error,
                )
                return CliObservation(
                    command=action_body,
                    returncode=0 if not error else 126,
                    stdout=excerpt,
                    stderr=error,
                    source="knowledge",
                )
            action_target = request.target
            if request.route == "knowledge" or request.target == "knowledge" or action_body.startswith("local:"):
                action_target = ""
            report = collect_on_demand_evidence(request.route, action_target, action_body)
            result = list(report.get("results") or [])[0]
            return CliObservation(
                command=result.command,
                returncode=result.returncode,
                stdout=(result.stdout or "")[:4000],
                stderr=(result.stderr or "")[:2000],
                source=getattr(result, "mode", "sandbox"),
            )

        session = wrapper.run(
            command=interactive_command,
            initial_prompt=prompt,
            action_handler=handle_action,
            timeout_seconds=timeout_seconds,
        )
        _write_provider_trace(
            "pty_session_finish",
            cmd_display,
            timed_out=session.timed_out,
            stop_reason=session.stop_reason,
            actions_executed=len(session.actions),
            observations=len(session.observations),
            raw_output_preview=session.raw_output[:800],
            report_payload=session.report_payload,
        )

        if self._is_quota_error(session.raw_output):
            return self._quota_error_result(session.raw_output)

        if not session.report_payload:
            if session.stop_reason == "stalled_no_blocks":
                return self._pty_stalled_result(session.raw_output)
            if session.stop_reason == "deadline_timeout" and self._looks_like_partial_report(session.raw_output):
                return self._pty_partial_report_result(session.raw_output)
            raise RuntimeError("pty interactive session did not return report payload")

        parsed = parse_provider_output(json.dumps(session.report_payload, ensure_ascii=False))
        observation_evidence = []
        action_events: List[ActionEvent] = []
        for item in session.observations:
            preview = (item.stdout or item.stderr or "").strip()
            if preview:
                if item.source == "knowledge":
                    observation_evidence.append(f"knowledge_read[{item.command}]: {preview[:400]}")
                    action_events.append(
                        build_action_event(
                            action_type=ACTION_READ_KNOWLEDGE,
                            source=self.name,
                            payload={
                                "path": item.command,
                                "excerpt": preview[:400],
                                "ok": item.returncode == 0,
                            },
                        )
                    )
                else:
                    observation_evidence.append(f"{item.source}:{item.command} => {preview[:400]}")
                    action_events.append(
                        build_action_event(
                            action_type=ACTION_SECURE_SSH_EXECUTE,
                            source=self.name,
                            payload={
                                "command": item.command,
                                "stdout": item.stdout[:400],
                                "stderr": item.stderr[:200],
                                "returncode": item.returncode,
                                "mode": item.source,
                            },
                        )
                    )

        result = ProviderResult(
            provider_name=self.name,
            summary=parsed.get("summary") or session.raw_output or "copilotcli 未返回 report。",
            next_steps=tuple(parsed.get("next_steps") or ()),
            root_cause=str(parsed.get("root_cause") or ""),
            severity=str(parsed.get("severity") or ""),
            evidence=tuple(str(item) for item in parsed.get("evidence") or ()) + tuple(observation_evidence),
            action_events=tuple(action_events),
            confidence=str(parsed.get("confidence") or ("low" if session.timed_out else "medium")),
            raw_output=session.raw_output,
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

    def _looks_like_jsonl_event_stream(self, raw_output: str) -> bool:
        lines = [line.strip() for line in (raw_output or "").splitlines() if line.strip()]
        if not lines:
            return False

        event_lines = 0
        for line in lines:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("type"), str):
                event_lines += 1

        return event_lines > 0 and event_lines >= max(1, len(lines) // 2)

    def _parse_jsonl_output(self, raw_output: str) -> Tuple[Dict[str, Any], str, List[str]]:
        parsed_payload: Dict[str, Any] = {}
        root_cause = ""
        evidence: List[str] = []
        assistant_chunks: List[str] = []

        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue

            if not isinstance(payload, dict):
                continue

            event_type = str(payload.get("type") or "")
            data = payload.get("data")
            if event_type == "session.warning" and isinstance(data, dict):
                warning_type = str(data.get("warningType") or "")
                message = str(data.get("message") or "")
                if warning_type == "policy" and message:
                    root_cause = message
                    evidence.append(f"policy_warning: {message}")
                continue

            if event_type == "session.mcp_servers_loaded" and isinstance(data, dict):
                servers = data.get("servers") or []
                if isinstance(servers, list) and servers:
                    formatted = ", ".join(
                        str(server.get("name") or "unknown")
                        for server in servers
                        if isinstance(server, dict)
                    )
                    if formatted:
                        evidence.append(f"mcp_servers_loaded: {formatted}")
                continue

            if event_type == "session.mcp_server_status_changed" and isinstance(data, dict):
                server_name = str(data.get("serverName") or "unknown")
                status = str(data.get("status") or "unknown")
                evidence.append(f"mcp_server_status: {server_name}={status}")
                continue

            if event_type.startswith("assistant."):
                content = self._extract_assistant_text(data)
                if content:
                    assistant_chunks.append(content)
                continue

            if "summary" in payload or "answer" in payload:
                parsed_payload = payload

        assistant_content = "".join(assistant_chunks).strip()
        if not parsed_payload and assistant_content:
            parsed_payload = self._extract_json_object(assistant_content)

        return parsed_payload, root_cause, evidence

    def _is_auth_error(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        return any(marker in normalized for marker in self._AUTH_ERROR_MARKERS)

    def _is_quota_error(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        return any(marker.lower() in normalized for marker in self._QUOTA_ERROR_MARKERS)

    def _auth_error_result(self) -> ProviderResult:
        result = ProviderResult(
            provider_name=self.name,
            summary="当前 Copilot 认证状态异常，模型复核暂时不可用。",
            next_steps=(
                "稍后重新发起一次相同问题，确认是否为瞬时认证异常。",
                "如果持续复现，检查 feishu_agent 服务里的 Copilot token 或登录态。",
                "确认服务重启后仍可执行一次最小 copilot -p 探针。",
            ),
            root_cause="Copilot CLI 返回认证异常，当前请求未完成模型复核。",
            severity="警告",
            evidence=("copilot_auth_error",),
            confidence="low",
            raw_output="copilot_auth_error",
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

    def _quota_error_result(self, raw_output: str) -> ProviderResult:
        result = ProviderResult(
            provider_name=self.name,
            summary="当前 Copilot 月度额度已用尽，模型复核暂时不可用。",
            next_steps=(
                "先用本地排障脚本和知识库继续首轮排查，不依赖模型复核。",
                "恢复 Copilot 额度或切换到其它可用 provider 后，再重试同一条问题。",
                "若只需验证消息链路，可先发一条最小测试消息确认机器人仍能入站并回帖。",
            ),
            root_cause="Copilot CLI 返回月度额度耗尽，当前请求无法完成模型复核。",
            severity="警告",
            evidence=("copilot_quota_exhausted",),
            confidence="low",
            raw_output=raw_output[:4000],
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

    def _pty_stalled_result(self, raw_output: str) -> ProviderResult:
        result = ProviderResult(
            provider_name=self.name,
            summary="copilotcli PTY 工作态卡住，未产出受控协议块。",
            next_steps=(
                "缩短 interactive prompt 内容，只保留最小 question、context 和 1 到 2 条 evidence 后重试。",
                "继续查看 provider_trace.log，确认后续是否仍只有 Working esc cancel 而没有 read_knowledge / execute / report。",
                "如果 PTY 继续卡住，暂时回退到 single-shot 或继续收紧 PTY 路由范围。",
            ),
            root_cause="PTY 会话进入工作态后持续无块输出，当前未拿到 read_knowledge、execute 或 report。",
            severity="警告",
            evidence=("pty_stalled_no_blocks",),
            confidence="low",
            raw_output=raw_output[:4000],
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

    def _looks_like_partial_report(self, raw_output: str) -> bool:
        compact = raw_output or ""
        return (
            '"summary"' in compact
            and '"root_cause"' in compact
            and '"severity"' in compact
            and '"next_steps"' in compact
        )

    def _pty_partial_report_result(self, raw_output: str) -> ProviderResult:
        result = ProviderResult(
            provider_name=self.name,
            summary="copilotcli PTY 已输出报告片段，但未形成可解析的最终 report。",
            next_steps=(
                "继续保持紧凑 prompt，避免重新加入大段格式说明或重复规则。",
                "把 PTY 路由继续限制在最小 probe 或极少量 AMR case，不要扩大到 network/rcs。",
                "后续若要继续提升成功率，优先针对 transcript 中重复回显 prompt 的模式做专门裁剪，而不是继续放宽协议。",
            ),
            root_cause="PTY 会话在超时前只输出了残缺或重复的 report-like JSON 片段，未形成可解析对象。",
            severity="警告",
            evidence=("pty_partial_report_timeout",),
            confidence="low",
            raw_output=raw_output[:4000],
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

    def _should_fallback_from_pty(self, result: ProviderResult) -> bool:
        return any(item in self._PTY_FALLBACK_EVIDENCE for item in result.evidence)

    def _run_single_shot(self, command: str, payload: str, timeout_seconds: int) -> Tuple[int, str, str, bool]:
        cmd = [command, "-p", payload, "--output-format", "json", "--silent"]
        additional_mcp = self._resolve_additional_mcp()
        if additional_mcp:
            cmd.extend(["--additional-mcp-config", additional_mcp])
            logging.info("copilot provider using additional MCP config %s", additional_mcp)
        return run_provider_command(
            command=cmd,
            input_text=None,
            timeout_seconds=timeout_seconds,
        )

    def run(self, request: ProviderRequest) -> ProviderResult:
        command = os.getenv("COPILOTCLI_COMMAND", "")
        if not command:
            result = ProviderResult(
                provider_name=self.name,
                summary="copilotcli 未配置，跳过模型复核。",
                next_steps=(),
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

        timeout_seconds = int(os.getenv("COPILOTCLI_TIMEOUT", "600"))
        timeout_cap_seconds = int(os.getenv("COPILOTCLI_TIMEOUT_CAP", "90"))
        timeout_seconds = max(15, min(timeout_seconds, timeout_cap_seconds))
        logging.info(
            "copilot provider request route=%s target=%s question_preview=%s evidence_count=%s",
            request.route,
            request.target,
            request.question[:80],
            len(request.evidence),
        )
        pty_enabled = os.getenv("COPILOTCLI_ENABLE_PTY_PROTOCOL", "0") == "1"
        pty_routes = {
            route.strip()
            for route in os.getenv("COPILOTCLI_PTY_ROUTES", "").split(",")
            if route.strip()
        }
        if pty_enabled and request.route in pty_routes:
            try:
                pty_result = self._run_interactive_protocol(command, request, timeout_seconds)
                if not self._should_fallback_from_pty(pty_result):
                    return pty_result
                logging.warning(
                    "copilot interactive protocol returned fallback-worthy result, degrading to single-shot mode: %s",
                    ",".join(str(item) for item in pty_result.evidence),
                )
            except Exception as exc:
                logging.warning("copilot interactive protocol failed, fallback to single-shot mode: %s", exc)

        payload = build_provider_prompt(request)
        returncode, stdout, stderr, timed_out = self._run_single_shot(command, payload, timeout_seconds)
        raw_output = (stdout or stderr or "").strip()
        if self._is_quota_error(raw_output):
            logging.warning("copilot provider hit quota exhaustion in single-shot mode")
            return self._quota_error_result(raw_output)
        if self._is_auth_error(raw_output):
            logging.warning("copilot provider hit auth error, retrying single-shot once")
            returncode, stdout, stderr, timed_out = self._run_single_shot(command, payload, timeout_seconds)
            raw_output = (stdout or stderr or "").strip()
            if self._is_quota_error(raw_output):
                logging.warning("copilot provider hit quota exhaustion after auth retry")
                return self._quota_error_result(raw_output)
            if self._is_auth_error(raw_output):
                logging.error("copilot provider auth error persisted after retry")
                return self._auth_error_result()
        parsed = parse_provider_output(raw_output)
        root_cause = ""
        derived_evidence: Tuple[str, ...] = ()
        if not parsed and raw_output:
            jsonl_payload, root_cause, jsonl_evidence = self._parse_jsonl_output(raw_output)
            if jsonl_payload:
                parsed = parse_provider_output(json.dumps(jsonl_payload, ensure_ascii=False))
            derived_evidence = tuple(jsonl_evidence)
        suppressed_raw_output = self._looks_like_jsonl_event_stream(raw_output)
        fallback_summary = (
            "copilotcli 超时后已终止。"
            if timed_out
            else "copilotcli 未返回可解析诊断结果。"
            if suppressed_raw_output
            else "copilotcli 未返回结果。"
        )
        effective_root_cause = str(parsed.get("root_cause") or (root_cause if parsed else ""))
        result = ProviderResult(
            provider_name=self.name,
            summary=parsed.get("summary") or (raw_output if (raw_output and not timed_out and not suppressed_raw_output) else fallback_summary),
            next_steps=tuple(parsed.get("next_steps") or ()),
            root_cause=effective_root_cause,
            severity=str(parsed.get("severity") or ""),
            evidence=tuple(str(item) for item in parsed.get("evidence") or ()) + derived_evidence,
            confidence=str(parsed.get("confidence") or ("low" if timed_out or suppressed_raw_output else "medium" if returncode == 0 else "low")),
            raw_output=raw_output,
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
