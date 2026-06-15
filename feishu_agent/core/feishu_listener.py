import json
import threading
from typing import Any, Dict, Optional, Tuple

import lark_oapi as lark

from feishu_agent import ws_agent
from feishu_agent.core.orchestrator import CaseRequest, Orchestrator


class FeishuListener:
    def __init__(self, orchestrator: Optional[Orchestrator] = None) -> None:
        self._orchestrator = ws_agent.configure_runtime(orchestrator)
        self._api_client = None

    def build_event_handler(self) -> lark.EventDispatcherHandler:
        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.handle_im_message)
            .build()
        )

    def parse_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
        text, payload = ws_agent.parse_message(event)
        return {
            "text": text,
            "payload": payload,
        }

    def handle_event(self, event: Dict[str, Any]) -> None:
        payload = self.parse_message(event)["payload"]
        raw = lark.JSON.unmarshal(json.dumps(payload, ensure_ascii=False), lark.im.v1.P2ImMessageReceiveV1)
        self.handle_im_message(raw)

    def _extract_event_context(self, data: lark.im.v1.P2ImMessageReceiveV1) -> Dict[str, Any]:
        payload = json.loads(lark.JSON.marshal(data))
        raw_text = ws_agent._extract_raw_message_text(payload)
        text, _ = ws_agent.parse_message(payload)
        header = payload.get("header") or {}
        event_id = str(header.get("event_id") or header.get("trace_id") or "")
        sender = getattr(getattr(data, "event", None), "sender", None)
        sender_display_name = ws_agent.resolve_sender_display_name(sender)
        sender_open_id = getattr(getattr(sender, "sender_id", None), "open_id", "")
        sender_type = str(getattr(sender, "sender_type", "") or "").lower()
        message = getattr(getattr(data, "event", None), "message", None)
        payload = ws_agent._hydrate_message_identity(payload, message)
        message_id = getattr(message, "message_id", "")
        chat_id = getattr(message, "chat_id", "")
        message_type = getattr(message, "message_type", "")
        return {
            "payload": payload,
            "raw_text": raw_text,
            "text": text,
            "event_id": event_id,
            "sender": sender,
            "sender_display_name": sender_display_name,
            "sender_open_id": sender_open_id,
            "sender_type": sender_type,
            "message": message,
            "message_id": message_id,
            "chat_id": chat_id,
            "message_type": message_type,
        }

    def _should_skip_event(self, context: Dict[str, Any]) -> bool:
        payload = context["payload"]
        text = context["text"]
        event_id = context["event_id"]
        sender_type = context["sender_type"]
        chat_id = context["chat_id"]
        message_id = context["message_id"]
        sender_display_name = context["sender_display_name"]
        sender_open_id = context["sender_open_id"]

        if sender_type and sender_type != "user":
            ws_agent.logging.info("ignore non-user sender sender_type=%s text=%s", sender_type, text)
            return True
        if event_id and (event_id in ws_agent.processed_event_ids or event_id in ws_agent.processing_event_ids):
            ws_agent.logging.info("duplicate event ignored event_id=%s message=%s", event_id, text)
            return True

        context["payload"] = ws_agent._hydrate_thread_root_id(payload, sender_open_id, text)
        payload = context["payload"]
        if ws_agent._should_ignore_group_message(payload):
            ws_agent.logging.info(
                "ignore group message without mention chat_id=%s message_id=%s sender=%s text=%s",
                chat_id,
                message_id,
                sender_display_name,
                text,
            )
            return True
        if not ws_agent._reserve_processing_ids(message_id, event_id):
            ws_agent.logging.info("duplicate event ignored event_id=%s message=%s", event_id, text)
            return True
        return False

    def _attach_conversation_context(self, context: Dict[str, Any]) -> Tuple[str, Any]:
        payload = context["payload"]
        text = context["text"]
        sender_open_id = context["sender_open_id"]
        message = context["message"]
        message_id = context["message_id"]
        chat_id = context["chat_id"]

        route, target, time_key, conversation_key = ws_agent.resolve_case_context(text, payload, sender_open_id)
        previous_state = ws_agent.conversation_state.get(conversation_key or "", {})
        payload_message = (payload.get("event") or {}).get("message") or {}

        context["route"] = route
        context["target"] = target
        context["time_key"] = time_key
        context["conversation_key"] = conversation_key
        context["previous_state"] = previous_state
        context["payload_message"] = payload_message

        if not message_id:
            ws_agent.logging.warning("feishu ws event missing message_id, skip reply")
            return conversation_key, previous_state

        if conversation_key:
            ws_agent._remember_thread_alias(chat_id, sender_open_id, conversation_key)
            ws_agent._touch_conversation_state(conversation_key)
            ws_agent.conversation_router.register_thread_message_anchor(
                message_id,
                conversation_key,
                root_id=str(getattr(message, "root_id", "") or ""),
                parent_id=str(getattr(message, "parent_id", "") or ""),
                thread_id=str(getattr(message, "thread_id", "") or ""),
            )
        ws_agent.logging.info(
            "message hydration result conversation_key=%s alias=%s previous_route=%s previous_step_index=%s payload_chat_id=%s payload_message_id=%s payload_root_id=%s payload_parent_id=%s payload_thread_id=%s",
            conversation_key,
            ws_agent.conversation_thread_aliases.get(ws_agent._thread_alias_key(chat_id, sender_open_id), ""),
            previous_state.get("route"),
            previous_state.get("step_index"),
            str(payload_message.get("chat_id") or ""),
            str(payload_message.get("message_id") or ""),
            str(payload_message.get("root_id") or ""),
            str(payload_message.get("parent_id") or ""),
            str(payload_message.get("thread_id") or ""),
        )

        ws_agent.logging.info(
            "message resolved conversation_key=%s route=%s target=%s time_key=%s previous_route=%s previous_step_index=%s",
            conversation_key,
            route,
            target,
            time_key,
            previous_state.get("route"),
            previous_state.get("step_index"),
        )
        return conversation_key, previous_state

    def _dispatch_case(self, context: Dict[str, Any]) -> bool:
        text = context["text"]
        payload = context["payload"]
        event_id = context["event_id"]
        message_id = context["message_id"]
        chat_id = context["chat_id"]
        sender_open_id = context["sender_open_id"]
        sender_display_name = context["sender_display_name"]
        message_type = context["message_type"]
        route = context["route"]
        target = context["target"]
        time_key = context["time_key"]
        conversation_key = context["conversation_key"] or ""
        previous_state = context["previous_state"]

        ws_agent.logging.info(
            "feishu ws event received route=%s sender=%s message_id=%s chat_id=%s message_type=%s text=%s",
            route,
            sender_display_name,
            message_id,
            chat_id,
            message_type,
            text,
        )
        ws_agent.logging.debug("full payload=%s", json.dumps(payload, ensure_ascii=False, indent=2))
        plan = ws_agent.orchestrator.build_dispatch_plan(
            route=route,
            target=target or "",
            time_key=time_key or "",
            conversation_key=conversation_key,
            previous_state=previous_state,
        )

        if plan.should_ack and plan.ack_text:
            self._send_ack_reply(
                message_id=message_id,
                sender_open_id=sender_open_id,
                sender_display_name=sender_display_name,
                ack_text=plan.ack_text,
            )

        if plan.requires_worker and plan.should_background:
            self._start_case_worker(
                text=text,
                payload=payload,
                sender_open_id=sender_open_id,
                sender_display_name=sender_display_name,
                message_id=message_id,
                event_id=event_id,
                conversation_key=conversation_key,
                chat_id=chat_id,
            )
            return True

        if plan.requires_worker:
            self._process_case_and_reply(
                text=text,
                payload=payload,
                sender_open_id=sender_open_id,
                sender_display_name=sender_display_name,
                message_id=message_id,
                event_id=event_id,
                conversation_key=conversation_key,
                chat_id=chat_id,
            )
            return False

        return False

    def _send_ack_reply(
        self,
        *,
        message_id: str,
        sender_open_id: str,
        sender_display_name: str,
        ack_text: str,
    ) -> None:
        try:
            self._send_case_reply(
                message_id,
                sender_open_id,
                sender_display_name,
                ack_text,
            )
        except Exception:
            ws_agent.logging.exception("ack reply failed message_id=%s", message_id)

    def _start_case_worker(self, **kwargs: object) -> None:
        worker = threading.Thread(target=self._process_case_and_reply, kwargs=kwargs, daemon=True)
        worker.start()

    def _store_run_result_state(
        self,
        *,
        conversation_key: str,
        chat_id: str,
        message_id: str,
        text: str,
        run_result: object,
    ) -> None:
        ws_agent._store_run_result_state(
            conversation_key=conversation_key,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            run_result=run_result,
        )

    def _build_reply_content(self, sender_open_id: str, sender_display_name: str, report_text: str) -> str:
        first_line, *rest_lines = str(report_text or "").split("\n")
        return json.dumps(
            {
                "zh_cn": {
                    "title": "",
                    "content": [
                        [
                            {
                                "tag": "text",
                                "text": first_line,
                            },
                        ],
                        [
                            {
                                "tag": "at",
                                "user_id": sender_open_id,
                                "user_name": sender_display_name,
                            },
                            {
                                "tag": "text",
                                "text": ("\n" + "\n".join(rest_lines)) if rest_lines else "",
                            },
                        ],
                    ],
                }
            },
            ensure_ascii=False,
        )

    def _send_case_reply(self, message_id: str, sender_open_id: str, sender_display_name: str, reply_text: str) -> Dict[str, str]:
        client = self._api_client
        if client is None:
            try:
                client = ws_agent.get_api_client()
                self._api_client = client
            except Exception:
                ws_agent.logging.exception("api client unavailable, skip reply message_id=%s", message_id)
                return {"message_id": "", "root_id": "", "parent_id": "", "thread_id": ""}

        if sender_open_id:
            reply_msg_type = "post"
            reply_content = self._build_reply_content(sender_open_id, sender_display_name, reply_text)
        else:
            reply_msg_type = "text"
            reply_content = json.dumps({"text": reply_text}, ensure_ascii=False)

        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .msg_type(reply_msg_type)
                .content(reply_content)
                .reply_in_thread(True)
                .build()
            )
            .build()
        )

        response = client.im.v1.message.reply(request)
        response_data = getattr(response, "data", None)
        ws_agent.logging.info(
            "reply sent code=%s msg=%s message_id=%s response_data=%s",
            getattr(response, "code", None),
            getattr(response, "msg", None),
            message_id,
            response_data,
        )
        return {
            "message_id": getattr(response_data, "message_id", ""),
            "root_id": getattr(response_data, "root_id", ""),
            "parent_id": getattr(response_data, "parent_id", ""),
            "thread_id": getattr(response_data, "thread_id", ""),
        }

    def _register_reply_anchor(
        self,
        *,
        conversation_key: str,
        chat_id: str,
        sender_open_id: str,
        reply_ids: Dict[str, str],
    ) -> None:
        if not conversation_key or not reply_ids.get("message_id"):
            return

        ws_agent.conversation_router.register_thread_message_anchor(
            reply_ids.get("message_id", ""),
            conversation_key,
            root_id=reply_ids.get("root_id", ""),
            parent_id=reply_ids.get("parent_id", ""),
            thread_id=reply_ids.get("thread_id", ""),
        )
        ws_agent.logging.info(
            "process case reply anchored conversation_key=%s reply_message_id=%s root_id=%s parent_id=%s thread_id=%s",
            conversation_key,
            reply_ids.get("message_id", ""),
            reply_ids.get("root_id", ""),
            reply_ids.get("parent_id", ""),
            reply_ids.get("thread_id", ""),
        )
        ws_agent._remember_thread_alias(chat_id, sender_open_id, conversation_key)

    def _mark_case_processed(self, message_id: str, event_id: str) -> None:
        ws_agent._mark_processed_message_id(message_id)
        if event_id:
            ws_agent._mark_processed_event_id(event_id)

    def _release_processing_ids(self, message_id: str, event_id: str) -> None:
        ws_agent.processing_message_ids.discard(message_id)
        if event_id:
            ws_agent.processing_event_ids.discard(event_id)

    def _process_case_and_reply(
        self,
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
        try:
            ws_agent.logging.info(
                "process case start conversation_key=%s chat_id=%s message_id=%s event_id=%s text=%s",
                conversation_key,
                chat_id,
                message_id,
                event_id,
                text,
            )
            case_result = self._orchestrator.run(
                CaseRequest(
                    text=text,
                    payload=payload,
                    sender_open_id=sender_open_id,
                    sender_display_name=sender_display_name,
                    message_id=message_id,
                )
            )
            self._store_run_result_state(
                conversation_key=conversation_key,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                run_result=case_result,
            )

            reply_ids = self._send_case_reply(message_id, sender_open_id, sender_display_name, case_result.reply_text)
            self._register_reply_anchor(
                conversation_key=conversation_key,
                chat_id=chat_id,
                sender_open_id=sender_open_id,
                reply_ids=reply_ids,
            )
            self._mark_case_processed(message_id, event_id)
            ws_agent.logging.info(
                "process case end conversation_key=%s route=%s target=%s step_index=%s reply_kind=%s",
                conversation_key,
                case_result.route,
                case_result.target,
                case_result.step_index,
                case_result.reply_kind,
            )
        except Exception:
            ws_agent.logging.exception("reply failed message_id=%s", message_id)
        finally:
            self._release_processing_ids(message_id, event_id)

    def handle_im_message(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        ws_agent.cleanup_runtime_state()
        context = self._extract_event_context(data)
        ws_agent.logging.info(
            "feishu ws event received chat_id=%s message_id=%s event_id=%s sender=%s type=%s raw_text=%s text=%s",
            context["chat_id"],
            context["message_id"],
            context["event_id"],
            context["sender_display_name"],
            context["message_type"],
            context["raw_text"],
            context["text"],
        )
        if self._should_skip_event(context):
            return
        self._attach_conversation_context(context)

        try:
            defer_processing_release = self._dispatch_case(context)
            return
        except Exception:
            ws_agent.logging.exception("reply failed message_id=%s", context["message_id"])
        finally:
            if not defer_processing_release:
                ws_agent._release_processing_ids(context["message_id"], context["event_id"])

    def start(self) -> None:
        self._orchestrator = ws_agent.configure_runtime(self._orchestrator)
        self._api_client = ws_agent.get_api_client()
        ws_agent._prime_bot_identity_ids()
        client = lark.ws.Client(
            ws_agent.os.getenv("FEISHU_APP_ID", ""),
            ws_agent.os.getenv("FEISHU_APP_SECRET", ""),
            event_handler=self.build_event_handler(),
            log_level=lark.LogLevel.DEBUG,
        )
        ws_agent.api_client = self._api_client
        client.start()
