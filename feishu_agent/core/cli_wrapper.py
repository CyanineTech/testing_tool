import json
import errno
import os
import pty
import re
import select
import signal
import subprocess
import time
import fcntl
import struct
import termios
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from feishu_agent.providers.base import extract_json_object, strip_ansi


def _trace_pty_chunk(command: Sequence[str], chunk: str, *, source: str, transcript_length: int) -> None:
    if not chunk:
        return
    from feishu_agent.providers.base import _write_provider_trace

    _write_provider_trace(
        "pty_chunk",
        " ".join(command),
        source=source,
        transcript_length=transcript_length,
        chunk_length=len(chunk),
        chunk_preview=chunk[:800],
    )


def _trace_pty_event(command: Sequence[str], stage: str, **fields: Any) -> None:
    from feishu_agent.providers.base import _write_provider_trace

    _write_provider_trace(stage, " ".join(command), **fields)


@dataclass(frozen=True)
class CliAction:
    kind: str
    body: str
    raw_block: str


@dataclass(frozen=True)
class CliObservation:
    command: str
    returncode: int
    stdout: str
    stderr: str
    source: str = "sandbox"


@dataclass
class CliSessionResult:
    raw_output: str
    report_payload: Dict[str, Any] = field(default_factory=dict)
    actions: List[CliAction] = field(default_factory=list)
    observations: List[CliObservation] = field(default_factory=list)
    timed_out: bool = False
    stop_reason: str = ""


