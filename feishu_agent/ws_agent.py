import asyncio
import copy
import json
import logging
import os
import re
import threading
import time
from typing import Dict, Optional, Tuple

import lark_oapi as lark
from lark_oapi.channel import fetch_bot_identity

from feishu_agent.app import classify_text, parse_message
from feishu_agent.core import router as conversation_router
from feishu_agent.core.orchestrator import CaseRequest, Orchestrator
from feishu_agent.diagnostics import extract_target, extract_time_key
from feishu_agent.observability.logger import setup_logging
from feishu_agent.troubleshoot import build_troubleshoot_plan, format_troubleshoot_plan


setup_logging()

api_client = lark.Client.builder()
api_client = None

sender_name_cache: Dict[str, str] = {}
conversation_state: Dict[str, Dict[str, object]] = {}
conversation_state_last_active: Dict[str, float] = {}
conversation_thread_aliases: Dict[str, str] = {}
conversation_thread_alias_last_active: Dict[str, float] = {}
processing_message_ids: set = set()
processed_message_ids: Dict[str, float] = {}
processing_event_ids: set = set()
processed_event_ids: Dict[str, float] = {}
_processing_state_lock = threading.RLock()

orchestrator = Orchestrator()


def configure_runtime(orchestrator_instance: Optional[Orchestrator] = None) -> Orchestrator:
    global orchestrator

    if orchestrator_instance is not None:
        orchestrator = orchestrator_instance
    return orchestrator

FEISHU_SESSION_TTL_SECONDS = int(os.getenv("FEISHU_SESSION_TTL_SECONDS", "21600"))
FEISHU_DEDUP_TTL_SECONDS = int(os.getenv("FEISHU_DEDUP_TTL_SECONDS", "86400"))
FEISHU_STATE_SWEEP_INTERVAL_SECONDS = int(os.getenv("FEISHU_STATE_SWEEP_INTERVAL_SECONDS", "300"))
FEISHU_DEDUP_MAX_ITEMS = int(os.getenv("FEISHU_DEDUP_MAX_ITEMS", "50000"))
_last_runtime_state_cleanup_at = 0.0


ID_LIKE_NAME_RE = re.compile(r"^(?:ou|on|oc|cli|u)_?[0-9a-zA-Z-]+$")
FOLLOW_UP_RE = re.compile(r"^(?:下一步|继续(?:下一步)?(?:检查|排查|看一下)?|再往下|然后呢|怎么查|接着查|处理|排查|查什么|再看)$")
MENTION_RE = re.compile(r"<at[^>]*>.*?</at>|@_user_\d+")
_BOT_IDENTITY_IDS: Optional[Tuple[str, ...]] = None


def get_conversation_key(payload: Dict[str, object], sender_open_id: str = "") -> str:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    chat_id = str(message.get("chat_id") or "")
    for anchor_key in ("root_id", "thread_id", "parent_id", "message_id"):
        anchor_id = str(message.get(anchor_key) or "")
        if anchor_id and anchor_id in conversation_router.THREAD_MESSAGE_ANCHORS:
            return conversation_router.THREAD_MESSAGE_ANCHORS[anchor_id]
    root_id = str(message.get("root_id") or message.get("message_id") or "")
    return f"{chat_id}:{root_id or 'root'}"


def _thread_alias_key(chat_id: str, sender_open_id: str) -> str:
    return f"{chat_id}"


def _now() -> float:
    return time.monotonic()


def _touch_conversation_state(conversation_key: str) -> None:
    if conversation_key:
        conversation_state_last_active[conversation_key] = _now()


def _touch_thread_alias(chat_id: str, sender_open_id: str) -> None:
    alias_key = _thread_alias_key(chat_id, sender_open_id)
    if alias_key:
        conversation_thread_alias_last_active[alias_key] = _now()


def _mark_processed_message_id(message_id: str) -> None:
    if message_id:
        processed_message_ids[message_id] = _now()


def _mark_processed_event_id(event_id: str) -> None:
    if event_id:
        processed_event_ids[event_id] = _now()


def _reserve_processing_ids(message_id: str, event_id: str) -> bool:
    with _processing_state_lock:
        if message_id and (message_id in processed_message_ids or message_id in processing_message_ids):
            return False
        if event_id and (event_id in processed_event_ids or event_id in processing_event_ids):
            return False
        if message_id:
            processing_message_ids.add(message_id)
        if event_id:
            processing_event_ids.add(event_id)
        return True


def _release_processing_ids(message_id: str, event_id: str) -> None:
    with _processing_state_lock:
        if message_id:
            processing_message_ids.discard(message_id)
        if event_id:
            processing_event_ids.discard(event_id)


