import unittest

from feishu_agent.app import classify_text
from feishu_agent.core.orchestrator import CaseRequest, Orchestrator


def build_payload(text: str, chat_id: str = "chat_1", root_id: str = "root_1"):
    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "root_id": root_id,
                "message_id": f"msg_{chat_id}_{root_id}",
                "content": {"text": text},
            }
        }
    }


class MessageFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = Orchestrator()

    def test_amr_flow(self) -> None:
        response = self.orchestrator.handle_case(
            CaseRequest(
                text="AMR 取货时无法叉货到位 192.168.1.10",
                payload=build_payload("AMR 取货时无法叉货到位 192.168.1.10", "chat_a", "root_a"),
                sender_open_id="ou_123",
                sender_display_name="张三",
                message_id="msg_a",
            )
        )
        self.assertEqual(response.route, "amr")
        self.assertIn("AMR 机器人问题", response.reply_text)
        self.assertIn("首查命令", response.reply_text)
        self.assertIn("候选文档", response.reply_text)

    def test_network_flow(self) -> None:
        response = self.orchestrator.handle_case(
            CaseRequest(
                text="网络连不上 192.168.1.250",
                payload=build_payload("网络连不上 192.168.1.250", "chat_b", "root_b"),
                sender_open_id="ou_123",
                sender_display_name="张三",
                message_id="msg_b",
            )
        )
        self.assertEqual(response.route, "network")
        self.assertIn("网络问题", response.reply_text)

    def test_rcs_flow(self) -> None:
        response = self.orchestrator.handle_case(
            CaseRequest(
                text="RCS 任务不派发",
                payload=build_payload("RCS 任务不派发", "chat_c", "root_c"),
                sender_open_id="ou_123",
                sender_display_name="张三",
                message_id="msg_c",
            )
        )
        self.assertEqual(response.route, "rcs")
        self.assertIn("RCS 主机问题", response.reply_text)

    def test_cpu_high_flow(self) -> None:
        response = self.orchestrator.handle_case(
            CaseRequest(
                text="leefung-t5 CPU占用过高",
                payload=build_payload("leefung-t5 CPU占用过高", "chat_d", "root_d"),
                sender_open_id="ou_123",
                sender_display_name="张三",
                message_id="msg_d",
            )
        )
        self.assertEqual(response.route, "amr")
        self.assertIn("knowledge/cpu-high.md", response.reply_text)

    def test_service_timeout_flow(self) -> None:
        response = self.orchestrator.handle_case(
            CaseRequest(
                text="192.168.1.170 后端接口超时",
                payload=build_payload("192.168.1.170 后端接口超时", "chat_e", "root_e"),
                sender_open_id="ou_123",
                sender_display_name="张三",
                message_id="msg_e",
            )
        )
        self.assertEqual(response.route, "rcs")
        self.assertIn("knowledge/backend/service-timeout.md", response.reply_text)

    def test_host_service_history_classifies_as_rcs(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"

        self.assertEqual(classify_text(text, target="leefung-s1"), "rcs")


if __name__ == "__main__":
    unittest.main()