class PtyCliWrapper:
    _REPORT_LIST_NOISE_VALUES = {
        "summary",
        "root_cause",
        "severity",
        "next_steps",
        "evidence",
        "confidence",
        "command",
        "returncode",
        "stdout",
        "stderr",
        "source",
    }
    _VALID_SEVERITY_VALUES = {
        "info",
        "warning",
        "error",
        "critical",
        "unknown",
        "low",
        "medium",
        "high",
        "信息",
        "提示",
        "警告",
        "错误",
        "严重",
        "待确认",
    }

    def __init__(self) -> None:
        self._knowledge_prefixes = ("```read_knowledge", "<read_knowledge>")
        self._execute_prefixes = ("```execute", "<execute>")
        self._report_prefixes = ("```report", "<report>")
        self._ready_markers = (
            "/ commands",
            "? help",
            "GPT-5.4",
            "Loading: 1 skill",
        )
        self._fatal_markers = (
            "Unknown tool name in the tool excludedlist",
            "Do you want to run this command?",
            "What would you like me to do in this repository?",
            "Asking user What would you like me to do in this repository?",
            "Type your answer...",
        )
        self._terminal_setup_prompt_markers = (
            "Set up terminal for multi-line input support",
            "Would you like to add this key binding to your terminal configuration?",
        )
        self._terminal_setup_resolution_markers = (
            "Added key binding for shift+enter for VS Code successfully.",
            "No changes made to terminal configuration",
            "Continuing without adding key binding",
        )
        self._quota_markers = (
            "You have exceeded your monthly quota",
            "AI Credits: 0",
        )
        self._protocol_correction_enabled = os.getenv("COPILOTCLI_PTY_PROTOCOL_CORRECTION", "0") == "1"
        self._stall_markers = ("Working esc cancel",)
        self._stall_timeout_seconds = float(os.getenv("COPILOTCLI_PTY_STALL_SECONDS", "12"))
        self._protocol_correction_delay_seconds = float(os.getenv("COPILOTCLI_PTY_PROTOCOL_CORRECTION_DELAY", "2.5"))
        self._naked_knowledge_pattern = re.compile(r"(?:^|\n|●\s+)(knowledge/[A-Za-z0-9_./-]+\.md)(?=\s|`|$)")
        self._naked_execute_pattern = re.compile(
            r"(?:^|\n|●\s+)(check_[A-Za-z0-9_/-]+(?:\s+[A-Za-z0-9_.:-]+)*)"
        )
        self._naked_execute_command_patterns = (
            (re.compile(r"rosnode\s+list", re.IGNORECASE), "rosnode list"),
            (
                re.compile(r"rostopic\s+echo\s+-n\s+1\s+/low_level_error", re.IGNORECASE),
                "rostopic echo /low_level_error -n1",
            ),
            (
                re.compile(r"rostopic\s+echo\s+/low_level_error\s+-n1", re.IGNORECASE),
                "rostopic echo /low_level_error -n1",
            ),
        )

    def run(
        self,
        command: Sequence[str],
        initial_prompt: str,
        action_handler: Callable[[CliAction], CliObservation],
        timeout_seconds: int,
    ) -> CliSessionResult:
        master_fd, slave_fd = pty.openpty()
        child_env = dict(os.environ)
        child_env["TERM"] = "dumb"
        child_env["CI"] = "1"
        process = subprocess.Popen(
            list(command),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=child_env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)

        transcript = ""
        result = CliSessionResult(raw_output="")
        handled_blocks: Set[str] = set()
        deadline = time.monotonic() + timeout_seconds
        prompt_sent = False
        prompt_retried = False
        prompt_sent_at = 0.0
        last_transcript_length = 0
        ready_seen = False
        prompt_acknowledged = False
        corrective_prompt_sent = False
        last_approval_offset = -1
        last_terminal_setup_offset = -1
        stalled_since: Optional[float] = None
        ready_offset_before_prompt = -1

        try:
            self._set_pty_size(master_fd)
            if initial_prompt:
                warmup_deadline = time.monotonic() + 1.0
                while time.monotonic() < warmup_deadline:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready:
                        continue
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    cleaned_chunk = strip_ansi(chunk.decode("utf-8", errors="ignore"))
                    transcript += cleaned_chunk
                    _trace_pty_chunk(command, cleaned_chunk, source="warmup", transcript_length=len(transcript))
                    ready_seen = self._is_ready_for_prompt(transcript)
                    break
                last_transcript_length = len(transcript)
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        if process.poll() is not None:
                            break
                        continue
                    cleaned_chunk = strip_ansi(chunk.decode("utf-8", errors="ignore"))
                    transcript += cleaned_chunk
                    _trace_pty_chunk(command, cleaned_chunk, source="stdout", transcript_length=len(transcript))
                    ready_seen = ready_seen or self._is_ready_for_prompt(transcript)
                    prompt_acknowledged = prompt_acknowledged or self._is_prompt_acknowledged(transcript, initial_prompt)

                    if self._has_quota_marker(transcript):
                        _trace_pty_event(
                            command,
                            "pty_quota_exhausted",
                            transcript_preview=transcript[-1200:],
                        )
                        result.stop_reason = "quota_exhausted"
                        break

                    if self._is_stall_chunk(cleaned_chunk) and prompt_sent and prompt_acknowledged and not result.actions and not result.report_payload:
                        stalled_since = stalled_since or time.monotonic()
                    elif cleaned_chunk.strip() and not self._is_stall_chunk(cleaned_chunk):
                        stalled_since = None

                    terminal_setup_offset = self._find_latest_terminal_setup_prompt(transcript)
                    if terminal_setup_offset > last_terminal_setup_offset and self._has_pending_terminal_setup_prompt(transcript):
                        self._dismiss_terminal_setup_prompt(master_fd, command)
                        last_terminal_setup_offset = terminal_setup_offset
                        last_transcript_length = len(transcript)
                        continue

                    if self._has_fatal_protocol_marker(transcript):
                        _trace_pty_event(
                            command,
                            "pty_protocol_abort",
                            transcript_preview=transcript[-1200:],
                        )
                        raise RuntimeError("pty interactive session entered unsupported tool/protocol flow")
                    last_transcript_length = len(transcript)

                    if initial_prompt and ready_seen and not prompt_sent:
                        ready_offset_before_prompt = self._find_latest_ready_offset(transcript)
                        self._send_prompt(master_fd, command, initial_prompt, reason="initial")
                        prompt_sent = True
                        prompt_sent_at = time.monotonic()

                    approval_offset = self._find_latest_approval_prompt(transcript)
                    while approval_offset > last_approval_offset:
                        self._send_confirmation(master_fd, command, "1", reason="approve_execute")
                        last_approval_offset = approval_offset
                        approval_offset = self._find_latest_approval_prompt(transcript)

                    while True:
                        action = self._find_next_action(transcript, handled_blocks)
                        if action is None:
                            break
                        handled_blocks.add(action.raw_block)
                        result.actions.append(action)
                        observation = action_handler(action)
                        result.observations.append(observation)
                        response = self._format_observation(observation)
                        self._send_observation(master_fd, command, response, source=observation.source)

                    report = self._find_next_block(transcript, handled_blocks, kind="report")
                    if report is not None:
                        handled_blocks.add(report.raw_block)
                        payload = self._parse_report_payload(report.body)
                        if payload:
                            result.report_payload = payload
                            break

                    if (
                        prompt_sent
                        and prompt_acknowledged
                        and self._find_latest_ready_offset(transcript) > ready_offset_before_prompt
                    ):
                        payload = self._find_naked_report_payload(transcript)
                        if payload:
                            result.report_payload = payload
                            break

                    if (
                        stalled_since is not None
                        and self._should_send_protocol_correction(
                            stalled_since=stalled_since,
                            prompt_sent=prompt_sent,
                            prompt_acknowledged=prompt_acknowledged,
                            corrective_prompt_sent=corrective_prompt_sent,
                            action_count=len(result.actions),
                            has_report=bool(result.report_payload),
                        )
                    ):
                        self._send_prompt(
                            master_fd,
                            command,
                            self._build_protocol_correction_prompt(),
                            reason="stall_protocol_correction",
                        )
                        corrective_prompt_sent = True
                        stalled_since = None
                        prompt_sent_at = time.monotonic()
                        continue

                    if (
                        stalled_since is not None
                        and time.monotonic() - stalled_since >= self._stall_timeout_seconds
                    ):
                        _trace_pty_event(
                            command,
                            "pty_stalled_no_blocks",
                            stalled_seconds=time.monotonic() - stalled_since,
                            transcript_preview=transcript[-1200:],
                        )
                        result.timed_out = True
                        result.stop_reason = "stalled_no_blocks"
                        break

                    if (
                        self._protocol_correction_enabled
                        and
                        initial_prompt
                        and prompt_sent
                        and prompt_acknowledged
                        and not corrective_prompt_sent
                        and not result.actions
                        and not result.report_payload
                        and self._find_latest_ready_offset(transcript) > ready_offset_before_prompt
                    ):
                        self._send_prompt(
                            master_fd,
                            command,
                            self._build_protocol_correction_prompt(),
                            reason="protocol_correction",
                        )
                        corrective_prompt_sent = True
                        prompt_sent_at = time.monotonic()
                elif (
                    initial_prompt
                    and prompt_sent
                    and not prompt_retried
                    and not prompt_acknowledged
                    and len(transcript) == last_transcript_length
                    and time.monotonic() - prompt_sent_at >= 2.0
                    and process.poll() is None
                ):
                    self._send_prompt(master_fd, command, initial_prompt, reason="retry")
                    prompt_retried = True
                    prompt_sent_at = time.monotonic()
                elif initial_prompt and not prompt_sent and not ready_seen and time.monotonic() + 3.0 >= deadline:
                    self._send_prompt(master_fd, command, initial_prompt, reason="deadline_fallback")
                    prompt_sent = True
                    prompt_sent_at = time.monotonic()

                if process.poll() is not None and not ready:
                    break

            if not result.report_payload and time.monotonic() >= deadline:
                result.timed_out = True
                result.stop_reason = result.stop_reason or "deadline_timeout"
        finally:
            if not result.report_payload and transcript:
                report = self._find_next_block(transcript, handled_blocks, kind="report")
                if report is not None:
                    result.report_payload = self._parse_report_payload(report.body)
                elif "{" in transcript:
                    result.report_payload = self._parse_report_payload(transcript)
            result.raw_output = transcript
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass
            try:
                os.close(master_fd)
            except Exception:
                pass

        return result

    def _set_pty_size(self, master_fd: int, rows: int = 40, cols: int = 120) -> None:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    def _send_prompt(self, master_fd: int, command: Sequence[str], prompt: str, *, reason: str) -> None:
        self._send_message(master_fd, command, prompt, reason=reason)

    def _send_message(self, master_fd: int, command: Sequence[str], message: str, *, reason: str) -> None:
        prompt_body = message.rstrip("\r\n")
        payload = prompt_body.encode("utf-8", errors="ignore")
        os.write(master_fd, payload)
        time.sleep(0.05)
        submit = b"\r"
        os.write(master_fd, submit)
        _trace_pty_event(
            command,
            "pty_prompt_send",
            reason=reason,
            payload_length=len(payload) + len(submit),
            payload_preview=message[:800],
        )

    def _send_observation(self, master_fd: int, command: Sequence[str], message: str, *, source: str) -> None:
        observation_body = message.rstrip("\r\n")
        payload = observation_body.encode("utf-8", errors="ignore")
        os.write(master_fd, payload)
        time.sleep(0.05)
        enqueue = b"\x11"
        os.write(master_fd, enqueue)
        time.sleep(0.05)
        submit = b"\r"
        os.write(master_fd, submit)
        _trace_pty_event(
            command,
            "pty_prompt_send",
            reason=f"observation_{source}",
            payload_length=len(payload) + len(enqueue) + len(submit),
            payload_preview=message[:800],
        )

    def _is_ready_for_prompt(self, transcript: str) -> bool:
        compact = transcript[-4000:]
        return any(marker in compact for marker in self._ready_markers) and not self._has_pending_terminal_setup_prompt(compact)

    def _find_latest_ready_offset(self, transcript: str) -> int:
        compact = transcript[-12000:]
        offsets = [compact.rfind(marker) for marker in self._ready_markers]
        latest = max(offsets)
        if latest < 0:
            return -1
        return len(transcript) - len(compact) + latest

    def _is_prompt_acknowledged(self, transcript: str, prompt: str = "") -> bool:
        compact = transcript[-4000:]
        if "[Paste #" in compact or "Working esc cancel" in compact:
            return True
        prompt_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
        if prompt_lines:
            first_line = prompt_lines[0][:24]
            if first_line and first_line in compact:
                return True
        return False

    def _find_latest_approval_prompt(self, transcript: str) -> int:
        compact = transcript[-12000:]
        if "1. Yes" not in compact or "3. No, and tell Copilot what to do differently" not in compact:
            return -1
        prompt_markers = (
            "Do you want to run this command?",
            "↑/↓ to navigate · enter to select · esc to cancel",
        )
        return max(compact.rfind(marker) for marker in prompt_markers)

    def _send_confirmation(self, master_fd: int, command: Sequence[str], choice: str, *, reason: str) -> None:
        payload = f"{choice}\r".encode("utf-8", errors="ignore")
        os.write(master_fd, payload)
        _trace_pty_event(
            command,
            "pty_confirmation_send",
            reason=reason,
            payload_preview=choice,
        )

    def _dismiss_terminal_setup_prompt(self, master_fd: int, command: Sequence[str]) -> None:
        payload = b"n\r"
        os.write(master_fd, payload)
        _trace_pty_event(
            command,
            "pty_terminal_setup_dismiss",
            payload_preview="n",
        )

    def _build_protocol_correction_prompt(self) -> str:
        return (
            "协议违规：你刚才输出了普通文本或裸命令，但没有使用受控协议块。\n"
            "不要调用 shell，不要输出 bash 命令，不要输出工具说明。\n"
            "如果需要补知识，请只输出一个 read_knowledge 命名代码块；如果需要执行，请只输出一个 execute 命名代码块；如果已有证据足够，请直接输出一个 report 命名代码块。\n"
            "现在仅按协议继续。"
        )

    def _should_send_protocol_correction(
        self,
        *,
        stalled_since: float,
        prompt_sent: bool,
        prompt_acknowledged: bool,
        corrective_prompt_sent: bool,
        action_count: int,
        has_report: bool,
    ) -> bool:
        if not self._protocol_correction_enabled:
            return False
        if not prompt_sent or not prompt_acknowledged:
            return False
        if corrective_prompt_sent or action_count or has_report:
            return False
        return time.monotonic() - stalled_since >= self._protocol_correction_delay_seconds

    def _has_fatal_protocol_marker(self, transcript: str) -> bool:
        compact = transcript[-12000:]
        return any(marker in compact for marker in self._fatal_markers)

    def _has_quota_marker(self, transcript: str) -> bool:
        compact = transcript[-12000:]
        return any(marker in compact for marker in self._quota_markers)

    def _is_stall_chunk(self, chunk: str) -> bool:
        return any(marker in chunk for marker in self._stall_markers)

    def _find_latest_terminal_setup_prompt(self, transcript: str) -> int:
        compact = transcript[-12000:]
        offsets = [compact.rfind(marker) for marker in self._terminal_setup_prompt_markers]
        latest = max(offsets)
        if latest < 0:
            return -1
        return len(transcript) - len(compact) + latest

    def _has_pending_terminal_setup_prompt(self, transcript: str) -> bool:
        prompt_offset = self._find_latest_terminal_setup_prompt(transcript)
        if prompt_offset < 0:
            return False
        tail = transcript[prompt_offset:]
        return not any(marker in tail for marker in self._terminal_setup_resolution_markers)

    def _find_next_block(self, transcript: str, handled_blocks: Set[str], kind: str) -> Optional[CliAction]:
        candidates = self._extract_fenced_blocks(transcript, kind) + self._extract_tag_blocks(transcript, kind)
        for _, raw_block, body in sorted(candidates, key=lambda item: item[0]):
            if raw_block in handled_blocks:
                continue
            cleaned_body = body.strip()
            if cleaned_body:
                return CliAction(kind=kind, body=cleaned_body, raw_block=raw_block)
        return None

    def _find_next_action(self, transcript: str, handled_blocks: Set[str]) -> Optional[CliAction]:
        next_actions = [
            action
            for action in (
                self._find_next_block(transcript, handled_blocks, kind="read_knowledge"),
                self._find_next_block(transcript, handled_blocks, kind="execute"),
                self._find_next_naked_knowledge_action(transcript, handled_blocks),
                self._find_next_naked_execute_action(transcript, handled_blocks),
            )
            if action is not None
        ]
        if not next_actions:
            return None

        def _position(action: CliAction) -> int:
            return transcript.find(action.raw_block)

        return min(next_actions, key=_position)

    def _find_next_naked_knowledge_action(self, transcript: str, handled_blocks: Set[str]) -> Optional[CliAction]:
        compact = transcript[-12000:]
        for match in self._naked_knowledge_pattern.finditer(compact):
            path = match.group(1).strip()
            if not path or path in handled_blocks:
                continue
            trailing = compact[match.end(1):match.end(1) + 2]
            if trailing.startswith("。"):
                continue
            raw_block = path
            return CliAction(kind="read_knowledge", body=path, raw_block=raw_block)
        return None

    def _find_next_naked_execute_action(self, transcript: str, handled_blocks: Set[str]) -> Optional[CliAction]:
        compact = transcript[-12000:]
        for match in self._naked_execute_pattern.finditer(compact):
            raw_block = match.group(1).strip()
            if not raw_block or raw_block in handled_blocks:
                continue
            command = self._normalize_naked_execute(raw_block)
            if not command:
                continue
            return CliAction(kind="execute", body=command, raw_block=raw_block)

        next_match: Optional[Tuple[int, str, str]] = None
        for pattern, command in self._naked_execute_command_patterns:
            for match in pattern.finditer(compact):
                raw_block = match.group(0).strip()
                if not raw_block or raw_block in handled_blocks:
                    continue
                if next_match is None or match.start() < next_match[0]:
                    next_match = (match.start(), raw_block, command)
                break

        if next_match is None:
            return None

        _, raw_block, command = next_match
        return CliAction(kind="execute", body=command, raw_block=raw_block)
        

    def _normalize_naked_execute(self, raw_block: str) -> str:
        compact = raw_block.strip().lower()
        if compact.startswith("check_low_level_error_and_rosnode") or compact.startswith("check_low_level_error"):
            return "rostopic echo /low_level_error -n1"
        if compact.startswith("check_rosnode"):
            return "rosnode list"
        return ""

    def _extract_fenced_blocks(self, transcript: str, kind: str) -> List[Tuple[int, str, str]]:
        marker = f"```{kind}"
        blocks: List[Tuple[int, str, str]] = []
        start = 0
        while True:
            block_start = transcript.find(marker, start)
            if block_start < 0:
                break
            body_start = block_start + len(marker)
            block_end = transcript.find("```", body_start)
            if block_end < 0:
                break
            raw_block = transcript[block_start:block_end + 3]
            body = transcript[body_start:block_end]
            blocks.append((block_start, raw_block, body))
            start = block_end + 3
        return blocks

    def _extract_tag_blocks(self, transcript: str, kind: str) -> List[Tuple[int, str, str]]:
        open_tag = f"<{kind}>"
        close_tag = f"</{kind}>"
        blocks: List[Tuple[int, str, str]] = []
        start = 0
        while True:
            block_start = transcript.find(open_tag, start)
            if block_start < 0:
                break
            body_start = block_start + len(open_tag)
            block_end = transcript.find(close_tag, body_start)
            if block_end < 0:
                break
            raw_block = transcript[block_start:block_end + len(close_tag)]
            body = transcript[body_start:block_end]
            blocks.append((block_start, raw_block, body))
            start = block_end + len(close_tag)
        return blocks

    def _parse_report_payload(self, body: str) -> Dict[str, Any]:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict) and self._looks_like_report_payload(payload):
                return self._normalize_report_payload(payload, body)
        except Exception:
            pass
        payload = self._extract_latest_json_object(body)
        if isinstance(payload, dict) and self._looks_like_report_payload(payload):
            return self._normalize_report_payload(payload, body)
        payload = extract_json_object(body)
        if isinstance(payload, dict) and self._looks_like_report_payload(payload):
            return self._normalize_report_payload(payload, body)
        payload = self._salvage_report_payload(body)
        if payload:
            return self._normalize_report_payload(payload, body)
        return {}

    def _find_naked_report_payload(self, transcript: str) -> Dict[str, Any]:
        focus_text = self._extract_report_focus_region(transcript)
        payload = self._parse_report_payload(focus_text)
        if self._looks_like_report_payload(payload, require_complete=True):
            return payload
        return {}

    def _normalize_report_payload(self, payload: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        normalized = dict(payload)
        salvaged = self._salvage_report_payload(raw_text)

        for key in ("summary", "root_cause", "severity", "confidence"):
            current = self._normalize_report_scalar(key, normalized.get(key) or "")
            candidate = self._normalize_report_scalar(key, salvaged.get(key) or "")
            normalized[key] = max((current, candidate), key=self._score_report_scalar).strip()

        for key in ("next_steps", "evidence"):
            current_list = normalized.get(key) if isinstance(normalized.get(key), list) else []
            candidate_list = salvaged.get(key) if isinstance(salvaged.get(key), list) else []
            normalized[key] = max((current_list, candidate_list), key=self._score_report_list)

        return {key: value for key, value in normalized.items() if value not in ("", [], None)}

    def _normalize_report_scalar(self, key: str, value: Any) -> str:
        cleaned = self._clean_report_text(str(value or ""))
        if not cleaned:
            return ""
        if key == "severity":
            normalized = cleaned.strip()
            lowered = normalized.lower()
            if lowered in self._VALID_SEVERITY_VALUES or normalized in self._VALID_SEVERITY_VALUES:
                return normalized
            if re.fullmatch(r"[A-Za-z]", normalized):
                return ""
            return normalized if len(normalized) >= 2 else ""
        if key == "confidence":
            lowered = cleaned.lower()
            if lowered in {"low", "medium", "high", "unknown"}:
                return lowered
            if re.fullmatch(r"0(?:\.\d+)?|1(?:\.0+)?", cleaned):
                return cleaned
            return "" if re.fullmatch(r"[A-Za-z]", cleaned) else cleaned
        if key in {"summary", "root_cause"} and len(cleaned) <= 2:
            return ""
        return cleaned

    def _score_report_scalar(self, value: str) -> Tuple[int, int]:
        cleaned = value.strip()
        if not cleaned:
            return (0, 0)
        return (1, len(cleaned))

    def _score_report_list(self, items: List[str]) -> Tuple[int, int]:
        cleaned_items = [str(item).strip() for item in items if str(item).strip()]
        return (len(cleaned_items), sum(len(item) for item in cleaned_items))

    def _clean_report_text(self, text: str) -> str:
        cleaned = text or ""
        cleaned = re.sub(r"[●◉◎○]\s+Working esc cancel.*$", "", cleaned).strip()
        cleaned = re.sub(r"GPT-5\.4 mini(?:\s·\smedium)?", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _looks_like_report_payload(self, payload: Dict[str, Any], *, require_complete: bool = False) -> bool:
        if not isinstance(payload, dict):
            return False
        has_summary = bool(payload.get("summary") or payload.get("answer"))
        root_cause = str(payload.get("root_cause") or "").strip()
        has_root_cause = len(root_cause) >= 4
        has_next_steps = bool(payload.get("next_steps"))
        has_confidence = bool(payload.get("confidence"))
        if require_complete:
            return has_summary and (has_root_cause or has_next_steps or has_confidence)
        return has_summary or has_root_cause

    def _salvage_report_payload(self, raw_text: str) -> Dict[str, Any]:
        if not raw_text:
            return {}

        focus_text = self._extract_report_focus_region(raw_text)

        payload: Dict[str, Any] = {}
        for key in ("summary", "root_cause", "severity", "confidence"):
            value = self._extract_best_string_field(focus_text, key)
            if value:
                payload[key] = value

        next_steps = self._extract_last_list_field(focus_text, "next_steps")
        if next_steps:
            payload["next_steps"] = next_steps

        evidence = self._extract_last_list_field(focus_text, "evidence")
        if evidence:
            payload["evidence"] = evidence

        if self._looks_like_report_payload(payload, require_complete=True):
            return payload
        return {}

    def _extract_best_string_field(self, raw_text: str, key: str) -> str:
        candidates: List[str] = []
        complete_pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"')
        partial_pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"([^\r\n"]*)')

        for pattern, decode_json in ((complete_pattern, True), (partial_pattern, False)):
            for match in pattern.finditer(raw_text):
                try:
                    value = json.loads(f'"{match.group(1)}"') if decode_json else match.group(1)
                except Exception:
                    value = match.group(1)
                value = self._normalize_report_scalar(key, value)
                if not value or value == key:
                    continue
                candidates.append(value)
        return max(candidates, key=self._score_report_scalar) if candidates else ""

    def _extract_last_list_field(self, raw_text: str, key: str) -> List[str]:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', re.DOTALL)
        candidates: List[List[str]] = []
        for match in pattern.finditer(raw_text):
            items: List[str] = []
            for item_match in re.finditer(r'"((?:\\.|[^"\\])*)"', match.group(1)):
                try:
                    item = json.loads(f'"{item_match.group(1)}"')
                except Exception:
                    item = item_match.group(1)
                item = self._normalize_report_list_item(key, item)
                if item:
                    items.append(item)
            if items:
                candidates.append(items)
        return max(candidates, key=self._score_report_list) if candidates else []

    def _normalize_report_list_item(self, key: str, value: Any) -> str:
        cleaned = self._clean_report_text(str(value or ""))
        if not cleaned:
            return ""
        lowered = cleaned.lower()
        if lowered in self._REPORT_LIST_NOISE_VALUES:
            return ""
        if any(marker in cleaned for marker in ("Working esc cancel", "GPT-5.4", "```result", "如果还需要更多证据", "已读取知识摘要")):
            return ""
        if re.fullmatch(r"[:{},\[\]-]+", cleaned):
            return ""
        min_length = 4 if key == "next_steps" else 3
        if len(cleaned) < min_length:
            return ""
        return cleaned

    def _extract_report_focus_region(self, raw_text: str) -> str:
        anchors = [
            raw_text.rfind(token)
            for token in ('"summary"', '"root_cause"', '"next_steps"', '"evidence"')
        ]
        anchor = max(anchors)
        if anchor < 0:
            return raw_text[-4000:]
        start = raw_text.rfind("{", max(0, anchor - 4000), anchor + 1)
        if start < 0:
            start = max(0, anchor - 400)
        return raw_text[start:]

    def _extract_latest_json_object(self, raw_text: str) -> Dict[str, Any]:
        if not raw_text:
            return {}

        decoder = json.JSONDecoder()
        latest_payload: Dict[str, Any] = {}
        for index, char in enumerate(raw_text):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(raw_text[index:])
            except Exception:
                continue
            if isinstance(payload, dict):
                latest_payload = payload
        return latest_payload

    def _format_observation(self, observation: CliObservation) -> str:
        if observation.source == "knowledge":
            excerpt = (observation.stdout or observation.stderr or "").strip()
            excerpt_lines = [line.strip() for line in excerpt.splitlines() if line.strip()][:4]
            compact_excerpt = " | ".join(excerpt_lines)
            return (
                "\n已读取知识摘要。"
                f"文档: {observation.command}。"
                f"摘要: {compact_excerpt}。"
                "以上是知识，不是命令。"
                "除非你明确需要第二份 knowledge，否则下一条只允许输出一个 report 代码块；"
                "正文必须是 JSON，并包含 summary、root_cause、severity、next_steps、evidence、confidence。\n"
            )

        payload = {
            "command": observation.command,
            "returncode": observation.returncode,
            "stdout": observation.stdout,
            "stderr": observation.stderr,
            "source": observation.source,
        }
        return (
            "\n执行结果：\n"
            "```result\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "```\n"
            "如果还需要更多证据，请继续输出 read_knowledge 或 execute 代码块；如果已经可以下结论，请输出 report 代码块。\n"
        )