def _start_case_worker(**kwargs: object) -> None:
    worker = threading.Thread(target=_process_case_and_reply, kwargs=kwargs, daemon=True)
    worker.start()


def _should_background_case_processing() -> bool:
    return any(
        os.getenv(env_name, "0") == "1"
        for env_name in (
            "FEISHU_BACKGROUND_CASE_PROCESSING",
            "FEISHU_ENABLE_PROVIDER_REVIEW",
            "FEISHU_ENABLE_LOCAL_DIAG",
            "FEISHU_ENABLE_REMOTE_COLLECT",
        )
    )


def _prune_timed_dict(registry: Dict[str, float], ttl_seconds: int, now_value: float, max_items: int = 0) -> None:
    if ttl_seconds <= 0:
        return

    expired_keys = [key for key, timestamp in registry.items() if now_value - timestamp > ttl_seconds]
    for key in expired_keys:
        registry.pop(key, None)

    if max_items > 0 and len(registry) > max_items:
        overflow = len(registry) - max_items
        oldest_keys = sorted(registry, key=registry.get)[:overflow]
        for key in oldest_keys:
            registry.pop(key, None)


def cleanup_runtime_state(force: bool = False) -> None:
    global _last_runtime_state_cleanup_at

    now_value = _now()
    if not force and now_value - _last_runtime_state_cleanup_at < FEISHU_STATE_SWEEP_INTERVAL_SECONDS:
        return

    expired_conversation_keys = [
        key for key, timestamp in conversation_state_last_active.items()
        if now_value - timestamp > FEISHU_SESSION_TTL_SECONDS
    ]
    for key in expired_conversation_keys:
        conversation_state.pop(key, None)
        conversation_state_last_active.pop(key, None)

    expired_alias_keys = [
        key for key, timestamp in conversation_thread_alias_last_active.items()
        if now_value - timestamp > FEISHU_SESSION_TTL_SECONDS
    ]
    for key in expired_alias_keys:
        conversation_thread_aliases.pop(key, None)
        conversation_thread_alias_last_active.pop(key, None)

    _prune_timed_dict(processed_message_ids, FEISHU_DEDUP_TTL_SECONDS, now_value, FEISHU_DEDUP_MAX_ITEMS)
    _prune_timed_dict(processed_event_ids, FEISHU_DEDUP_TTL_SECONDS, now_value, FEISHU_DEDUP_MAX_ITEMS)
    conversation_router.cleanup_thread_message_anchors(FEISHU_SESSION_TTL_SECONDS, now_value)

    if expired_conversation_keys or expired_alias_keys:
        logging.info(
            "runtime state pruned conversation_count=%s alias_count=%s ttl_seconds=%s dedup_ttl_seconds=%s",
            len(expired_conversation_keys),
            len(expired_alias_keys),
            FEISHU_SESSION_TTL_SECONDS,
            FEISHU_DEDUP_TTL_SECONDS,
        )

    _last_runtime_state_cleanup_at = now_value


def _remember_thread_alias(chat_id: str, sender_open_id: str, conversation_key: str) -> None:
    if chat_id and conversation_key:
        conversation_thread_aliases[_thread_alias_key(chat_id, sender_open_id)] = conversation_key
        _touch_thread_alias(chat_id, sender_open_id)


def _extract_root_id_from_conversation_key(conversation_key: str) -> str:
    parts = conversation_key.split(":", 2)
    if len(parts) >= 2:
        return parts[1]
    return ""


def _should_hydrate_thread_root_id(text: str) -> bool:
    return bool(FOLLOW_UP_RE.fullmatch(text))


def _hydrate_thread_root_id(payload: Dict[str, object], sender_open_id: str, text: str) -> Dict[str, object]:
    enriched_payload = copy.deepcopy(payload)
    event = enriched_payload.setdefault("event", {})
    message = event.setdefault("message", {})
    root_id = str(message.get("root_id") or "")
    logging.info(
        "hydrate thread root inspect sender=%s text=%s chat_id=%s message_id=%s root_id=%s parent_id=%s thread_id=%s",
        sender_open_id,
        text,
        str(message.get("chat_id") or ""),
        str(message.get("message_id") or ""),
        root_id,
        str(message.get("parent_id") or ""),
        str(message.get("thread_id") or ""),
    )
    if root_id:
        return enriched_payload
    return enriched_payload


