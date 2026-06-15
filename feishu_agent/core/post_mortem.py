import re
from datetime import datetime
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Union

from feishu_agent.config import Settings, load_settings
from feishu_agent.protocols.schemas import DraftResult, OrchestratorRunResult, ReportResult, TraceEntry


SETTINGS: Optional[Settings] = None
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


def _default_drafts_dir(settings: Optional[Settings] = None) -> Path:
    resolved = _resolve_settings(settings)
    return resolved.repo_root / resolved.system.drafts_root_name


def _utc_timestamp_compact() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _normalize_conversation(conversation: Sequence[object]) -> List[str]:
    lines: List[str] = []
    for item in conversation:
        if isinstance(item, str):
            text = item.strip()
            if text:
                lines.append(text)
            continue
        if isinstance(item, Mapping):
            role = str(item.get("role") or "unknown").strip()
            content = str(item.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
            continue
        text = str(item).strip()
        if text:
            lines.append(text)
    return lines


def _trace_to_lines(trace: Sequence[object]) -> List[str]:
    lines: List[str] = []
    for item in trace:
        if isinstance(item, TraceEntry):
            details = item.details or {}
            if item.type == "knowledge_candidates":
                items = details.get("items") or []
                if isinstance(items, list) and items:
                    lines.append("候选文档：" + "、".join(str(doc) for doc in items if str(doc).strip()))
            elif item.type == "local_execution":
                command = str(details.get("command") or "").strip()
                returncode = details.get("returncode", "")
                if command:
                    lines.append(f"关键命令：`{command}` (rc={returncode})")
            elif item.type == "provider_action":
                action_type = str(item.action_type or "").strip()
                if action_type == "read_knowledge":
                    path = str(details.get("payload", {}).get("path") if isinstance(details.get("payload"), dict) else "").strip()
                    if path:
                        lines.append(f"读取文档：{path}")
                elif action_type == "secure_ssh_execute":
                    payload = details.get("payload") if isinstance(details.get("payload"), dict) else {}
                    command = str(payload.get("command") or "").strip()
                    if command:
                        lines.append(f"执行命令：`{command}`")
            continue

        if isinstance(item, Mapping):
            item_type = str(item.get("type") or "")
            if item_type == "knowledge_candidates":
                items = item.get("items") or []
                if isinstance(items, list) and items:
                    lines.append("候选文档：" + "、".join(str(doc) for doc in items if str(doc).strip()))
            elif item_type == "local_execution":
                command = str(item.get("command") or "").strip()
                returncode = item.get("returncode", "")
                if command:
                    lines.append(f"关键命令：`{command}` (rc={returncode})")
            elif item_type == "provider_action":
                action_type = str(item.get("action_type") or "").strip()
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                if action_type == "read_knowledge":
                    path = str(payload.get("path") or "").strip()
                    if path:
                        lines.append(f"读取文档：{path}")
                elif action_type == "secure_ssh_execute":
                    command = str(payload.get("command") or "").strip()
                    if command:
                        lines.append(f"执行命令：`{command}`")
    return lines


class PostMortem:
    def __init__(self, drafts_dir: Union[str, Path, None] = None, settings: Optional[Settings] = None) -> None:
        draft_root = Path(drafts_dir) if drafts_dir is not None else _default_drafts_dir(settings)
        self.drafts_dir = draft_root.expanduser().resolve()

    def build_draft_text(
        self,
        conversation: list,
        answer: str,
        sop_path: str,
        *,
        trace: Optional[Sequence[object]] = None,
        report_result: Optional[ReportResult] = None,
    ) -> str:
        conversation_lines = _normalize_conversation(conversation)
        trace_lines = _trace_to_lines(trace or [])
        answer_text = (answer or "").strip()
        sop_text = (sop_path or "").strip() or "knowledge/README.md"

        lines = [
            "# 排障草稿",
            "",
            f"- 生成时间：{_utc_timestamp_compact()}",
            f"- SOP 路径：{sop_text}",
            "",
            "## 会话摘要",
        ]
        if conversation_lines:
            lines.extend(f"- {line}" for line in conversation_lines)
        else:
            lines.append("- 无会话记录")

        if report_result:
            lines.extend(
                [
                    "",
                    "## 结构化结果",
                    f"- 摘要：{report_result.summary or '未提供'}",
                    f"- 根因：{report_result.root_cause or '未提供'}",
                    f"- 严重程度：{report_result.severity or '未提供'}",
                ]
            )
            if report_result.knowledge_used:
                lines.append("- 已读文档：" + "、".join(report_result.knowledge_used))
            if report_result.commands_used:
                lines.append("- 已用命令：" + "、".join(f"`{cmd}`" for cmd in report_result.commands_used))

        if trace_lines:
            lines.extend(
                [
                    "",
                    "## 关键命令",
                ]
            )
            lines.extend(f"- {line}" for line in trace_lines)
        else:
            lines.extend(
                [
                    "",
                    "## 关键命令",
                    "- 未记录关键命令",
                ]
            )

        lines.extend(
            [
                "",
                "## 最终结论",
                answer_text or "未生成最终结论",
                "",
                "## 备注",
                "- 草稿仅用于复盘与后续 AI 参考，不覆盖正式 SOP。",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def save_draft(self, text: str, filename: Optional[str] = None) -> str:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = filename or f"draft_{_utc_timestamp_compact()}.md"
        safe_filename = _SAFE_FILENAME_RE.sub("_", safe_filename).strip("._-") or f"draft_{_utc_timestamp_compact()}.md"
        if not safe_filename.endswith(".md"):
            safe_filename = f"{safe_filename}.md"
        draft_path = (self.drafts_dir / safe_filename).resolve()
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            draft_path.relative_to(self.drafts_dir)
        except ValueError:
            raise ValueError("draft path escapes drafts dir")
        draft_path.write_text(text, encoding="utf-8")
        return str(draft_path)

    def generate_draft(
        self,
        conversation: list,
        answer: str,
        sop_path: str,
        *,
        trace: Optional[Sequence[object]] = None,
        report_result: Optional[ReportResult] = None,
    ) -> DraftResult:
        text = self.build_draft_text(conversation, answer, sop_path, trace=trace, report_result=report_result)
        filename = f"{Path(sop_path or 'knowledge/README.md').stem}_{_utc_timestamp_compact()}.md"
        draft_path = self.save_draft(text, filename=filename)
        title = f"{Path(sop_path or 'knowledge/README.md').stem} 排障草稿"
        return DraftResult(
            draft_path=draft_path,
            title=title,
            source_sop=sop_path or "knowledge/README.md",
        )


def build_post_mortem_from_result(result: OrchestratorRunResult, settings: Optional[Settings] = None) -> DraftResult:
    post_mortem = PostMortem(settings=settings)
    conversation = list(result.messages or [])
    answer = result.final_answer or ""
    sop_path = result.sop_path or "knowledge/README.md"
    conversation.append(
        {
            "role": "system",
            "content": f"trace_count={len(result.trace)} report_summary={(result.report_result.summary if result.report_result else '')}",
        }
    )
    return post_mortem.generate_draft(
        conversation,
        answer,
        sop_path,
        trace=result.trace,
        report_result=result.report_result,
    )
