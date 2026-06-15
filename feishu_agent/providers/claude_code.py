import os
import logging
from dataclasses import dataclass
from typing import Any, Dict

from feishu_agent.providers.base import ProviderRequest, ProviderResult, build_provider_prompt, parse_provider_output, run_provider_command


@dataclass
class ClaudeCodeProvider:
    name: str = "claude-code"

    def available(self) -> bool:
        return bool(os.getenv("CLAUDE_CODE_COMMAND", ""))

    def run(self, request: ProviderRequest) -> ProviderResult:
        command = os.getenv("CLAUDE_CODE_COMMAND", "")
        if not command:
            return ProviderResult(
                provider_name=self.name,
                summary="Claude Code 未配置，跳过模型复核。",
                next_steps=(),
                confidence="low",
            )

        payload = build_provider_prompt(request)
        logging.info(
            "claude provider request route=%s target=%s question_preview=%s evidence_count=%s",
            request.route,
            request.target,
            request.question[:80],
            len(request.evidence),
        )
        # Run claude-code in non-interactive prompt mode
        cmd = [command, "-p", payload, "--output-format", "json", "--silent"]
        returncode, stdout, stderr, timed_out = run_provider_command(
            command=cmd,
            input_text=None,
            timeout_seconds=int(os.getenv("CLAUDE_CODE_TIMEOUT", "600")),
        )
        raw_output = (stdout or stderr or "").strip()
        parsed = parse_provider_output(raw_output)
        return ProviderResult(
            provider_name=self.name,
            summary=parsed.get("summary") or raw_output or ("Claude Code 超时后已终止。" if timed_out else "Claude Code 未返回结果。"),
            next_steps=tuple(parsed.get("next_steps") or ()),
            root_cause=str(parsed.get("root_cause") or ""),
            severity=str(parsed.get("severity") or ""),
            evidence=tuple(str(item) for item in parsed.get("evidence") or ()),
            confidence=str(parsed.get("confidence") or ("low" if timed_out else "medium" if returncode == 0 else "low")),
            raw_output=raw_output,
        )