def _hydrate_message_identity(payload: Dict[str, object], message: object) -> Dict[str, object]:
    enriched_payload = copy.deepcopy(payload)
    event = enriched_payload.setdefault("event", {})
    payload_message = event.setdefault("message", {})
    source_fields = {}
    for key in ("chat_id", "message_id", "root_id", "parent_id", "thread_id", "message_type", "chat_type"):
        value = getattr(message, key, "")
        source_fields[key] = value
        if value and not payload_message.get(key):
            payload_message[key] = value
    logging.info(
        "hydrate message identity source_chat_id=%s source_message_id=%s source_root_id=%s source_parent_id=%s source_thread_id=%s source_chat_type=%s payload_chat_id=%s payload_message_id=%s payload_root_id=%s payload_parent_id=%s payload_thread_id=%s payload_chat_type=%s",
        str(source_fields.get("chat_id") or ""),
        str(source_fields.get("message_id") or ""),
        str(source_fields.get("root_id") or ""),
        str(source_fields.get("parent_id") or ""),
        str(source_fields.get("thread_id") or ""),
        str(source_fields.get("chat_type") or ""),
        str(payload_message.get("chat_id") or ""),
        str(payload_message.get("message_id") or ""),
        str(payload_message.get("root_id") or ""),
        str(payload_message.get("parent_id") or ""),
        str(payload_message.get("thread_id") or ""),
        str(payload_message.get("chat_type") or ""),
    )
    return enriched_payload


def _extract_raw_message_text(payload: Dict[str, object]) -> str:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    raw_content = message.get("content")
    if isinstance(raw_content, str):
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            content = {"text": raw_content}
    elif isinstance(raw_content, dict):
        content = raw_content
    else:
        content = {}
    return str(content.get("text") or content.get("content") or "").strip()


def _collect_mention_ids(mention: object) -> Tuple[str, ...]:
    if not isinstance(mention, dict):
        return ()
    ids = []
    mention_id = mention.get("id") if isinstance(mention.get("id"), dict) else {}
    for value in (
        mention.get("open_id"),
        mention.get("user_id"),
        mention_id.get("open_id") if mention_id else "",
        mention_id.get("user_id") if mention_id else "",
    ):
        value_text = str(value or "").strip()
        if value_text and value_text not in ids:
            ids.append(value_text)
    return tuple(ids)


def _get_bot_identity_ids() -> Tuple[str, ...]:
    global _BOT_IDENTITY_IDS

    if _BOT_IDENTITY_IDS is not None:
        return _BOT_IDENTITY_IDS

    ids = []
    for env_name in ("FEISHU_BOT_OPEN_ID", "FEISHU_BOT_USER_ID"):
        value = os.getenv(env_name, "").strip()
        if value and value not in ids:
            ids.append(value)

    _BOT_IDENTITY_IDS = tuple(ids)
    return _BOT_IDENTITY_IDS


def _prime_bot_identity_ids() -> None:
    global _BOT_IDENTITY_IDS

    ids = list(_get_bot_identity_ids())
    try:
        identity = asyncio.run(fetch_bot_identity(get_api_client().config))
    except Exception as exc:
        logging.info("resolve bot identity skipped reason=%s", exc)
        identity = None

    if identity is not None:
        for value in (identity.open_id, identity.user_id):
            value_text = str(value or "").strip()
            if value_text and value_text not in ids:
                ids.append(value_text)

    _BOT_IDENTITY_IDS = tuple(ids)


def _has_group_mention(payload: Dict[str, object]) -> bool:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    raw_content = message.get("content")
    if isinstance(raw_content, str):
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            content = {"text": raw_content}
    elif isinstance(raw_content, dict):
        content = raw_content
    else:
        content = {}

    bot_identity_ids = set(_get_bot_identity_ids())
    mention_candidates = []
    for mention in message.get("mentions") or content.get("mentions") or []:
        mention_candidates.extend(_collect_mention_ids(mention))

    raw_text = str(content.get("text") or content.get("content") or "")
    if bot_identity_ids.intersection(mention_candidates):
        return True

    if MENTION_RE.search(raw_text):
        logging.info(
            "group mention ignored because bot was not mentioned chat_id=%s message_id=%s mentions=%s bot_ids=%s",
            str(message.get("chat_id") or ""),
            str(message.get("message_id") or ""),
            ",".join(mention_candidates),
            ",".join(sorted(bot_identity_ids)),
        )

    return False


def _has_registered_thread_anchor(message: Dict[str, object]) -> bool:
    for anchor_key in ("root_id", "thread_id", "parent_id", "message_id"):
        anchor_id = str(message.get(anchor_key) or "")
        if anchor_id and anchor_id in conversation_router.THREAD_MESSAGE_ANCHORS:
            return True
    return False


