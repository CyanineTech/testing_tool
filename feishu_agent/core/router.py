import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from feishu_agent.app import classify_text
from feishu_agent.diagnostics import extract_target, extract_time_key


FOLLOW_UP_RE = re.compile(
    r"^(?:下一步|继续|再往下|然后呢|怎么查|接着查|处理|排查|查什么|再看)(?:.*)?$"
)

THREAD_MESSAGE_ANCHORS: Dict[str, str] = {}
THREAD_MESSAGE_ANCHOR_LAST_ACTIVE: Dict[str, float] = {}


@dataclass(frozen=True)
class CaseContext:
    route: str
    target: str
    time_key: str
    conversation_key: str
    is_follow_up: bool = False
    missing_fields: List[str] = field(default_factory=list)


def _resolve_thread_anchor(message: Dict[str, object]) -> str:
    logging.info(
        "thread anchor scan chat_id=%s root_id=%s thread_id=%s parent_id=%s message_id=%s",
        str(message.get("chat_id") or ""),
        str(message.get("root_id") or ""),
        str(message.get("thread_id") or ""),
        str(message.get("parent_id") or ""),
        str(message.get("message_id") or ""),
    )
    for key in ("root_id", "thread_id", "parent_id", "message_id"):
        anchor_id = str(message.get(key) or "")
        if anchor_id and anchor_id in THREAD_MESSAGE_ANCHORS:
            logging.info(
                "thread anchor hit anchor_key=%s anchor_id=%s conversation_key=%s",
                key,
                anchor_id,
                THREAD_MESSAGE_ANCHORS[anchor_id],
            )
            return THREAD_MESSAGE_ANCHORS[anchor_id]
    return ""


def get_conversation_key(payload: Dict[str, object], sender_open_id: str = "") -> str:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    chat_id = str(message.get("chat_id") or "")
    root_id = str(message.get("root_id") or message.get("message_id") or "")
    anchor_conversation_key = _resolve_thread_anchor(message)
    if anchor_conversation_key:
        return anchor_conversation_key
    conversation_key = f"{chat_id}:{root_id or 'root'}"
    logging.info(
        "thread anchor miss fallback chat_id=%s root_id=%s sender=%s conversation_key=%s",
        chat_id,
        root_id,
        sender_open_id,
        conversation_key,
    )
    return conversation_key


def register_thread_message_anchor(message_id: str, conversation_key: str, root_id: str = "", parent_id: str = "", thread_id: str = "") -> None:
    if not conversation_key:
        return

    now_value = time.monotonic()
    for anchor_id in (message_id, root_id, parent_id, thread_id):
        if anchor_id:
            THREAD_MESSAGE_ANCHORS[anchor_id] = conversation_key
            THREAD_MESSAGE_ANCHOR_LAST_ACTIVE[anchor_id] = now_value
            logging.info(
                "thread anchor registered anchor_id=%s conversation_key=%s root_id=%s parent_id=%s thread_id=%s",
                anchor_id,
                conversation_key,
                root_id,
                parent_id,
                thread_id,
            )


def cleanup_thread_message_anchors(ttl_seconds: int, now: Optional[float] = None) -> None:
    if ttl_seconds <= 0:
        return

    current_time = now if now is not None else time.monotonic()
    expired_keys = [
        message_id
        for message_id, timestamp in THREAD_MESSAGE_ANCHOR_LAST_ACTIVE.items()
        if current_time - timestamp > ttl_seconds
    ]
    for message_id in expired_keys:
        THREAD_MESSAGE_ANCHORS.pop(message_id, None)
        THREAD_MESSAGE_ANCHOR_LAST_ACTIVE.pop(message_id, None)
    if expired_keys:
        logging.info("thread anchors pruned count=%s ttl_seconds=%s", len(expired_keys), ttl_seconds)


def extract_case_context(text: str, payload: Dict[str, object], sender_open_id: str = "") -> CaseContext:
    conversation_key = get_conversation_key(payload, sender_open_id)
    event = payload.get("event") or {}
    message = event.get("message") or {}
    previous_state = message.get("state") or {}
    previous_route = str(previous_state.get("route") or "")
    previous_target = str(previous_state.get("target") or "")

    explicit_target = extract_target(text)
    is_follow_up = bool(FOLLOW_UP_RE.fullmatch(text))
    if is_follow_up and previous_target and not explicit_target:
        target = previous_target
    elif is_follow_up and previous_target and explicit_target:
        if target_override_allowed(text, explicit_target, previous_target):
            target = explicit_target
        else:
            target = previous_target
    else:
        target = explicit_target or previous_target

    text_route = classify_text(text, target=target)
    if FOLLOW_UP_RE.fullmatch(text) and previous_route:
        route = previous_route
    elif text_route == "unknown" and previous_route:
        route = previous_route
        is_follow_up = True
    else:
        route = text_route
        is_follow_up = bool(FOLLOW_UP_RE.fullmatch(text))

    time_key = extract_time_key(text) or str(previous_state.get("time_key") or "")

    missing_fields: List[str] = []
    if route in {"amr", "network"} and not target:
        missing_fields.append("target")
    if route == "unknown":
        missing_fields.extend(["route", "target"])

    return CaseContext(
        route=route,
        target=target,
        time_key=time_key,
        conversation_key=conversation_key,
        is_follow_up=is_follow_up,
        missing_fields=missing_fields,
    )


def target_override_allowed(text: str, explicit_target: str, previous_target: str) -> bool:
    if not explicit_target or not previous_target:
        return False
    if explicit_target == previous_target:
        return True
    if extract_target(text) == explicit_target:
        return bool(re.search(r"(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+", explicit_target))
    return False


def needs_clarification(context: CaseContext) -> bool:
    return bool(context.missing_fields)
