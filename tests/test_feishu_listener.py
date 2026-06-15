import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import lark_oapi as lark

from feishu_agent.core.feishu_listener import FeishuListener


class FeishuListenerTests(unittest.TestCase):
    def test_parse_message_uses_existing_parser(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()
        event = {
            "event": {
                "message": {
                    "content": json.dumps({"text": "@_user_1 网络连不上 192.168.1.250"}),
                }
            }
        }

        parsed = listener.parse_message(event)

        self.assertEqual(parsed["text"], "网络连不上 192.168.1.250")
        self.assertEqual(parsed["payload"], event)

    def test_build_event_handler_registers_ws_agent_handler(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        handler = listener.build_event_handler()

        self.assertIsInstance(handler, lark.EventDispatcherHandler)

    def test_start_uses_new_listener_entry(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()), \
            patch("feishu_agent.core.feishu_listener.ws_agent._prime_bot_identity_ids") as mocked_prime, \
            patch("feishu_agent.core.feishu_listener.lark.ws.Client") as mocked_client:
            client_instance = mocked_client.return_value
            listener.start()

        mocked_prime.assert_called_once()
        client_instance.start.assert_called_once()

    def test_dispatch_case_uses_listener_worker_entrypoints(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        context = {
            "text": "网络连不上 192.168.1.250",
            "payload": {"event": {"message": {"message_id": "msg_1"}}},
            "event_id": "evt_1",
            "message_id": "msg_1",
            "chat_id": "chat_1",
            "sender_open_id": "ou_1",
            "sender_display_name": "张三",
            "message_type": "text",
            "route": "network",
            "target": "192.168.1.250",
            "time_key": "",
            "conversation_key": "chat_1:root_1",
            "previous_state": {},
        }
        plan = SimpleNamespace(
            should_ack=True,
            ack_text="收到，处理中",
            requires_worker=True,
            should_background=False,
        )

        with patch("feishu_agent.core.feishu_listener.ws_agent.orchestrator.build_dispatch_plan", return_value=plan), \
            patch.object(listener, "_send_ack_reply") as mocked_ack, \
            patch.object(listener, "_process_case_and_reply") as mocked_process:
            deferred = listener._dispatch_case(context)

        self.assertFalse(deferred)
        mocked_ack.assert_called_once()
        mocked_process.assert_called_once()

    def test_send_ack_reply_uses_send_case_reply(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        with patch.object(listener, "_send_case_reply") as mocked_reply:
            listener._send_ack_reply(
                message_id="msg_1",
                sender_open_id="ou_1",
                sender_display_name="张三",
                ack_text="收到，处理中",
            )

        mocked_reply.assert_called_once_with("msg_1", "ou_1", "张三", "收到，处理中")

    def test_build_reply_content_formats_first_line_and_mention(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        content = json.loads(listener._build_reply_content("ou_1", "张三", "第一行\n第二行"))
        blocks = content["zh_cn"]["content"]

        self.assertEqual(blocks[0][0]["text"], "第一行")
        self.assertEqual(blocks[1][0]["user_id"], "ou_1")
        self.assertIn("第二行", blocks[1][1]["text"])

    def test_send_case_reply_uses_listener_api_client(self) -> None:
        fake_response = SimpleNamespace(
            code=0,
            msg="ok",
            data=SimpleNamespace(message_id="bot_msg_1", root_id="root_1", parent_id="parent_1", thread_id="thread_1"),
        )
        fake_client = SimpleNamespace(
            im=SimpleNamespace(
                v1=SimpleNamespace(
                    message=SimpleNamespace(reply=patch)
                )
            )
        )
        fake_client.im.v1.message.reply = lambda request: fake_response

        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=fake_client):
            listener = FeishuListener()
            listener._api_client = fake_client
            reply_ids = listener._send_case_reply("msg_1", "ou_1", "张三", "ok")

        self.assertEqual(reply_ids["message_id"], "bot_msg_1")
        self.assertEqual(reply_ids["root_id"], "root_1")

    def test_process_case_and_reply_uses_orchestrator_run_result(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        run_result = SimpleNamespace(
            reply_text="ok",
            route="network",
            target="192.168.1.250",
            time_key="",
            conversation_key="chat_1:root_1",
            step_index=0,
            reply_kind="progress",
            domain="network",
            sop_path="knowledge/common-faults.md",
            draft_result=SimpleNamespace(draft_path="knowledge/_ai_drafts/network_case.md"),
        )

        with patch.object(listener._orchestrator, "run", return_value=run_result) as mocked_run, \
            patch.object(listener, "_store_run_result_state") as mocked_store, \
            patch.object(listener, "_send_case_reply", return_value={"message_id": "", "root_id": "", "parent_id": "", "thread_id": ""}) as mocked_reply, \
            patch.object(listener, "_register_reply_anchor") as mocked_anchor, \
            patch.object(listener, "_mark_case_processed") as mocked_mark:
            listener._process_case_and_reply(
                text="网络连不上 192.168.1.250",
                payload={"event": {"message": {"message_id": "msg_1"}}},
                sender_open_id="ou_1",
                sender_display_name="张三",
                message_id="msg_1",
                event_id="evt_1",
                conversation_key="chat_1:root_1",
                chat_id="chat_1",
            )

        mocked_run.assert_called_once()
        mocked_store.assert_called_once()
        mocked_reply.assert_called_once()
        mocked_anchor.assert_called_once()
        mocked_mark.assert_called_once()

    def test_register_reply_anchor_skips_empty_reply_message(self) -> None:
        with patch("feishu_agent.core.feishu_listener.ws_agent.get_api_client", return_value=object()):
            listener = FeishuListener()

        with patch("feishu_agent.core.feishu_listener.ws_agent.conversation_router.register_thread_message_anchor") as mocked_register:
            listener._register_reply_anchor(
                conversation_key="chat_1:root_1",
                chat_id="chat_1",
                sender_open_id="ou_1",
                reply_ids={"message_id": "", "root_id": "", "parent_id": "", "thread_id": ""},
            )

        mocked_register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
