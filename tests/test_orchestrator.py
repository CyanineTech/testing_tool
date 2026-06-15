import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_agent.core.orchestrator import CaseRequest, Orchestrator
from feishu_agent.core.router import extract_case_context
from feishu_agent.protocols.actions import ACTION_READ_KNOWLEDGE, ACTION_REPORT, ACTION_SECURE_SSH_EXECUTE, build_action_event
from feishu_agent.core.session import SessionState, SessionStore
from feishu_agent.diagnostics import extract_time_key
from feishu_agent.knowledge.index import select_relevant_docs
from feishu_agent.knowledge.loader import load_knowledge_excerpt
from feishu_agent.providers.base import build_interactive_protocol_prompt
from feishu_agent.providers.base import ProviderResult
from feishu_agent.output.formatter import format_case_report


def _build_payload(text: str, chat_id: str = "chat_1", root_id: str = "root_1"):
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


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="orchestrator_state_")
        self._original_state_file = os.environ.get("FEISHU_SESSION_STATE_FILE")
        os.environ["FEISHU_SESSION_STATE_FILE"] = os.path.join(self._temp_dir.name, "feishu_session_state.json")
        self.orchestrator = Orchestrator()

    def tearDown(self) -> None:
        if self._original_state_file is None:
            os.environ.pop("FEISHU_SESSION_STATE_FILE", None)
        else:
            os.environ["FEISHU_SESSION_STATE_FILE"] = self._original_state_file
        self._temp_dir.cleanup()

    def test_extract_time_key_supports_chinese_month_day(self) -> None:
        self.assertEqual(extract_time_key("看下 6月7日 掉线的是哪个雷达"), "2026_06_07")

    def test_extract_time_key_supports_full_timestamp(self) -> None:
        text = "看一下这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"
        self.assertEqual(extract_time_key(text), "2026_06_11")

    def test_service_history_question_keeps_time_but_not_ros_target(self) -> None:
        text = "看一下这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"

        context = extract_case_context(text, _build_payload(text), sender_open_id="ou_123")

        self.assertEqual(context.route, "amr")
        self.assertEqual(context.target, "")
        self.assertEqual(context.time_key, "2026_06_11")
        self.assertIn("target", context.missing_fields)

    def test_host_service_history_question_routes_to_rcs_and_keeps_time(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"

        context = extract_case_context(text, _build_payload(text), sender_open_id="ou_123")

        self.assertEqual(context.route, "rcs")
        self.assertEqual(context.target, "leefung-s1")
        self.assertEqual(context.time_key, "2026_06_11")

    def test_service_history_question_prompts_for_target_instead_of_answering_blindly(self) -> None:
        text = "看一下这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败"
        request = CaseRequest(
            text=text,
            payload=_build_payload(text, chat_id="chat_history_missing_target", root_id="root_history_missing_target"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_history_service",
        )

        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.reply_kind, "clarification")
        self.assertEqual(response.route, "amr")
        self.assertIn("请补充设备/IP 或主机名", response.reply_text)

    def test_amr_missing_target_prompts_clarification(self) -> None:
        request = CaseRequest(
            text="AMR 叉货有问题",
            payload=_build_payload("AMR 叉货有问题"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_1",
        )

        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.reply_kind, "clarification")
        self.assertEqual(response.route, "amr")
        self.assertIn("请补充设备/IP 或主机名", response.reply_text)

    def test_network_follow_up_advances_step(self) -> None:
        first_request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_2",
        )
        first_response = self.orchestrator.handle_case(first_request)

        second_request = CaseRequest(
            text="继续",
            payload=_build_payload("继续"),
            sender_open_id="ou_456",
            sender_display_name="李四",
            message_id="msg_3",
        )
        second_response = self.orchestrator.handle_case(second_request)

        self.assertEqual(first_response.route, "network")
        self.assertEqual(first_response.reply_kind, "progress")
        self.assertEqual(second_response.route, "network")
        self.assertEqual(second_response.step_index, 1)

    def test_same_text_different_roots_do_not_share_progress(self) -> None:
        first_request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", root_id="root_a"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_a",
        )
        first_response = self.orchestrator.handle_case(first_request)

        second_request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", root_id="root_b"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_b",
        )
        second_response = self.orchestrator.handle_case(second_request)

        self.assertEqual(first_response.step_index, 0)
        self.assertEqual(second_response.step_index, 0)
        self.assertIn("网络问题", first_response.reply_text)
        self.assertIn("网络问题", second_response.reply_text)

    def test_rcs_route_is_recognized(self) -> None:
        request = CaseRequest(
            text="RCS 主机调度异常",
            payload=_build_payload("RCS 主机调度异常"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_4",
        )

        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.route, "rcs")
        self.assertEqual(response.reply_kind, "progress")
        self.assertIn("RCS 主机问题", response.reply_text)

    def test_provider_result_can_override_final_root_cause(self) -> None:
        request = CaseRequest(
            text="RCS 后端接口超时",
            payload=_build_payload("RCS 后端接口超时"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_5",
        )

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_ENABLE_LOCAL_DIAG": "1"}, clear=False), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", return_value=ProviderResult(
                provider_name="copilotcli",
                summary="发现调度链路阻塞",
                next_steps=("检查队列",),
                root_cause="调度中心队列阻塞",
                severity="错误",
                evidence=("队列长度持续上升",),
                confidence="high",
                raw_output='{"summary":"发现调度链路阻塞"}',
            )):
            response = self.orchestrator.handle_case(request)

        self.assertIn("调度中心队列阻塞", response.reply_text)
        self.assertIn("错误", response.reply_text)

    def test_time_scoped_amr_case_runs_local_diag_and_ai_review(self) -> None:
        request = CaseRequest(
            text="看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的",
            payload=_build_payload("看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的", chat_id="chat_hist", root_id="root_hist"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            "severity": "错误",
            "root_cause": "前雷达节点在 2026_06_07 相关日志中多次掉线",
            "evidence": "LaserScan front 掉线\nusb reset",
            "text": request.text,
        }

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="结合本地日志与知识库，当前更像前雷达历史掉线，但仍需 caution/bag 进一步核对。",
                next_steps=("下载 caution 包核对 front/rear_scan",),
                root_cause="前雷达节点在 2026_06_07 相关日志中多次掉线",
                severity="错误",
                evidence=("LaserScan front 掉线",),
                confidence="high",
            )

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            response = self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        self.assertIn("local_diag_summary:", "\n".join(captured_request.evidence))
        self.assertIn("local_diag_executed:", "\n".join(captured_request.evidence))
        self.assertIn("前雷达节点在 2026_06_07 相关日志中多次掉线", response.reply_text)
        self.assertIn("LaserScan front 掉线", response.reply_text)
        self.assertIn("结合本地日志与知识库", response.reply_text)
        self.assertNotIn("provider：", response.reply_text)
        self.assertEqual(response.time_key, "2026_06_07")

    def test_time_scoped_amr_keeps_local_insufficient_evidence_conclusion_when_ai_confidence_is_medium(self) -> None:
        request = CaseRequest(
            text="看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的",
            payload=_build_payload("看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的", chat_id="chat_hist2", root_id="root_hist2"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist2",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_07 对应的 ROS 原始日志，现有文本证据不足，无法判定具体前/后雷达和直接原因",
            "evidence": "caution_T9_20260607_154805.bag.zip",
            "text": request.text,
        }

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(
                self.orchestrator.provider_manager,
                "run_review",
                return_value=ProviderResult(
                    provider_name="copilotcli",
                    summary="AI 认为可能与前向扫描异常相关，但现有证据不充分。",
                    next_steps=("下载 caution 包进一步核对",),
                    root_cause="可能是前雷达异常",
                    severity="警告",
                    evidence=("仅有 caution 包名",),
                    confidence="medium",
                ),
            ):
            response = self.orchestrator.handle_case(request)

        self.assertIn("未找到 2026_06_07 对应的 ROS 原始日志", response.reply_text)
        self.assertIn("AI 认为可能与前向扫描异常相关", response.reply_text)
        self.assertNotIn("provider：", response.reply_text)

    def test_auto_diag_hides_low_confidence_provider_timeout_fallback(self) -> None:
        request = CaseRequest(
            text="看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的",
            payload=_build_payload("看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的", chat_id="chat_hist3", root_id="root_hist3"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist3",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_07 对应的 ROS 原始日志；当前只能确认同日存在 5 份 caution 录包，无法仅凭现有文本证据判定具体前/后雷达和直接原因",
            "evidence": "caution_T9_20260607_154805.bag.zip",
            "text": request.text,
        }

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(
                self.orchestrator.provider_manager,
                "run_review",
                return_value=ProviderResult(
                    provider_name="copilotcli",
                    summary="copilotcli 超时后已终止。",
                    next_steps=(),
                    root_cause="",
                    severity="",
                    evidence=(
                        "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy. Only built-in servers are available.",
                    ),
                    confidence="low",
                ),
            ):
            response = self.orchestrator.handle_case(request)

        self.assertIn("未找到 2026_06_07 对应的 ROS 原始日志", response.reply_text)
        self.assertNotIn("copilotcli 超时后已终止", response.reply_text)
        self.assertNotIn("**模型复核**", response.reply_text)
        self.assertNotIn("policy_warning", response.reply_text)

    def test_auto_diag_hides_low_confidence_unparseable_provider_summary(self) -> None:
        request = CaseRequest(
            text="看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的",
            payload=_build_payload("看下从机leefung-t9在6月7日掉线的是哪个雷达，什么原因导致的", chat_id="chat_hist4", root_id="root_hist4"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist4",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_07 对应的 ROS 原始日志；当前只能确认同日存在 5 份 caution 录包，无法仅凭现有文本证据判定具体前/后雷达和直接原因",
            "evidence": "caution_T9_20260607_154805.bag.zip",
            "text": request.text,
        }

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(
                self.orchestrator.provider_manager,
                "run_review",
                return_value=ProviderResult(
                    provider_name="copilotcli",
                    summary="copilotcli 未返回可解析诊断结果。",
                    next_steps=(),
                    root_cause="",
                    severity="",
                    evidence=(
                        "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy. Only built-in servers are available.",
                    ),
                    confidence="low",
                ),
            ):
            response = self.orchestrator.handle_case(request)

        self.assertIn("未找到 2026_06_07 对应的 ROS 原始日志", response.reply_text)
        self.assertNotIn("copilotcli 未返回可解析诊断结果", response.reply_text)
        self.assertNotIn("policy_warning", response.reply_text)

    def test_brief_follow_up_uses_compact_provider_prompt(self) -> None:
        conversation_key = "chat_follow:root_follow"
        self.orchestrator.session_store.update(
            conversation_key,
            route="amr",
            target="leefung-t9",
            time_key="",
            step_index=0,
            evidence=[f"evidence_{index}" for index in range(6)],
            last_doc_candidates=["knowledge/common-faults.md", "knowledge/error-codes.md"],
            last_read_docs=["knowledge/error-tracing-methods.md"],
            last_report="已收到：AMR 机器人问题\n摘要：copilotcli 超时后已终止。",
            last_reply_kind="progress",
            last_payload=_build_payload("看下从机 leefung-t9 当前状态", chat_id="chat_follow", root_id="root_follow"),
        )

        request = CaseRequest(
            text="继续",
            payload=_build_payload("继续", chat_id="chat_follow", root_id="root_follow"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_follow",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="继续检查 USB 和 CAN 状态",
                next_steps=("检查 can0",),
                root_cause="仍需更多实时证据",
                severity="信息",
                evidence=("依据当前步骤建议先看 USB/CAN",),
                confidence="medium",
            )

        with patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            response = self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        self.assertEqual(response.step_index, 1)
        self.assertIn("当前步骤：2.", captured_request.question)
        self.assertNotIn("上一轮回复", captured_request.context)
        self.assertNotIn("超时后已终止", captured_request.context)
        self.assertIn("已读取文档：knowledge/error-tracing-methods.md", captured_request.context)
        self.assertNotIn("knowledge/common-faults.md", captured_request.context)
        self.assertLessEqual(len(captured_request.evidence), 4)

    def test_quota_follow_up_forces_local_diag_instead_of_provider_retry(self) -> None:
        conversation_key = "chat_quota:root_quota"
        self.orchestrator.session_store.update(
            conversation_key,
            route="rcs",
            target="leefung-s1",
            time_key="2026_06_11",
            step_index=0,
            evidence=["copilot_quota_exhausted"],
            last_doc_candidates=["knowledge/task_dispatch/rcs-task-system.md"],
            last_read_docs=["knowledge/task_dispatch/rcs-task-system.md"],
            last_report="已收到：RCS 系统问题\n摘要：当前 Copilot 月度额度已用尽，模型复核暂时不可用。",
            last_reply_kind="progress",
            last_payload=_build_payload("看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 失败", chat_id="chat_quota", root_id="root_quota"),
        )

        request = CaseRequest(
            text="继续",
            payload=_build_payload("继续", chat_id="chat_quota", root_id="root_quota"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_quota_follow",
        )

        diag_report = {
            "need_more_info": False,
            "route": "rcs",
            "target": "leefung-s1",
            "executed": [{"command": "bash scripts/check_rcs_status.sh leefung-s1", "returncode": 0}],
            "severity": "警告",
            "root_cause": "RCS 侧存在服务异常或端口不可用",
            "evidence": "port 8079 closed",
            "text": request.text,
        }

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review") as mocked_review:
            response = self.orchestrator.handle_case(request)

        mocked_review.assert_not_called()
        self.assertEqual(response.route, "rcs")
        self.assertEqual(response.step_index, 1)
        self.assertIn("RCS 侧存在服务异常或端口不可用", response.reply_text)
        self.assertIn("bash scripts/check_rcs_status.sh leefung-s1", response.reply_text)

    def test_orchestrator_uses_topk_relevant_docs(self) -> None:
        request = CaseRequest(
            text="AMR CAN 通信异常，雷达和底层总线是否异常",
            payload=_build_payload("AMR CAN 通信异常，雷达和底层总线是否异常"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_topk",
        )

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_TOPK_DOCS": "3"}, clear=False):
            response = self.orchestrator.handle_case(request)

        session = self.orchestrator.session_store.get(response.conversation_key)
        self.assertLessEqual(len(session.last_doc_candidates), 3)
        self.assertEqual(session.last_read_docs, [])
        self.assertTrue(any("error-codes" in path or "can" in path for path in session.last_doc_candidates))

    def test_provider_knowledge_reads_are_tracked_separately(self) -> None:
        request = CaseRequest(
            text="AMR leefung-t9 can 通信异常",
            payload=_build_payload("AMR leefung-t9 can 通信异常", chat_id="chat_read", root_id="root_read"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_read",
        )

        with patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", return_value=ProviderResult(
                provider_name="copilotcli",
                summary="依据知识库继续判断",
                next_steps=("继续检查 CAN",),
                root_cause="底层链路抖动",
                severity="警告",
                evidence=("knowledge_read[knowledge/error-codes.md]: CAN 错误码说明",),
                confidence="medium",
            )):
            response = self.orchestrator.handle_case(request)

        session = self.orchestrator.session_store.get(response.conversation_key)
        self.assertTrue(session.last_doc_candidates)
        self.assertEqual(session.last_read_docs, ["knowledge/error-codes.md"])

    def test_provider_action_events_are_reflected_in_evidence_and_read_docs(self) -> None:
        request = CaseRequest(
            text="AMR leefung-t9 can 通信异常",
            payload=_build_payload("AMR leefung-t9 can 通信异常", chat_id="chat_actions", root_id="root_actions"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_actions",
        )

        with patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(
                self.orchestrator.provider_manager,
                "run_review",
                return_value=ProviderResult(
                    provider_name="copilotcli",
                    summary="依据知识与执行结果继续判断",
                    next_steps=("继续检查 CAN",),
                    root_cause="底层链路抖动",
                    severity="警告",
                    evidence=(),
                    action_events=(
                        build_action_event(
                            action_type=ACTION_READ_KNOWLEDGE,
                            source="copilotcli",
                            payload={"path": "knowledge/error-codes.md", "excerpt": "CAN 错误码说明"},
                        ),
                        build_action_event(
                            action_type=ACTION_SECURE_SSH_EXECUTE,
                            source="copilotcli",
                            payload={"command": "ip -details link show can0", "stdout": "state UP", "stderr": "", "returncode": 0},
                        ),
                        build_action_event(
                            action_type=ACTION_REPORT,
                            source="copilotcli",
                            payload={"summary": "依据知识与执行结果继续判断"},
                        ),
                    ),
                    confidence="medium",
                ),
            ):
            response = self.orchestrator.handle_case(request)

        session = self.orchestrator.session_store.get(response.conversation_key)
        self.assertEqual(session.last_read_docs, ["knowledge/error-codes.md"])
        self.assertTrue(any(item.startswith("knowledge_read[knowledge/error-codes.md]") for item in session.evidence))
        self.assertTrue(any(item.startswith("provider_execute[ip -details link show can0]") for item in session.evidence))
        self.assertTrue(any(item.startswith("provider_report: 依据知识与执行结果继续判断") for item in session.evidence))
        self.assertIsNotNone(response.report_result)
        self.assertTrue(response.trace)
        self.assertTrue(any(item["type"] == "provider_action" for item in response.trace))

    def test_progress_response_includes_structured_report_and_trace(self) -> None:
        request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", chat_id="chat_trace", root_id="root_trace"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_trace",
        )

        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.reply_kind, "progress")
        self.assertIsNotNone(response.report_result)
        self.assertEqual(response.report_result.root_cause, "当前基于知识库与上下文进行排障")
        self.assertTrue(response.trace)
        self.assertTrue(any(item["type"] == "knowledge_candidates" for item in response.trace))

    def test_run_returns_standard_result_with_messages_trace_and_sop(self) -> None:
        request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", chat_id="chat_run", root_id="root_run"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_run",
        )

        result = self.orchestrator.run(request)

        self.assertEqual(result.domain, "network")
        self.assertTrue(result.sop_path.startswith("knowledge/"))
        self.assertEqual(result.final_answer, result.reply_text)
        self.assertGreaterEqual(len(result.messages), 3)
        self.assertEqual(result.messages[0]["role"], "system")
        self.assertEqual(result.messages[1]["role"], "user")
        self.assertEqual(result.messages[2]["role"], "assistant")
        self.assertTrue(result.trace)
        self.assertTrue(all(hasattr(item, "timestamp") for item in result.trace))
        self.assertTrue(all(hasattr(item, "success") for item in result.trace))
        self.assertTrue(any(item.type == "knowledge_candidates" for item in result.trace))
        self.assertIsNotNone(result.draft_result)
        self.assertTrue(result.draft_result.draft_path.endswith(".md"))

    def test_handle_case_is_compat_wrapper_over_run_result(self) -> None:
        request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", chat_id="chat_handle", root_id="root_handle"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_handle",
        )

        run_result = self.orchestrator.run(request)
        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.reply_text, run_result.final_answer)
        self.assertEqual(response.route, run_result.route)
        self.assertEqual(response.target, run_result.target)
        self.assertEqual(response.time_key, run_result.time_key)
        self.assertEqual(response.conversation_key, run_result.conversation_key)
        self.assertEqual(response.step_index, run_result.step_index)
        self.assertEqual(response.reply_kind, run_result.reply_kind)
        self.assertEqual(response.report_result, run_result.report_result)
        self.assertTrue(response.trace)
        self.assertTrue(any(item["type"] == "knowledge_candidates" for item in response.trace))

    def test_case_response_from_run_result_is_compat_only_projection(self) -> None:
        request = CaseRequest(
            text="网络连不上 192.168.1.250",
            payload=_build_payload("网络连不上 192.168.1.250", chat_id="chat_projection", root_id="root_projection"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_projection",
        )

        run_result = self.orchestrator.run(request)
        response = self.orchestrator.handle_case(request)

        self.assertEqual(response.reply_text, run_result.final_answer)
        self.assertEqual(response.report_result, run_result.report_result)
        self.assertEqual(len(response.trace), len(run_result.trace))
        self.assertTrue(all(isinstance(item, dict) for item in response.trace))

    def test_provider_context_and_doc_evidence_avoid_command_heavy_injection(self) -> None:
        request = CaseRequest(
            text="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常",
            payload=_build_payload("看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常", chat_id="chat_cmd", root_id="root_cmd"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_cmd",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="继续检查底层状态",
                next_steps=("确认错误码",),
                root_cause="待补充实时证据",
                severity="信息",
                evidence=(),
                confidence="medium",
            )

        with patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        self.assertNotIn("首查命令", captured_request.context)
        combined_evidence = "\n".join(str(item) for item in captured_request.evidence)
        self.assertNotIn("bash scripts/check_amr_status.sh", combined_evidence)
        self.assertNotIn("docker ps", combined_evidence)

    def test_pty_route_uses_compact_provider_context_and_evidence(self) -> None:
        request = CaseRequest(
            text="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常",
            payload=_build_payload("看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常", chat_id="chat_pty", root_id="root_pty"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_pty",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="继续检查底层状态",
                next_steps=("确认错误码",),
                root_cause="待补充实时证据",
                severity="信息",
                evidence=(),
                confidence="medium",
            )

        with patch.dict(
            "feishu_agent.core.orchestrator.os.environ",
            {
                "COPILOTCLI_ENABLE_PTY_PROTOCOL": "1",
                "COPILOTCLI_PTY_ROUTES": "amr",
                "FEISHU_PTY_PROVIDER_EVIDENCE_COUNT": "2",
            },
            clear=False,
        ), patch(
            "feishu_agent.core.orchestrator.collect_evidence",
            return_value={
                "results": [
                    type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "command timed out after 8s\n"})(),
                    type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/motor_control", "stderr": ""})(),
                ]
            },
        ), patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        self.assertIn("目标：leefung-t9", captured_request.context)
        self.assertIn("当前步骤：1.", captured_request.context)
        self.assertNotIn("后续步骤", captured_request.context)
        self.assertNotIn("候选文档", captured_request.context)
        self.assertLessEqual(len(captured_request.evidence), 3)
        combined_evidence = "\n".join(str(item) for item in captured_request.evidence)
        self.assertIn("/low_level_error 命令已超时结束，当前未读到单条错误消息", combined_evidence)
        self.assertIn("rosnode list 成功，检测到 2 个节点", combined_evidence)

    def test_pty_amr_route_prefetches_explicit_remote_evidence(self) -> None:
        request = CaseRequest(
            text="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常",
            payload=_build_payload("看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常", chat_id="chat_prefetch", root_id="root_prefetch"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_prefetch",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="已根据远端证据继续分析",
                next_steps=("确认错误码",),
                root_cause="待结合远端状态判断",
                severity="信息",
                evidence=(),
                confidence="medium",
            )

        class _Result:
            def __init__(self, command: str, stdout: str, stderr: str = "", returncode: int = 0) -> None:
                self.command = command
                self.stdout = stdout
                self.stderr = stderr
                self.returncode = returncode

        with patch.dict(
            "feishu_agent.core.orchestrator.os.environ",
            {
                "COPILOTCLI_ENABLE_PTY_PROTOCOL": "1",
                "COPILOTCLI_PTY_ROUTES": "amr",
            },
            clear=False,
        ), patch(
            "feishu_agent.core.orchestrator.collect_evidence",
            return_value={
                "results": [
                    _Result("rostopic echo /low_level_error -n1", "error_code=2001001"),
                    _Result("rosnode list", "/rosout\n/motor_control"),
                ]
            },
        ) as mocked_collect, patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            self.orchestrator.handle_case(request)

        self.assertTrue(mocked_collect.called)
        self.assertIsNotNone(captured_request)
        combined_evidence = "\n".join(str(item) for item in captured_request.evidence)
        self.assertIn("remote[rostopic echo /low_level_error -n1]: /low_level_error 已读到实时消息: error_code=2001001", combined_evidence)
        self.assertIn("remote[rosnode list]: rosnode list 成功，检测到 2 个节点；示例: /rosout, /motor_control", combined_evidence)

    def test_pty_amr_route_formats_unpublished_low_level_error_topic(self) -> None:
        request = CaseRequest(
            text="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            payload=_build_payload("看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态", chat_id="chat_prefetch_warn", root_id="root_prefetch_warn"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_prefetch_warn",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="已根据远端证据继续分析",
                next_steps=("确认错误码",),
                root_cause="待结合远端状态判断",
                severity="信息",
                evidence=(),
                confidence="medium",
            )

        class _Result:
            def __init__(self, command: str, stdout: str, stderr: str = "", returncode: int = 0) -> None:
                self.command = command
                self.stdout = stdout
                self.stderr = stderr
                self.returncode = returncode

        with patch.dict(
            "feishu_agent.core.orchestrator.os.environ",
            {
                "COPILOTCLI_ENABLE_PTY_PROTOCOL": "1",
                "COPILOTCLI_PTY_ROUTES": "amr",
            },
            clear=False,
        ), patch(
            "feishu_agent.core.orchestrator.collect_evidence",
            return_value={
                "results": [
                    _Result(
                        "rostopic echo /low_level_error -n1",
                        "",
                        stderr="WARNING: topic [/low_level_error] does not appear to be published yet\ncommand timed out after 8s\n",
                        returncode=124,
                    ),
                    _Result("rosnode list", "/rosout\n/motor_control"),
                ]
            },
        ), patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        combined_evidence = "\n".join(str(item) for item in captured_request.evidence)
        self.assertIn("/low_level_error 当前未发布，暂未读到实时错误消息", combined_evidence)
        self.assertNotIn("Connection timed out", combined_evidence)


class KnowledgeProtocolTests(unittest.TestCase):
    def test_interactive_prompt_mentions_read_knowledge(self) -> None:
        prompt = build_interactive_protocol_prompt(
            provider_request := type("Request", (), {
                "route": "amr",
                "question": "看下 CAN 异常",
                "context": "已收到：AMR 机器人问题",
                "evidence": ["doc_excerpt[knowledge/common-faults.md]: ..."],
                "target": "leefung-t9",
            })()
        )

        self.assertIn("read_knowledge", prompt)
        self.assertIn("knowledge/*.md", prompt)
        self.assertIn("execute", prompt)

    def test_load_knowledge_excerpt_rejects_non_knowledge_paths(self) -> None:
        excerpt, error = load_knowledge_excerpt("README.md")

        self.assertEqual(excerpt, "")
        self.assertIn("knowledge/", error)

    def test_select_relevant_docs_prefers_route_and_keyword_matches(self) -> None:
        docs = select_relevant_docs("CAN EB 通信异常", "amr", limit=3)

        self.assertLessEqual(len(docs), 3)
        self.assertTrue(any("error-codes" in path or "can" in path for path in docs))

    def test_select_relevant_docs_matches_usb_symptoms(self) -> None:
        docs = select_relevant_docs("摄像头离线并伴随 uvcvideo 和 pcan 重连", "amr", limit=4)

        self.assertIn("knowledge/hardware_bus/usb-device-troubleshooting.md", docs)

    def test_select_relevant_docs_matches_call_chain_monitoring(self) -> None:
        docs = select_relevant_docs("RCS 调用链监控 grpc redis topic ecbs", "rcs", limit=4)

        self.assertIn("knowledge/backend/python-ros-call-chain-monitoring.md", docs)

    def test_select_relevant_docs_can_pick_new_doc_from_directory_readme_without_code_rule(self) -> None:
        with tempfile.TemporaryDirectory(prefix="knowledge_route_") as tmpdir:
            repo_root = Path(tmpdir)
            knowledge_root = repo_root / "knowledge"
            network_root = knowledge_root / "network"
            network_root.mkdir(parents=True, exist_ok=True)
            (knowledge_root / "common-faults.md").write_text("# Common Faults\n", encoding="utf-8")
            (knowledge_root / "system-architecture.md").write_text("# Architecture\n", encoding="utf-8")
            (knowledge_root / "log-paths.md").write_text("# Logs\n", encoding="utf-8")
            (network_root / "README.md").write_text(
                "# 网络与连通性入口\n\n- [wifi-roaming-instability.md](wifi-roaming-instability.md)\n",
                encoding="utf-8",
            )
            (network_root / "wifi-roaming-instability.md").write_text(
                "# WiFi 漫游不稳定\n\n## 典型现象\n- WiFi 漫游后频繁掉线\n",
                encoding="utf-8",
            )
            with patch("feishu_agent.knowledge.index._knowledge_root", return_value=knowledge_root):
                docs = select_relevant_docs("WiFi 漫游后频繁掉线", "network", limit=6)

        self.assertIn("knowledge/network/wifi-roaming-instability.md", docs)


class FormatterTests(unittest.TestCase):
    def test_final_report_distinguishes_candidate_and_read_docs(self) -> None:
        report = format_case_report(
            route="amr",
            target="192.168.1.250",
            severity="错误",
            root_cause="CAN 链路异常",
            executed=[],
            evidence=["knowledge_candidates: knowledge/common-faults.md, knowledge/error-codes.md"],
            docs=["knowledge/common-faults.md", "knowledge/error-codes.md"],
            read_docs=["knowledge/error-codes.md"],
        )

        self.assertNotIn("**候选文档**：", report)
        self.assertNotIn("**已读取文档**：", report)

    def test_case_report_contains_required_sections(self) -> None:
        report = format_case_report(
            route="amr",
            target="192.168.1.250",
            severity="错误",
            root_cause="CAN 链路异常",
            executed=[{"command": "rostopic echo /low_level_error -n1", "returncode": 0}],
            evidence=["CAN bus停止发布数据"],
            docs=["knowledge/common-faults.md"],
            provider_summary="建议继续检查底层链路",
            provider_name="copilotcli",
            provider_confidence="medium",
            provider_root_cause="底层链路抖动",
            provider_severity="错误",
            provider_next_steps=["检查 CAN 总线", "复核电机供电"],
            provider_evidence=["模型提示 CAN 侧异常"],
        )

        self.assertIn("**故障类别**：amr", report)
        self.assertIn("**目标**：192.168.1.250", report)
        self.assertIn("**严重程度**：错误", report)
        self.assertIn("**根因分析**：CAN 链路异常", report)
        self.assertIn("rostopic echo /low_level_error -n1", report)
        self.assertIn("CAN bus停止发布数据", report)
        self.assertIn("建议继续检查底层链路", report)
        self.assertIn("**补充判断**：", report)
        self.assertIn("补充证据", report)
        self.assertIn("检查 CAN 总线", report)
        self.assertNotIn("provider：", report)
        self.assertNotIn("confidence：", report)
        self.assertNotIn("root_cause：", report)
        self.assertNotIn("**候选文档**：", report)
        self.assertNotIn("**已读取文档**：", report)

    def test_case_report_hides_internal_evidence_markers(self) -> None:
        report = format_case_report(
            route="amr",
            target="leefung-t9",
            severity="警告",
            root_cause="现有文本证据不足，无法判定具体前/后雷达",
            executed=[{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            evidence=[
                "local_diag_summary: severity=警告; root_cause=证据不足",
                "local_diag_executed: bash scripts/collect_logs.sh leefung-t9 2026_06_07 (rc=0)",
                "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy.",
                "knowledge_candidates: knowledge/common-faults.md, knowledge/error-tracing-methods.md",
                "doc_excerpt[knowledge/common-faults.md]: # 常见故障排查指南",
                "knowledge_read[knowledge/error-tracing-methods.md]: # 机器常见错误追溯方法",
                "/home/robot/autobag/caution_T9_20260607_154805.bag.zip",
            ],
            docs=["knowledge/error-tracing-methods.md"],
            provider_summary="仍需结合 caution 包进一步核对。",
            provider_name="copilotcli",
            provider_confidence="medium",
            provider_root_cause="证据链不完整",
            provider_evidence=[
                "knowledge_read[knowledge/error-tracing-methods.md]: # 机器常见错误追溯方法",
                "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy.",
                "同日存在 5 份 caution 录包",
            ],
        )

        self.assertNotIn("local_diag_summary:", report)
        self.assertNotIn("local_diag_executed:", report)
        self.assertNotIn("policy_warning:", report)
        self.assertNotIn("knowledge_candidates:", report)
        self.assertNotIn("doc_excerpt[", report)
        self.assertNotIn("knowledge_read[", report)
        self.assertNotIn("provider：", report)
        self.assertNotIn("confidence：", report)
        self.assertNotIn("root_cause：", report)
        self.assertNotIn("**候选文档**：", report)
        self.assertNotIn("**已读取文档**：", report)
        self.assertIn("caution_T9_20260607_154805.bag.zip", report)
        self.assertIn("同日存在 5 份 caution 录包", report)

    def test_case_report_normalizes_mapping_like_evidence_lines(self) -> None:
        report = format_case_report(
            route="amr",
            target="leefung-t9",
            severity="警告",
            root_cause="现有文本证据不足",
            executed=[{"command": "bash scripts/collect_logs.sh leefung-t9 2026_06_07", "returncode": 0}],
            evidence=["/home/robot/autobag/caution_T9_20260607_154805.bag.zip"],
            docs=["knowledge/error-tracing-methods.md"],
            provider_summary="仍需继续核对日志。",
            provider_evidence=[
                "{'type': 'local_diag_executed', 'content': 'bash scripts/collect_logs.sh leefung-t9 2026_06_07 (rc=0)'}",
                "{'type': 'knowledge_reference', 'content': 'knowledge/error-tracing-methods.md: default.launch 经常可以直接看到谁的信号没了。'}",
            ],
        )

        self.assertIn("本地诊断执行：bash scripts/collect_logs.sh leefung-t9 2026_06_07 (rc=0)", report)
        self.assertIn("知识参考：knowledge/error-tracing-methods.md: default.launch 经常可以直接看到谁的信号没了。", report)
        self.assertNotIn("{'type':", report)


class SessionStoreTests(unittest.TestCase):
    def test_get_reload_latest_state_from_disk(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session_store_") as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            with patch.dict("os.environ", {"FEISHU_SESSION_STATE_FILE": state_file}, clear=False):
                store_a = SessionStore()
                store_b = SessionStore()

                store_a.update("chat_thread:root", route="rcs", target="leefung-s1", step_index=0)

                reloaded = store_b.get("chat_thread:root")

        self.assertEqual(reloaded.route, "rcs")
        self.assertEqual(reloaded.target, "leefung-s1")
        self.assertEqual(reloaded.step_index, 0)

    def test_prune_expired_removes_old_session(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session_store_") as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            with patch.dict("os.environ", {"FEISHU_SESSION_STATE_FILE": state_file}, clear=False):
                store = SessionStore()
                store.update("chat_1:root_1", route="amr")
                store._sessions["chat_1:root_1"].last_active_at = 1.0

                store.prune_expired(3600, now=3600 + 10)

                self.assertEqual(store.get("chat_1:root_1").route, "")


if __name__ == "__main__":
    unittest.main()