def _should_ignore_group_message(payload: Dict[str, object]) -> bool:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    chat_type = str(message.get("chat_type") or "").lower()
    if chat_type != "group":
        return False
    if _has_group_mention(payload):
        return False
    raw_text = _extract_raw_message_text(payload)
    if any(str(message.get(key) or "") for key in ("root_id", "thread_id", "parent_id")):
        if FOLLOW_UP_RE.fullmatch(raw_text):
            return False
        return not _has_registered_thread_anchor(message)
    return True


def resolve_route(text: str, payload: Dict[str, object], sender_open_id: str = "") -> Tuple[str, Optional[str]]:
    conversation_key = get_conversation_key(payload, sender_open_id)
    previous_state = _get_previous_state(conversation_key)
    previous_route = previous_state.get("route")
    target = extract_target(text) or previous_state.get("target") or ""

    if FOLLOW_UP_RE.fullmatch(text) and previous_route:
        return previous_route, conversation_key

    route = classify_text(text, target=target)
    if route == "unknown" and previous_route:
        return previous_route, conversation_key

    return route, conversation_key


def get_next_step_index(conversation_key: Optional[str]) -> int:
    if not conversation_key:
        return 0
    previous_state = _get_previous_state(conversation_key)
    previous_step = previous_state.get("step_index", "-1")
    try:
        return int(previous_step) + 1
    except ValueError:
        return 0


def resolve_case_context(text: str, payload: Dict[str, object], sender_open_id: str = "") -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    conversation_key = get_conversation_key(payload, sender_open_id)
    previous_state = _get_previous_state(conversation_key)
    previous_route = previous_state.get("route")
    previous_target = previous_state.get("target")
    previous_time_key = previous_state.get("time_key")
    target = extract_target(text) or previous_target

    text_route = classify_text(text, target=target or "")
    if FOLLOW_UP_RE.fullmatch(text) and previous_route:
        route = previous_route
    elif text_route == "unknown" and previous_route:
        route = previous_route
    else:
        route = text_route

    time_key = extract_time_key(text) or previous_time_key
    return route, target, time_key, conversation_key


def _get_previous_state(conversation_key: Optional[str]) -> Dict[str, object]:
    if not conversation_key:
        return {}

    state = dict(conversation_state.get(conversation_key, {}))
    session_state = orchestrator.session_store.get(conversation_key)
    if session_state.route and not state.get("route"):
        state["route"] = session_state.route
    if session_state.target and not state.get("target"):
        state["target"] = session_state.target
    if session_state.time_key and not state.get("time_key"):
        state["time_key"] = session_state.time_key
    if "step_index" not in state and session_state.route:
        state["step_index"] = session_state.step_index
    return state


