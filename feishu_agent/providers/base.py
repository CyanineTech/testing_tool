import json
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Protocol, Sequence, Tuple, Union, Optional

from feishu_agent.protocols.actions import ActionEvent


@dataclass(frozen=True)
class ProviderRequest:
    route: str
    question: str
    context: str
    evidence: Sequence[str]
    target: str = ""


@dataclass(frozen=True)
class ProviderResult:
    provider_name: str
    summary: str
    next_steps: Sequence[str]
    root_cause: str = ""
    severity: str = ""
    evidence: Sequence[str] = ()
    action_events: Sequence[ActionEvent] = ()
    confidence: str = "unknown"
    raw_output: str = ""


class LlmProvider(Protocol):
    name: str

    def available(self) -> bool:
        ...

    def run(self, request: ProviderRequest) -> ProviderResult:
        ...


def _resolve_provider_trace_file() -> Path:
    trace_file = os.getenv("FEISHU_PROVIDER_TRACE_FILE", "").strip()
    if trace_file:
        return Path(trace_file).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "logs" / "provider_trace.log"


def _write_provider_trace(stage: str, command: str, **fields: Any) -> None:
    trace_path = _resolve_provider_trace_file()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stage": stage, "command": command, "timestamp": time.time(), **fields}
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with trace_path.open("a", encoding="utf-8") as trace_file:
        trace_file.write(line + "\n")

    def run(self, request: ProviderRequest) -> ProviderResult:
        ...


