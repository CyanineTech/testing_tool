import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from feishu_agent import ws_agent
from feishu_agent.core import router as conversation_router
from feishu_agent.core.session import SessionStore


class WsAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_state_file = os.environ.get("FEISHU_SESSION_STATE_FILE")
        os.environ["FEISHU_SESSION_STATE_FILE"] = os.path.join(self._temp_dir.name, "feishu_session_state.json")
        ws_agent.orchestrator.session_store = SessionStore()
        ws_agent.conversation_state.clear()
        ws_agent.conversation_state_last_active.clear()
        ws_agent.conversation_thread_aliases.clear()
        ws_agent.conversation_thread_alias_last_active.clear()
        ws_agent._BOT_IDENTITY_IDS = None
        ws_agent.processing_message_ids.clear()
        ws_agent.processed_message_ids.clear()
        ws_agent.processing_event_ids.clear()
        ws_agent.processed_event_ids.clear()
        conversation_router.THREAD_MESSAGE_ANCHORS.clear()
        conversation_router.THREAD_MESSAGE_ANCHOR_LAST_ACTIVE.clear()

    def tearDown(self) -> None:
        if self._original_state_file is None:
            os.environ.pop("FEISHU_SESSION_STATE_FILE", None)
        else:
            os.environ["FEISHU_SESSION_STATE_FILE"] = self._original_state_file
        self._temp_dir.cleanup()

    def test_handle_im_message_delegates_to_feishu_listener(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_123"},
            "event": {
                "message": {
                    "chat_id": "chat_1",
                    "message_id": "msg_1",
                    "message_type": "text",
                    "content": json.dumps({"text": "继续下一步检查"}),
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(message_id="msg_1", chat_id="chat_1", message_type="text"),
            )
        )

        listener = mock.Mock()
        listener.handle_im_message = mock.Mock()

        with mock.patch("feishu_agent.core.feishu_listener.FeishuListener", return_value=listener) as mocked_listener_cls:
            ws_agent.handle_im_message(data)

        mocked_listener_cls.assert_called_once_with()
        listener.handle_im_message.assert_called_once_with(data)

    def test_handle_im_message_hydrates_message_identity_before_routing(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_456"},
            "event": {
                "message": {
                    "content": json.dumps({"text": "AMR leefung-t9 有什么问题"}),
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(message_id="msg_1", chat_id="chat_1", message_type="text"),
            )
        )

        def _assert_routing_payload(text, routed_payload, sender_open_id=""):
            self.assertEqual(routed_payload["event"]["message"]["message_id"], "msg_1")
            self.assertEqual(routed_payload["event"]["message"]["chat_id"], "chat_1")
            return "amr", "leefung-t9", None, "chat_1:msg_1"

        with mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent, "resolve_case_context", side_effect=_assert_routing_payload), \
            mock.patch.object(ws_agent.orchestrator, "run", return_value=SimpleNamespace(
                reply_text="ok",
                route="amr",
                target="leefung-t9",
                time_key="",
                conversation_key="chat_1:msg_1",
                step_index=0,
                reply_kind="progress",
                domain="amr",
                sop_path="knowledge/common-faults.md",
                draft_result=SimpleNamespace(draft_path="knowledge/_ai_drafts/amr_case.md"),
            )), \
            mock.patch.object(ws_agent, "_send_reply", return_value={"message_id": "bot_msg_1", "root_id": "root_1", "parent_id": "parent_1", "thread_id": "thread_1"}):
            ws_agent.handle_im_message(data)

        self.assertEqual(ws_agent.conversation_state["chat_1:msg_1"]["route"], "amr")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_1"]["domain"], "amr")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_1"]["sop_path"], "knowledge/common-faults.md")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_1"]["reply_kind"], "progress")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_1"]["draft_path"], "knowledge/_ai_drafts/amr_case.md")

    def test_handle_im_message_hydrates_empty_message_identity_fields(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_457"},
            "event": {
                "message": {
                    "chat_id": "",
                    "message_id": "",
                    "root_id": "",
                    "content": json.dumps({"text": "AMR leefung-t9 有什么问题"}),
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(message_id="msg_2", chat_id="chat_1", message_type="text", root_id="root_2"),
            )
        )

        def _assert_routing_payload(text, routed_payload, sender_open_id=""):
            self.assertEqual(routed_payload["event"]["message"]["message_id"], "msg_2")
            self.assertEqual(routed_payload["event"]["message"]["chat_id"], "chat_1")
            self.assertEqual(routed_payload["event"]["message"]["root_id"], "root_2")
            return "amr", "leefung-t9", None, "chat_1:msg_2"

        with mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent, "resolve_case_context", side_effect=_assert_routing_payload), \
            mock.patch.object(ws_agent.orchestrator, "run", return_value=SimpleNamespace(
                reply_text="ok",
                route="amr",
                target="leefung-t9",
                time_key="",
                conversation_key="chat_1:msg_2",
                step_index=0,
                reply_kind="progress",
                domain="amr",
                sop_path="knowledge/common-faults.md",
                draft_result=None,
            )), \
            mock.patch.object(ws_agent, "_send_reply", return_value={"message_id": "bot_msg_2", "root_id": "root_2", "parent_id": "", "thread_id": ""}):
            ws_agent.handle_im_message(data)

        self.assertEqual(ws_agent.conversation_state["chat_1:msg_2"]["route"], "amr")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_2"]["domain"], "amr")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_2"]["sop_path"], "knowledge/common-faults.md")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_2"]["reply_kind"], "progress")
        self.assertEqual(ws_agent.conversation_state["chat_1:msg_2"]["draft_path"], "")

    def test_store_run_result_state_persists_standard_run_fields(self) -> None:
        run_result = SimpleNamespace(
            route="network",
            target="192.168.1.250",
            time_key="2026_06_13",
            step_index=2,
            reply_kind="progress",
            domain="network",
            sop_path="knowledge/common-faults.md",
            draft_result=SimpleNamespace(draft_path="knowledge/_ai_drafts/network_case.md"),
        )

        ws_agent._store_run_result_state(
            conversation_key="chat_1:root_1",
            chat_id="chat_1",
            message_id="msg_1",
            text="继续",
            run_result=run_result,
        )

        state = ws_agent.conversation_state["chat_1:root_1"]
        self.assertEqual(state["route"], "network")
        self.assertEqual(state["target"], "192.168.1.250")
        self.assertEqual(state["time_key"], "2026_06_13")
        self.assertEqual(state["step_index"], 2)
        self.assertEqual(state["reply_kind"], "progress")
        self.assertEqual(state["domain"], "network")
        self.assertEqual(state["sop_path"], "knowledge/common-faults.md")
        self.assertEqual(state["draft_path"], "knowledge/_ai_drafts/network_case.md")

    def test_store_run_result_state_prefers_standard_state_export(self) -> None:
        class _RunResult:
            def to_conversation_state(self):
                return {
                    "route": "rcs",
                    "target": "leefung-s1",
                    "time_key": "2026_06_11",
                    "step_index": 3,
                    "reply_kind": "progress",
                    "domain": "rcs",
                    "sop_path": "knowledge/task_dispatch/rcs-task-system.md",
                    "draft_path": "knowledge/_ai_drafts/rcs_case.md",
                }

        ws_agent._store_run_result_state(
            conversation_key="chat_2:root_2",
            chat_id="chat_2",
            message_id="msg_2",
            text="继续",
            run_result=_RunResult(),
        )

        state = ws_agent.conversation_state["chat_2:root_2"]
        self.assertEqual(state["route"], "rcs")
        self.assertEqual(state["target"], "leefung-s1")
        self.assertEqual(state["time_key"], "2026_06_11")
        self.assertEqual(state["step_index"], 3)
        self.assertEqual(state["reply_kind"], "progress")
        self.assertEqual(state["domain"], "rcs")
        self.assertEqual(state["sop_path"], "knowledge/task_dispatch/rcs-task-system.md")
        self.assertEqual(state["draft_path"], "knowledge/_ai_drafts/rcs_case.md")

    def test_process_case_and_reply_delegates_to_feishu_listener(self) -> None:
        listener = SimpleNamespace()
        listener._process_case_and_reply = mock.Mock()

        with mock.patch("feishu_agent.core.feishu_listener.FeishuListener", return_value=listener) as mocked_listener_cls:
            ws_agent._process_case_and_reply(
                text="网络连不上 192.168.1.250",
                payload={"event": {"message": {"message_id": "msg_1"}}},
                sender_open_id="ou_1",
                sender_display_name="张三",
                message_id="msg_1",
                event_id="evt_1",
                conversation_key="chat_1:root_1",
                chat_id="chat_1",
            )

        mocked_listener_cls.assert_called_once_with(orchestrator=ws_agent.orchestrator)
        listener._process_case_and_reply.assert_called_once()

    def test_send_reply_delegates_to_feishu_listener(self) -> None:
        listener = SimpleNamespace()
        listener._api_client = object()
        listener._send_case_reply = mock.Mock(return_value={"message_id": "bot_msg_1", "root_id": "", "parent_id": "", "thread_id": ""})

        with mock.patch("feishu_agent.core.feishu_listener.FeishuListener", return_value=listener) as mocked_listener_cls:
            result = ws_agent._send_reply("msg_1", "ou_1", "张三", "ok")

        mocked_listener_cls.assert_called_once_with(orchestrator=ws_agent.orchestrator)
        listener._send_case_reply.assert_called_once_with("msg_1", "ou_1", "张三", "ok")
        self.assertEqual(result["message_id"], "bot_msg_1")

    def test_handle_im_message_ignores_group_message_without_mention(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_999"},
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "chat_type": "group",
                    "message_id": "msg_9",
                    "message_type": "text",
                    "content": json.dumps({"text": "AMR leefung-t9 有什么问题"}),
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(
                    message_id="msg_9",
                    chat_id="chat_9",
                    chat_type="group",
                    message_type="text",
                ),
            )
        )

        with mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run") as mocked_handle_case, \
            mock.patch.object(ws_agent, "_send_reply") as mocked_send_reply:
            ws_agent.handle_im_message(data)

        mocked_handle_case.assert_not_called()
        mocked_send_reply.assert_not_called()
        self.assertNotIn("msg_9", ws_agent.processed_message_ids)

    def test_handle_im_message_ignores_group_message_when_mention_is_not_bot(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_998"},
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "chat_type": "group",
                    "message_id": "msg_8",
                    "message_type": "text",
                    "content": json.dumps({
                        "text": "AMR leefung-t9 有什么问题",
                        "mentions": [
                            {
                                "key": "@_user_1",
                                "name": "陈浩",
                                "id": {"open_id": "ou_other", "user_id": "u_other"},
                            }
                        ],
                    }),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "name": "陈浩",
                            "id": {"open_id": "ou_other", "user_id": "u_other"},
                        }
                    ],
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(message_id="msg_8", chat_id="chat_9", chat_type="group", message_type="text"),
            )
        )

        with mock.patch.object(ws_agent, "_get_bot_identity_ids", return_value=("ou_bot",)), \
            mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run") as mocked_handle_case, \
            mock.patch.object(ws_agent, "_send_reply") as mocked_send_reply:
            ws_agent.handle_im_message(data)

        mocked_handle_case.assert_not_called()
        mocked_send_reply.assert_not_called()
        self.assertNotIn("msg_8", ws_agent.processed_message_ids)

    def test_handle_im_message_ignores_group_thread_without_anchor_and_bot_mention(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_997"},
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "chat_type": "group",
                    "message_id": "msg_7",
                    "root_id": "root_7",
                    "thread_id": "thread_7",
                    "parent_id": "parent_7",
                    "message_type": "text",
                    "content": json.dumps({
                        "text": "123",
                        "mentions": [
                            {
                                "key": "@_user_1",
                                "name": "陈浩",
                                "id": {"open_id": "ou_other", "user_id": "u_other"},
                            }
                        ],
                    }),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "name": "陈浩",
                            "id": {"open_id": "ou_other", "user_id": "u_other"},
                        }
                    ],
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(
                    message_id="msg_7",
                    chat_id="chat_9",
                    chat_type="group",
                    message_type="text",
                    root_id="root_7",
                    thread_id="thread_7",
                    parent_id="parent_7",
                ),
            )
        )

        with mock.patch.object(ws_agent, "_get_bot_identity_ids", return_value=("ou_bot",)), \
            mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run") as mocked_handle_case, \
            mock.patch.object(ws_agent, "_send_reply") as mocked_send_reply:
            ws_agent.handle_im_message(data)

        mocked_handle_case.assert_not_called()
        mocked_send_reply.assert_not_called()
        self.assertNotIn("msg_7", ws_agent.processed_message_ids)

    def test_handle_im_message_allows_group_thread_follow_up_without_mention_after_restart(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_follow_up"},
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "chat_type": "group",
                    "message_id": "msg_follow_up",
                    "root_id": "root_follow_up",
                    "thread_id": "thread_follow_up",
                    "parent_id": "parent_follow_up",
                    "message_type": "text",
                    "content": json.dumps({"text": "继续"}),
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(
                    message_id="msg_follow_up",
                    chat_id="chat_9",
                    chat_type="group",
                    message_type="text",
                    root_id="root_follow_up",
                    thread_id="thread_follow_up",
                    parent_id="parent_follow_up",
                ),
            )
        )

        with mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run", return_value=SimpleNamespace(
                reply_text="ok",
                route="amr",
                target="leefung-t9",
                time_key="",
                conversation_key="chat_9:root_follow_up",
                step_index=1,
                reply_kind="progress",
            )), \
            mock.patch("feishu_agent.core.feishu_listener.FeishuListener._send_case_reply", return_value={"message_id": "bot_msg_follow_up", "root_id": "root_follow_up", "parent_id": "msg_follow_up", "thread_id": "thread_follow_up"}) as mocked_send_reply:
            ws_agent.handle_im_message(data)

        mocked_send_reply.assert_called_once()
        self.assertEqual(ws_agent.conversation_state["chat_9:root_follow_up"]["route"], "amr")

    def test_handle_im_message_logs_raw_text_before_normalization(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        payload = {
            "header": {"event_id": "evt_996"},
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "chat_type": "group",
                    "message_id": "msg_6",
                    "message_type": "text",
                    "content": json.dumps({
                        "text": "@陈浩123",
                        "mentions": [
                            {
                                "key": "@_user_1",
                                "name": "陈浩",
                                "id": {"open_id": "ou_other", "user_id": "u_other"},
                            }
                        ],
                    }),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "name": "陈浩",
                            "id": {"open_id": "ou_other", "user_id": "u_other"},
                        }
                    ],
                }
            },
        }
        data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(
                    message_id="msg_6",
                    chat_id="chat_9",
                    chat_type="group",
                    message_type="text",
                ),
            )
        )

        with mock.patch.object(ws_agent, "_get_bot_identity_ids", return_value=("ou_bot",)), \
            mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run") as mocked_handle_case, \
            mock.patch.object(ws_agent, "_send_reply") as mocked_send_reply, \
            self.assertLogs(level="INFO") as captured_logs:
            ws_agent.handle_im_message(data)

        mocked_handle_case.assert_not_called()
        mocked_send_reply.assert_not_called()
        self.assertNotIn("msg_6", ws_agent.processed_message_ids)
        self.assertTrue(any("raw_text=@陈浩123" in line for line in captured_logs.output))

    def test_hydrate_thread_root_id_does_not_use_chat_alias(self) -> None:
        ws_agent.conversation_thread_aliases["chat_1"] = "chat_1:root_1"

        follow_up_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_1",
                    "content": json.dumps({"text": "继续下一步"}),
                }
            }
        }
        follow_up_result = ws_agent._hydrate_thread_root_id(follow_up_payload, "", "继续下一步")
        self.assertNotIn("root_id", follow_up_result["event"]["message"])

        new_issue_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_1",
                    "content": json.dumps({"text": "AMR leefung-t9 有什么问题"}),
                }
            }
        }
        new_issue_result = ws_agent._hydrate_thread_root_id(new_issue_payload, "", "AMR leefung-t9 有什么问题")
        self.assertNotIn("root_id", new_issue_result["event"]["message"])

    def test_cleanup_runtime_state_expires_old_conversations(self) -> None:
        ws_agent.conversation_state["chat_1:root_1"] = {"route": "amr"}
        ws_agent.conversation_state_last_active["chat_1:root_1"] = 1.0
        ws_agent.conversation_thread_aliases["chat_1"] = "chat_1:root_1"
        ws_agent.conversation_thread_alias_last_active["chat_1"] = 1.0
        ws_agent.processed_message_ids["msg_old"] = 1.0
        ws_agent.processed_event_ids["evt_old"] = 1.0

        with mock.patch.object(ws_agent, "_now", return_value=max(ws_agent.FEISHU_SESSION_TTL_SECONDS, ws_agent.FEISHU_DEDUP_TTL_SECONDS) + 10):
            ws_agent.cleanup_runtime_state(force=True)

        self.assertNotIn("chat_1:root_1", ws_agent.conversation_state)
        self.assertNotIn("chat_1:root_1", ws_agent.conversation_state_last_active)
        self.assertNotIn("chat_1", ws_agent.conversation_thread_aliases)
        self.assertNotIn("chat_1", ws_agent.conversation_thread_alias_last_active)
        self.assertNotIn("msg_old", ws_agent.processed_message_ids)
        self.assertNotIn("evt_old", ws_agent.processed_event_ids)

    def test_thread_anchor_resolves_bot_reply_message(self) -> None:
        conversation_router.register_thread_message_anchor("bot_msg_1", "chat_1:root_1")

        payload = {
            "event": {
                "message": {
                    "chat_id": "chat_1",
                    "root_id": "bot_msg_1",
                    "content": json.dumps({"text": "继续"}),
                }
            }
        }

        self.assertEqual(ws_agent.get_conversation_key(payload, ""), "chat_1:root_1")

    def test_thread_anchor_resolves_thread_id_and_parent_id(self) -> None:
        conversation_router.register_thread_message_anchor(
            "bot_msg_2",
            "chat_2:root_2",
            root_id="root_2",
            parent_id="parent_2",
            thread_id="thread_2",
        )

        parent_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_2",
                    "parent_id": "parent_2",
                    "content": json.dumps({"text": "继续"}),
                }
            }
        }
        thread_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_2",
                    "thread_id": "thread_2",
                    "content": json.dumps({"text": "继续下一步"}),
                }
            }
        }
        thread_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_2",
                    "thread_id": "thread_2",
                    "content": json.dumps({"text": "继续下一步"}),
                }
            }
        }

        self.assertEqual(ws_agent.get_conversation_key(parent_payload, ""), "chat_2:root_2")
        self.assertEqual(ws_agent.get_conversation_key(thread_payload, ""), "chat_2:root_2")

    def test_resolve_case_context_uses_persisted_session_state(self) -> None:
        conversation_key = "chat_9:root_follow_up"
        ws_agent.orchestrator.session_store.update(
            conversation_key,
            route="amr",
            target="leefung-t9",
            time_key="",
            step_index=1,
            last_report="已收到：AMR 机器人问题\n摘要：copilotcli 超时后已终止。",
        )
        payload = {
            "event": {
                "message": {
                    "chat_id": "chat_9",
                    "message_id": "msg_follow_up_2",
                    "root_id": "root_follow_up",
                    "parent_id": "root_follow_up",
                    "thread_id": "thread_follow_up",
                    "chat_type": "group",
                    "content": json.dumps({"text": "继续"}),
                }
            }
        }

        route, target, time_key, resolved_key = ws_agent.resolve_case_context("继续", payload, "ou_1")

        self.assertEqual(route, "amr")
        self.assertEqual(target, "leefung-t9")
        self.assertIsNone(time_key)
        self.assertEqual(resolved_key, conversation_key)

    def test_inbound_message_registers_anchor_for_follow_up(self) -> None:
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_1"),
        )
        initial_payload = {
            "header": {"event_id": "evt_789"},
            "event": {
                "message": {
                    "chat_id": "chat_3",
                    "message_id": "msg_root_1",
                    "message_type": "text",
                    "content": json.dumps({"text": "网络连不上 192.168.1.250"}),
                }
            },
        }
        initial_data = SimpleNamespace(
            event=SimpleNamespace(
                sender=sender,
                message=SimpleNamespace(message_id="msg_root_1", chat_id="chat_3", message_type="text"),
            )
        )

        with mock.patch.object(ws_agent.lark.JSON, "marshal", return_value=json.dumps(initial_payload, ensure_ascii=False)), \
            mock.patch.object(ws_agent, "resolve_sender_display_name", return_value="张三"), \
            mock.patch.object(ws_agent.orchestrator, "run", return_value=SimpleNamespace(
                reply_text="ok",
                route="network",
                target="192.168.1.250",
                time_key="",
                conversation_key="chat_3:msg_root_1",
                step_index=0,
                reply_kind="progress",
            )), \
            mock.patch.object(ws_agent, "_send_reply", return_value={"message_id": "bot_msg_1", "root_id": "msg_root_1", "parent_id": "", "thread_id": ""}):
            ws_agent.handle_im_message(initial_data)

        follow_up_payload = {
            "event": {
                "message": {
                    "chat_id": "chat_3",
                    "root_id": "msg_root_1",
                    "content": json.dumps({"text": "继续"}),
                }
            }
        }

        self.assertEqual(ws_agent.get_conversation_key(follow_up_payload, ""), "chat_3:msg_root_1")

    def test_resolve_case_context_uses_target_aware_rcs_classification(self) -> None:
        payload = {
            "event": {
                "message": {
                    "chat_id": "chat_rcs",
                    "message_id": "msg_rcs",
                    "chat_type": "group",
                    "content": json.dumps({"text": "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"}),
                }
            }
        }

        route, target, time_key, resolved_key = ws_agent.resolve_case_context(
            "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败",
            payload,
            "ou_1",
        )

        self.assertEqual(route, "rcs")
        self.assertEqual(target, "leefung-s1")
        self.assertEqual(time_key, "2026_06_11")
        self.assertEqual(resolved_key, "chat_rcs:msg_rcs")


if __name__ == "__main__":
    unittest.main()