def get_api_client() -> lark.Client:
    global api_client

    if api_client is None:
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise RuntimeError("请先设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        api_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    return api_client


def resolve_sender_display_name(sender: object) -> str:
    if not os.getenv("FEISHU_APP_ID") or not os.getenv("FEISHU_APP_SECRET"):
        return "发言人"

    sender_id = getattr(sender, "sender_id", None)
    open_id = getattr(sender_id, "open_id", "")
    user_id = getattr(sender_id, "user_id", "")
    cache_key = open_id or user_id

    if cache_key and cache_key in sender_name_cache:
        return sender_name_cache[cache_key]

    candidates = []
    if open_id:
        candidates.append((open_id, "open_id"))
    if user_id and user_id != open_id:
        candidates.append((user_id, "user_id"))

    for candidate_id, candidate_type in candidates:
        try:
            request = (
                lark.contact.v3.GetUserRequest.builder()
                .user_id_type(candidate_type)
                .user_id(candidate_id)
                .build()
            )
            response = get_api_client().contact.v3.user.get(request)
            response_code = getattr(response, "code", None)
            response_msg = getattr(response, "msg", None)
            logging.info(
                "resolve sender lookup result user_id=%s type=%s code=%s msg=%s",
                candidate_id,
                candidate_type,
                response_code,
                response_msg,
            )
            if response_code not in (None, 0):
                continue
            user = getattr(getattr(response, "data", None), "user", None)
            logging.info(
                "resolve sender user fields user_id=%s type=%s open_id=%s user_id_field=%s name=%s nickname=%s",
                candidate_id,
                candidate_type,
                getattr(user, "open_id", None),
                getattr(user, "user_id", None),
                getattr(user, "name", None),
                getattr(user, "nickname", None),
            )
            display_name = getattr(user, "nickname", None) or getattr(user, "name", None)
            if display_name and not ID_LIKE_NAME_RE.match(display_name):
                if cache_key:
                    sender_name_cache[cache_key] = display_name
                return display_name
        except Exception:
            logging.exception("resolve sender display name failed user_id=%s type=%s", candidate_id, candidate_type)

    return "发言人"


def build_reply_content(sender_open_id: str, sender_display_name: str, report_text: str) -> str:
    from feishu_agent.core.feishu_listener import FeishuListener

    return FeishuListener(orchestrator=orchestrator)._build_reply_content(
        sender_open_id,
        sender_display_name,
        report_text,
    )


def _send_reply(message_id: str, sender_open_id: str, sender_display_name: str, report_text: str) -> Dict[str, str]:
    from feishu_agent.core.feishu_listener import FeishuListener

    listener = FeishuListener(orchestrator=orchestrator)
    listener._api_client = api_client
    reply_ids = listener._send_case_reply(message_id, sender_open_id, sender_display_name, report_text)
    globals()["api_client"] = listener._api_client
    return reply_ids


def _build_auto_diag_ack(route: str, target: str, previous_state: Dict[str, object]) -> str:
    previous_route = str(previous_state.get("route") or "")
    previous_step_index = int(previous_state.get("step_index") or 0)
    if previous_route == route and previous_step_index >= 0:
        step_label = previous_step_index + 1
        if target:
            return f"已收到：{route.upper()} {target}，正在继续上一条会话第 {step_label} 步排障，请稍等。"
        return f"已收到：{route.upper()} 问题，正在继续上一条会话第 {step_label} 步排障，请稍等。"
    if target:
        return f"已收到：{route.upper()} {target}，正在执行本地排障，请稍等。"
    return f"已收到：{route.upper()} 问题，正在执行本地排障，请稍等。"


def _store_run_result_state(
    *,
    conversation_key: str,
    chat_id: str,
    message_id: str,
    text: str,
    run_result: object,
) -> None:
    if not conversation_key:
        return

    state = conversation_state.setdefault(conversation_key, {})
    state_payload = None
    if hasattr(run_result, "to_conversation_state"):
        try:
            state_payload = run_result.to_conversation_state()
        except Exception:
            logging.exception("run result state export failed conversation_key=%s", conversation_key)
            state_payload = None

    if not isinstance(state_payload, dict):
        draft_result = getattr(run_result, "draft_result", None)
        state_payload = {
            "route": getattr(run_result, "route", ""),
            "target": getattr(run_result, "target", ""),
            "time_key": getattr(run_result, "time_key", ""),
            "step_index": getattr(run_result, "step_index", 0),
            "reply_kind": getattr(run_result, "reply_kind", "text"),
            "domain": getattr(run_result, "domain", ""),
            "sop_path": getattr(run_result, "sop_path", ""),
            "draft_path": getattr(draft_result, "draft_path", "") if draft_result is not None else "",
        }

    state["route"] = str(state_payload.get("route", "") or "")
    state["target"] = str(state_payload.get("target", "") or "")
    state["time_key"] = str(state_payload.get("time_key", "") or "")
    state["text"] = text
    state["message_id"] = message_id
    state["chat_id"] = chat_id
    state["step_index"] = int(state_payload.get("step_index", 0) or 0)
    state["reply_kind"] = str(state_payload.get("reply_kind", "text") or "text")
    state["domain"] = str(state_payload.get("domain", "") or "")
    state["sop_path"] = str(state_payload.get("sop_path", "") or "")
    state["draft_path"] = str(state_payload.get("draft_path", "") or "")
    _touch_conversation_state(conversation_key)


def _process_case_and_reply(
    *,
    text: str,
    payload: Dict[str, object],
    sender_open_id: str,
    sender_display_name: str,
    message_id: str,
    event_id: str,
    conversation_key: str,
    chat_id: str,
) -> None:
    from feishu_agent.core.feishu_listener import FeishuListener

    listener = FeishuListener(orchestrator=orchestrator)
    listener._process_case_and_reply(
        text=text,
        payload=payload,
        sender_open_id=sender_open_id,
        sender_display_name=sender_display_name,
        message_id=message_id,
        event_id=event_id,
        conversation_key=conversation_key,
        chat_id=chat_id,
    )


def handle_im_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    from feishu_agent.core.feishu_listener import FeishuListener

    FeishuListener().handle_im_message(data)


def build_event_handler() -> lark.EventDispatcherHandler:
    from feishu_agent.core.feishu_listener import FeishuListener

    return FeishuListener().build_event_handler()


def main() -> None:
    from feishu_agent.main import main as run_main

    run_main()


if __name__ == "__main__":
    main()