def build_provider_prompt(request: ProviderRequest) -> str:
    compact_question = (request.question or "").strip()[:400]
    compact_context = (request.context or "").strip()[:1600]
    compact_evidence = [str(item).strip()[:300] for item in request.evidence if str(item).strip()][:8]
    payload: Dict[str, Any] = {
        "protocol": "feishu_agent.provider.v1",
        "route": request.route,
        "question": compact_question,
        "context": compact_context,
        "target": request.target,
        "evidence": compact_evidence,
        "output_schema": {
            "summary": "string",
            "root_cause": "string",
            "severity": "string",
            "next_steps": ["string"],
            "evidence": ["string"],
            "confidence": "low|medium|high|unknown",
        },
        "rules": [
            "只输出 JSON",
            "不要输出额外解释",
            "summary 必须简短",
            "root_cause 和 severity 尽量给出明确判断",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def build_interactive_protocol_prompt(request: ProviderRequest) -> str:
    raw_evidence_lines = [str(item).strip() for item in request.evidence if str(item).strip()]
    evidence_lines = []
    for item in raw_evidence_lines:
        if item.startswith("doc_excerpt["):
            continue
        compact = item if len(item) <= 180 else f"{item[:177]}..."
        evidence_lines.append(compact)
    evidence_text = "\n".join(f"- {item}" for item in evidence_lines[:6]) or "- 暂无额外证据"
    target_text = request.target or "未指定"
    no_execute_requested = any(
        token in request.question
        for token in (
            "不要执行",
            "无需执行",
            "不要跑命令",
            "不要 execute",
            "只做协议连通性测试",
            "只做动作连通性测试",
        )
    )
    knowledge_only = request.route == "knowledge" or request.target == "knowledge"
    read_knowledge_first = "第一步必须且只能输出一个 read_knowledge" in request.question
    single_candidate = ""
    for item in raw_evidence_lines:
        if item.startswith("knowledge_candidates:"):
            candidates = [part.strip() for part in item.split(":", 1)[1].split(",") if part.strip()]
            if len(candidates) == 1:
                single_candidate = candidates[0]
            break

    if read_knowledge_first and single_candidate:
        return (
            "你是 AMR/RCS 排障专家。\n"
            f"第一步必须且只能输出一个 read_knowledge 代码块，正文只能是 {single_candidate}。\n"
            "不要输出 execute。不要输出 report。不要解释。\n"
            "如果看到工具界面或确认菜单，停止那种输出，改回 read_knowledge 代码块。\n"
        )

    parts = [
        "你是 AMR/RCS 排障专家，必须严格遵守受控协议。\n",
        f"route: {request.route}\n",
        f"target: {target_text}\n",
        f"question: {request.question}\n",
        f"context: {request.context}\n",
        "evidence:\n",
        f"{evidence_text}\n",
        "\n",
        "只允许以下三种输出之一：\n",
        "- read_knowledge 代码块：正文只写一个 knowledge/*.md 路径。\n",
        "- execute 代码块：正文只写一条命令。\n",
        "- report 代码块：正文必须是 JSON，对象键包含 summary、root_cause、severity、next_steps、evidence、confidence。\n",
        "禁止使用 Copilot 内建 Search/Read/Check/shell 工具。不要搜索文件，不要读取工作区文件，不要直接运行命令。\n",
        "即使你认为应该执行脚本或查看文件，也必须先输出 read_knowledge 或 execute 代码块，由外层系统代你完成。\n",
        "不要输出其它解释、命令建议、确认菜单或 Copilot 内建工具调用。\n",
        "证据不足时可以继续 read_knowledge 或 execute；结论足够时立即输出 report。\n",
        "如果看到 shell 确认或工具界面，停止那种输出，改回 read_knowledge、execute 或 report。\n",
    ]
    if no_execute_requested:
        parts.append("本轮禁止执行命令，因此你不能输出 execute。\n")
    if knowledge_only:
        parts.append("本轮是 knowledge 路由，因此不能输出 execute；如需补充，只能输出 read_knowledge 或 report。\n")
    return "".join(parts)


def parse_provider_output(raw_output: str) -> Dict[str, Any]:
    if not raw_output:
        return {}

    try:
        payload = json.loads(raw_output)
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    next_steps = payload.get("next_steps") or payload.get("nextSteps") or []
    evidence = payload.get("evidence") or []
    if isinstance(next_steps, str):
        next_steps = [next_steps]
    if isinstance(evidence, str):
        evidence = [evidence]

    return {
        "summary": payload.get("summary") or payload.get("answer") or "",
        "next_steps": next_steps,
        "root_cause": payload.get("root_cause") or payload.get("cause") or "",
        "severity": payload.get("severity") or "",
        "evidence": evidence,
        "confidence": payload.get("confidence") or "",
    }


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        return {}

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(raw_text[index:])
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def strip_ansi(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)


def _coerce_subprocess_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def run_provider_command(command: Union[Sequence[str], str], input_text: Optional[str], timeout_seconds: int) -> Tuple[int, str, str, bool]:
    start_time = time.monotonic()
    cmd_display = " ".join(command) if isinstance(command, (list, tuple)) else str(command)
    prompt_length = len(input_text) if input_text is not None else 0
    prompt_preview = (input_text or cmd_display)[:800]
    _write_provider_trace(
        "prompt_ready",
        cmd_display,
        timeout_seconds=timeout_seconds,
        prompt_length=prompt_length,
        prompt_preview=prompt_preview,
    )
    logging.info(
        "provider prompt ready command=%s timeout_seconds=%s prompt_length=%s prompt_preview=%s",
        cmd_display,
        timeout_seconds,
        prompt_length,
        prompt_preview[:200].replace("\n", " "),
    )
    _write_provider_trace("process_start", cmd_display, timeout_seconds=timeout_seconds)
    popen_cmd = list(command) if isinstance(command, (list, tuple)) else [str(command)]
    process = subprocess.Popen(
        popen_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _write_provider_trace("communicate_start", cmd_display, pid=process.pid)
    try:
        if input_text is not None:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout_seconds)
        else:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        elapsed_seconds = time.monotonic() - start_time
        _write_provider_trace(
            "communicate_finish",
            cmd_display,
            pid=process.pid,
            returncode=process.returncode or 0,
            elapsed_seconds=elapsed_seconds,
            stdout_length=len(stdout or ""),
            stderr_length=len(stderr or ""),
            stdout_preview=(stdout or "")[:800],
            stderr_preview=(stderr or "")[:800],
        )
        logging.info(
            "provider command finished command=%s returncode=%s timed_out=%s elapsed_seconds=%.3f stdout_len=%s stderr_len=%s stdout_preview=%s stderr_preview=%s",
            cmd_display,
            process.returncode or 0,
            False,
            elapsed_seconds,
            len(stdout or ""),
            len(stderr or ""),
            (stdout or "")[:200].replace("\n", " "),
            (stderr or "")[:200].replace("\n", " "),
        )
        return process.returncode or 0, stdout or "", stderr or "", False
    except subprocess.TimeoutExpired as exc:
        partial_stdout = _coerce_subprocess_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        partial_stderr = _coerce_subprocess_text(getattr(exc, "stderr", None))
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", ""
        stdout = partial_stdout + _coerce_subprocess_text(stdout)
        stderr = partial_stderr + _coerce_subprocess_text(stderr)
        returncode = process.returncode if process.returncode is not None else -signal.SIGTERM
        elapsed_seconds = time.monotonic() - start_time
        _write_provider_trace(
            "timeout_kill",
            cmd_display,
            pid=process.pid,
            returncode=returncode,
            elapsed_seconds=elapsed_seconds,
            stdout_length=len(stdout or ""),
            stderr_length=len(stderr or ""),
            stdout_preview=(stdout or "")[:800],
            stderr_preview=(stderr or "")[:800],
        )
        logging.warning(
            "provider command timed out command=%s returncode=%s timed_out=%s elapsed_seconds=%.3f stdout_len=%s stderr_len=%s stdout_preview=%s stderr_preview=%s",
            cmd_display,
            returncode,
            True,
            elapsed_seconds,
            len(stdout or ""),
            len(stderr or ""),
            (stdout or "")[:200].replace("\n", " "),
            (stderr or "")[:200].replace("\n", " "),
        )
        return returncode, stdout or "", stderr or "", True
