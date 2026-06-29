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

    def test_follow_up_keeps_previous_target_and_adds_guardrail(self) -> None:
        conversation_key = "chat_followup_guard:root_followup_guard"
        self.orchestrator.session_store.update(
            conversation_key,
            route="rcs",
            target="192.168.1.170",
            time_key="",
            step_index=1,
            evidence=["local evidence"],
            last_doc_candidates=["knowledge/backend/rcs-backend-service-failure.md"],
            last_read_docs=["knowledge/backend/rcs-backend-service-failure.md"],
            last_report="已收到：RCS 主机问题\n摘要：继续检查中。",
            last_reply_kind="progress",
            last_payload=_build_payload("检查刚刚主机192.168.1.170为什么死机了", chat_id="chat_followup_guard", root_id="root_followup_guard"),
        )

        request = CaseRequest(
            text="继续查 supervisor 为什么没运行，查 MySQL 异常的具体原因",
            payload=_build_payload("继续查 supervisor 为什么没运行，查 MySQL 异常的具体原因", chat_id="chat_followup_guard", root_id="root_followup_guard"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_followup_guard",
        )

        captured_request = None

        def _capture_request(provider_request):
            nonlocal captured_request
            captured_request = provider_request
            return ProviderResult(
                provider_name="copilotcli",
                summary="继续检查 RCS 主机服务链路",
                next_steps=("检查 supervisor",),
                root_cause="服务链路异常",
                severity="错误",
                evidence=("目标保持为 192.168.1.170",),
                confidence="medium",
            )

        with patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", side_effect=_capture_request):
            response = self.orchestrator.handle_case(request)

        self.assertIsNotNone(captured_request)
        self.assertEqual(response.route, "rcs")
        self.assertIn("目标：192.168.1.170", captured_request.context)
        self.assertIn("沿用上一轮目标", captured_request.context)
        self.assertEqual(captured_request.target, "192.168.1.170")

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

    def test_rcs_auto_diag_collects_deeper_evidence_when_mysql_and_supervisor_are_abnormal(self) -> None:
        request = CaseRequest(
            text="主机192.168.1.170当前后端异常，检查原因",
            payload=_build_payload("主机192.168.1.170当前后端异常，检查原因", chat_id="chat_rcs_deep", root_id="root_rcs_deep"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_rcs_deep",
        )

        diag_report = {
            "need_more_info": False,
            "route": "rcs",
            "target": "192.168.1.170",
            "executed": [{"command": "bash scripts/check_rcs_status.sh 192.168.1.170", "returncode": 0}],
            "severity": "错误",
            "root_cause": "RCS 侧存在服务异常或端口不可用",
            "evidence": "Supervisor 未运行\nHTTP状态码: 000\n[FAIL] 后端 API 无响应\n[FAIL] MySQL 异常",
            "text": request.text,
        }

        fake_remote_result = type(
            "FakeSandboxResult",
            (),
            {
                "command": "journalctl -u supervisor -n 80 --no-pager",
                "stdout": "supervisor.service: start request repeated too quickly",
                "stderr": "",
                "returncode": 0,
            },
        )()

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_ENABLE_LOCAL_DIAG": "1"}, clear=False), \
            patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": [fake_remote_result]}) as mocked_collect:
            response = self.orchestrator.handle_case(request)

        mocked_collect.assert_called_once()
        called_commands = mocked_collect.call_args.kwargs["commands"]
        self.assertIn("systemctl status supervisor --no-pager", called_commands)
        self.assertIn("docker logs docker-backend_1 --tail 80", called_commands)
        self.assertIn("docker logs docker-mysql_5_7-1 --tail 80", called_commands)
        self.assertIn("journalctl -k -n 80 --no-pager", called_commands)
        self.assertIn("supervisor 或其托管服务存在频繁拉起失败迹象。", response.reply_text)

    def test_provider_root_cause_with_execute_evidence_overrides_generic_local_root_cause(self) -> None:
        request = CaseRequest(
            text="主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因",
            payload=_build_payload("主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因", chat_id="chat_rcs_provider_override", root_id="root_rcs_provider_override"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_rcs_provider_override",
        )

        diag_report = {
            "need_more_info": False,
            "route": "rcs",
            "target": "192.168.1.170",
            "executed": [{"command": "bash scripts/check_rcs_status.sh 192.168.1.170", "returncode": 0}],
            "severity": "错误",
            "root_cause": "RCS 侧存在服务异常或端口不可用",
            "evidence": "Supervisor 未运行\nHTTP状态码: 000\n[FAIL] 后端 API 无响应",
            "text": request.text,
        }

        provider_result = ProviderResult(
            provider_name="openai_sdk",
            summary="已根据远程取证补齐主机服务状态。",
            next_steps=("检查 3737 端口对应进程",),
            root_cause="RCS 主机后端 API 未监听，当前是主业务服务未拉起或已退出，不是单纯接口慢。",
            severity="错误",
            evidence=("provider_execute[curl -s -S -m 3 http://127.0.0.1:3737/infos/ros/]: curl: (7) Failed to connect",),
            confidence="medium",
        )

        fake_remote_result = type(
            "FakeSandboxResult",
            (),
            {
                "command": "journalctl -u supervisor -n 80 --no-pager",
                "stdout": "supervisor.service: start request repeated too quickly",
                "stderr": "",
                "returncode": 0,
            },
        )()

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_ENABLE_LOCAL_DIAG": "1"}, clear=False), \
            patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": [fake_remote_result]}), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", return_value=provider_result):
            response = self.orchestrator.handle_case(request)

        self.assertIn("后端 API 未监听", response.reply_text)
        self.assertIn("3737 端口", response.reply_text)
        self.assertIn("已根据远程取证补齐主机服务状态。", response.reply_text)

    def test_historical_rcs_does_not_mix_in_current_state_deeper_collection(self) -> None:
        request = CaseRequest(
            text="主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因",
            payload=_build_payload("主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因", chat_id="chat_rcs_history", root_id="root_rcs_history"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_rcs_history",
        )

        diag_report = {
            "need_more_info": False,
            "route": "rcs",
            "target": "192.168.1.170",
            "executed": [{"command": "bash scripts/check_rcs_reboot_history.sh 192.168.1.170", "returncode": 0}],
            "severity": "错误",
            "root_cause": "重启前 3737 端口未监听，且 supervisor 日志显示 master_backend / cbs_master_server 异常退出或等待结束；应优先排查 backend / supervisor 拉起链路。",
            "evidence": "最近一次重启前的 boot 时间：2026-06-14 21:40:52",
            "text": request.text,
        }

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_ENABLE_LOCAL_DIAG": "1"}, clear=False), \
            patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence") as mocked_collect:
            response = self.orchestrator.handle_case(request)

        mocked_collect.assert_not_called()
        self.assertIn("check_rcs_reboot_history.sh", response.reply_text)
        self.assertIn("重启前 3737 端口未监听", response.reply_text)

    def test_historical_rcs_keeps_local_reboot_root_cause_when_provider_summary_is_generic(self) -> None:
        request = CaseRequest(
            text="主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因",
            payload=_build_payload("主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因", chat_id="chat_rcs_hist_provider", root_id="root_rcs_hist_provider"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_rcs_hist_provider",
        )

        diag_report = {
            "need_more_info": False,
            "route": "rcs",
            "target": "192.168.1.170",
            "executed": [{"command": "bash scripts/check_rcs_reboot_history.sh 192.168.1.170", "returncode": 0}],
            "severity": "错误",
            "root_cause": "重启前 3737 端口未监听，且 supervisor 日志显示 master_backend / cbs_master_server 异常退出或等待结束；应优先排查 backend / supervisor 拉起链路。",
            "evidence": "最近一次重启前的 boot 时间：2026-06-14 21:40:52",
            "text": request.text,
        }

        provider_result = ProviderResult(
            provider_name="openai_sdk",
            summary="已根据远程取证补齐主机服务状态。",
            next_steps=("继续核对 supervisor、backend、mysql 的启动日志。",),
            root_cause="RCS 主机关键服务链路异常。",
            severity="错误",
            evidence=(),
            confidence="medium",
        )

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_ENABLE_LOCAL_DIAG": "1"}, clear=False), \
            patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(self.orchestrator.provider_manager, "run_review", return_value=provider_result):
            response = self.orchestrator.handle_case(request)

        self.assertIn("重启前 3737 端口未监听", response.reply_text)
        self.assertIn("应优先排查 backend / supervisor 拉起链路", response.reply_text)

    def test_historical_amr_collects_deeper_evidence_before_finishing(self) -> None:
        request = CaseRequest(
            text="排查从机 leefung-t9 在 2026-06-13 01:14:15 的掉线故障",
            payload=_build_payload("排查从机 leefung-t9 在 2026-06-13 01:14:15 的掉线故障", chat_id="chat_hist_amr_deeper", root_id="root_hist_amr_deeper"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_deeper",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_13 对应的 ROS 原始日志，现有文本证据不足，无法判定具体前/后雷达和直接原因",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04",
            "text": request.text,
        }

        deeper_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "WARNING: topic [/low_level_error] does not appear to be published yet\ncommand timed out after 8s\n", "returncode": 124})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/move_base\n/amcl\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/$(ls -1 /home/robot/log/not_permanent/ 2>/dev/null | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S 2>/dev/null)\" '$1 <= target' | tail -1)/mobile_base.launch 2>/dev/null | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": deeper_results}), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertIn("底层嵌入式 / CAN 链路异常", response.reply_text)
        self.assertIn("rostopic echo /low_level_error -n1", response.reply_text)
        self.assertIn("rosnode list", response.reply_text)

    def test_historical_amr_stage3_uses_caution_and_manual_recovery_clues(self) -> None:
        request = CaseRequest(
            text="排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了",
            payload=_build_payload("排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了", chat_id="chat_hist_amr_stage3", root_id="root_hist_amr_stage3"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_stage3",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_13 对应的 ROS 原始日志，现有文本证据不足，无法判定具体前/后雷达和直接原因",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04\ncaution_T9_20260613_011430.bag.zip",
            "text": request.text,
        }

        locator_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/move_base\n/amcl\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "ls -1 /home/robot/log/not_permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1", "stdout": "2026_06_12-14_05_04\n", "stderr": "", "returncode": 0})(),
        ]
        deeper_results = [
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]
        stage3_results = [
            type("Result", (), {"command": "find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20", "stdout": "/home/robot/autobag/caution_T9_20260613_011430.bag.zip\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80", "stdout": "switch to manual\n", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", side_effect=[{"results": locator_results}, {"results": deeper_results}, {"results": stage3_results}, {"results": []}, {"results": []}]), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertIn("手动 / 恢复动作应视为掩盖首因的派生过程", response.reply_text)
        self.assertIn("caution_T9_20260613_011430.bag.zip", response.reply_text)

    def test_historical_amr_stage4_builds_second_level_timeline(self) -> None:
        request = CaseRequest(
            text="排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了",
            payload=_build_payload("排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了", chat_id="chat_hist_amr_stage4", root_id="root_hist_amr_stage4"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_stage4",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_13 对应的 ROS 原始日志，现有文本证据不足，无法判定具体前/后雷达和直接原因",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04\ncaution_T9_20260613_011430.bag.zip",
            "text": request.text,
        }

        locator_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/move_base\n/amcl\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "ls -1 /home/robot/log/not_permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1", "stdout": "2026_06_12-14_05_04\n", "stderr": "", "returncode": 0})(),
        ]
        deeper_results = [
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]
        stage3_results = [
            type("Result", (), {"command": "find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20", "stdout": "/home/robot/autobag/caution_T9_20260613_011430.bag.zip\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80", "stdout": "switch to manual\n", "stderr": "", "returncode": 0})(),
        ]
        stage4_results = [
            type("Result", (), {"command": "awk mobile_base exact", "stdout": "[1781284454.100000000] connection dropped\n[1781284455.200000000] reset embedded system\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "awk state_monitor exact", "stdout": "[1781284461.000000000] switch to manual\n[1781284463.000000000] pause\n", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", side_effect=[{"results": locator_results}, {"results": deeper_results}, {"results": stage3_results}, {"results": stage4_results}, {"results": []}]), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertIn("首发候选", response.reply_text)
        self.assertIn("恢复/暂停线索", response.reply_text)

    def test_historical_amr_stage5_checks_kernel_and_swap_before_concluding(self) -> None:
        request = CaseRequest(
            text="排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了",
            payload=_build_payload("排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了", chat_id="chat_hist_amr_stage5", root_id="root_hist_amr_stage5"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_stage5",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "警告",
            "root_cause": "未找到 2026_06_13 对应的 ROS 原始日志，现有文本证据不足，无法判定具体前/后雷达和直接原因",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04\ncaution_T9_20260613_011430.bag.zip",
            "text": request.text,
        }

        locator_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/move_base\n/amcl\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "ls -1 /home/robot/log/not_permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1", "stdout": "2026_06_12-14_05_04\n", "stderr": "", "returncode": 0})(),
        ]
        deeper_results = [
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]
        stage3_results = [
            type("Result", (), {"command": "find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20", "stdout": "/home/robot/autobag/caution_T9_20260613_011430.bag.zip\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80", "stdout": "switch to manual\n", "stderr": "", "returncode": 0})(),
        ]
        stage4_results = [
            type("Result", (), {"command": "awk mobile_base exact", "stdout": "[1781284454.100000000] connection dropped\n", "stderr": "", "returncode": 0})(),
        ]
        stage5_results = [
            type("Result", (), {"command": "journalctl -k --since '2026-06-13 00:44:15' --until '2026-06-13 01:44:15' --no-pager", "stdout": "", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "swapon --show", "stdout": "", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", side_effect=[{"results": locator_results}, {"results": deeper_results}, {"results": stage3_results}, {"results": stage4_results}, {"results": stage5_results}]) as mocked_collect, \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertEqual(mocked_collect.call_count, 5)
        stage5_commands = mocked_collect.call_args_list[-1].kwargs["commands"]
        self.assertIn("swapon --show", stage5_commands)
        self.assertIn("journalctl -k --since '2026-06-13 00:44:15' --until '2026-06-13 01:44:15' --no-pager", stage5_commands)
        self.assertTrue(any("find /home/robot/log/permanent/" in item and "date -d \"2026-06-13 01:14:15\"" in item and "error_monitor_server.launch" in item for item in stage5_commands))
        self.assertIn("当前证据不支持把 swap 作为首发根因", response.reply_text)

    def test_historical_amr_auto_closure_builds_first_cause_and_derived_state(self) -> None:
        request = CaseRequest(
            text="排查从机 v001 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了",
            payload=_build_payload("排查从机 v001 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了", chat_id="chat_hist_amr_closure", root_id="root_hist_amr_closure"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_closure",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "v001",
            "executed": [{"command": "bash scripts/collect_logs.sh v001 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "错误",
            "root_cause": "同时间段已存在 caution / bag 线索，且底层链路异常与扫描异常相互印证；应优先按首发底层异常解释本次故障，而不是只看恢复后的状态。",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04\ncaution_v001_20260613_011430.bag.zip",
            "text": request.text,
        }

        locator_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "WARNING: topic [/low_level_error] does not appear to be published yet\n", "returncode": 124})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/motor_control\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "ls -1 /home/robot/log/not_permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1", "stdout": "2026_06_12-14_05_04\n", "stderr": "", "returncode": 0})(),
        ]
        deeper_results = [
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]
        stage3_results = [
            type("Result", (), {"command": "find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20", "stdout": "/home/robot/autobag/caution_v001_20260613_011430.bag.zip\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80", "stdout": "switch to manual\npause\n", "stderr": "", "returncode": 0})(),
        ]
        stage4_results = [
            type("Result", (), {"command": "awk mobile_base exact", "stdout": "[1781284454.100000000] connection dropped\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "awk state_monitor exact", "stdout": "[1781284461.000000000] switch to manual\n", "stderr": "", "returncode": 0})(),
        ]
        stage5_results = [
            type("Result", (), {"command": "find /home/robot/log/permanent/$(ls -1 /home/robot/log/permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1) -maxdepth 3 \\( -type f -o -type l \\) -name 'error_monitor_server.launch' -exec tail -n 120 {} \\;", "stdout": "[1781284458.000000000] Register ID: 32000101 trigger\n", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", side_effect=[{"results": locator_results}, {"results": deeper_results}, {"results": stage3_results}, {"results": stage4_results}, {"results": stage5_results}]), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertIn("自动收口显示：先出现", response.reply_text)
        self.assertIn("switch to manual", response.reply_text)
        self.assertIn("Register ID: 32000101 trigger", response.reply_text)
        self.assertNotIn("核对 01:14:10-01:14:30 期间的 mobile_base.launch", response.reply_text)
        self.assertIn("优先排查 CAN / EB / driver 硬件链路", response.reply_text)
        self.assertIn("若有录包或 bag，优先核对 01:14:10-01:14:25", response.reply_text)

    def test_historical_amr_auto_closure_hides_provider_root_cause_override(self) -> None:
        request = CaseRequest(
            text="排查从机 v001 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了",
            payload=_build_payload("排查从机 v001 在 2026-06-13 01:14:15 的故障，现场后来切手动恢复了", chat_id="chat_hist_amr_provider_hide", root_id="root_hist_amr_provider_hide"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_hist_amr_provider_hide",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "v001",
            "executed": [{"command": "bash scripts/collect_logs.sh v001 '' '2026-06-13 00:44:15' '2026-06-13 01:44:15' '2026-06-13 01:14:15'", "returncode": 0}],
            "severity": "错误",
            "root_cause": "同时间段已存在 caution / bag 线索，且底层链路异常与扫描异常相互印证；应优先按首发底层异常解释本次故障，而不是只看恢复后的状态。",
            "evidence": "/home/robot/log/not_permanent/2026_06_12-14_05_04\ncaution_v001_20260613_011430.bag.zip",
            "text": request.text,
        }

        locator_results = [
            type("Result", (), {"command": "rostopic echo /low_level_error -n1", "stdout": "", "stderr": "WARNING: topic [/low_level_error] does not appear to be published yet\n", "returncode": 124})(),
            type("Result", (), {"command": "rosnode list", "stdout": "/rosout\n/motor_control\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "ls -1 /home/robot/log/not_permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1", "stdout": "2026_06_12-14_05_04\n", "stderr": "", "returncode": 0})(),
        ]
        deeper_results = [
            type("Result", (), {"command": "grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120", "stdout": "connection dropped\nreset embedded system\n", "stderr": "", "returncode": 0})(),
        ]
        stage3_results = [
            type("Result", (), {"command": "find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20", "stdout": "/home/robot/autobag/caution_v001_20260613_011430.bag.zip\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80", "stdout": "switch to manual\npause\n", "stderr": "", "returncode": 0})(),
        ]
        stage4_results = [
            type("Result", (), {"command": "awk mobile_base exact", "stdout": "[1781284454.100000000] connection dropped\n", "stderr": "", "returncode": 0})(),
            type("Result", (), {"command": "awk state_monitor exact", "stdout": "[1781284461.000000000] switch to manual\n", "stderr": "", "returncode": 0})(),
        ]
        stage5_results = [
            type("Result", (), {"command": "find /home/robot/log/permanent/$(ls -1 /home/robot/log/permanent/ | awk -v target=\"$(date -d \"2026-06-13 01:14:15\" +%Y_%m_%d-%H_%M_%S)\" '$1 <= target' | tail -1) -maxdepth 3 \\( -type f -o -type l \\) -name 'error_monitor_server.launch' -exec tail -n 120 {} \\;", "stdout": "[1781284458.000000000] Register ID: 32000101 trigger\n", "stderr": "", "returncode": 0})(),
        ]

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", side_effect=[{"results": locator_results}, {"results": deeper_results}, {"results": stage3_results}, {"results": stage4_results}, {"results": stage5_results}]), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=object()), \
            patch.object(
                self.orchestrator.provider_manager,
                "run_review",
                return_value=ProviderResult(
                    provider_name="openai_sdk",
                    summary="最可能根因是 mobile_base 相关底层链路异常。",
                    next_steps=("检查 01:14:15 前后 mobile_base.launch",),
                    root_cause="最可能根因是 mobile_base 相关底层链路异常。",
                    severity="错误",
                    evidence=(),
                    confidence="high",
                ),
            ):
            response = self.orchestrator.handle_case(request)

        self.assertIn("自动收口显示：先出现", response.reply_text)
        self.assertNotIn("最可能根因是 mobile_base 相关底层链路异常。", response.reply_text)

    def test_relative_historical_amr_enables_local_diag(self) -> None:
        request = CaseRequest(
            text="刚刚从机 leefung-t9 为什么掉线了",
            payload=_build_payload("刚刚从机 leefung-t9 为什么掉线了", chat_id="chat_recent_amr", root_id="root_recent_amr"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_recent_amr",
        )

        diag_report = {
            "need_more_info": False,
            "route": "amr",
            "target": "leefung-t9",
            "executed": [{"command": "bash scripts/collect_logs.sh leefung-t9 '' '2026-06-15 12:00:00' '2026-06-15 20:00:00'", "returncode": 0}],
            "severity": "错误",
            "root_cause": "前雷达 / 前向 LaserScan 在 recent_8h 相关历史证据中存在掉线或数据异常",
            "evidence": "LaserScan front 掉线",
            "text": request.text,
        }

        with patch("feishu_agent.core.orchestrator.diagnose_route", return_value=diag_report), \
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": []}), \
            patch.object(self.orchestrator.provider_manager, "select_provider", return_value=None):
            response = self.orchestrator.handle_case(request)

        self.assertIn("前向扫描链路", response.reply_text)
        self.assertIn("collect_logs.sh", response.reply_text)

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
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": []}), \
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
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": []}), \
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
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": []}), \
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
            patch("feishu_agent.core.orchestrator.collect_evidence", return_value={"results": []}), \
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
            text="看下从机 leefung-t9 当前 CAN 通信异常，雷达和底层总线是否异常",
            payload=_build_payload("看下从机 leefung-t9 当前 CAN 通信异常，雷达和底层总线是否异常"),
            sender_open_id="ou_123",
            sender_display_name="张三",
            message_id="msg_topk",
        )

        with patch.dict("feishu_agent.core.orchestrator.os.environ", {"FEISHU_TOPK_DOCS": "3"}, clear=False):
            response = self.orchestrator.handle_case(request)

        session = self.orchestrator.session_store.get(response.conversation_key)
        self.assertLessEqual(len(session.last_doc_candidates), 3)
        self.assertEqual(session.last_read_docs, [])
        self.assertTrue(
            any(
                "error-codes" in path
                or "can" in path
                or "hardware_bus" in path
                for path in session.last_doc_candidates
            )
        )

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
        self.assertIn("knowledge/hardware_bus/can-eb-communication-abnormal.md", docs)

    def test_select_relevant_docs_matches_location_tf_history_mix(self) -> None:
        docs = select_relevant_docs("刚刚定位漂移并伴随 tf 跳变和地图不匹配", "amr", limit=5)

        self.assertIn("knowledge/ros/location-loss.md", docs)
        self.assertTrue(
            any(
                path in docs
                for path in [
                    "knowledge/ros/tf-tree-incomplete-or-jumping.md",
                    "knowledge/ros/history-case-location-ok-but-map-or-tf-mismatch.md",
                ]
            )
        )

    def test_select_relevant_docs_matches_task_state_feedback_mix(self) -> None:
        docs = select_relevant_docs("任务卡住了，状态不推进，事件没回执", "amr", limit=5)

        self.assertIn("knowledge/task_dispatch/task-state-not-advancing.md", docs)
        self.assertIn("knowledge/task_dispatch/history-case-task-sent-but-no-state-feedback.md", docs)

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

        self.assertIn("**1. 故障结论**", report)
        self.assertIn("对象：amr / 192.168.1.250", report)
        self.assertIn("严重程度：错误", report)
        self.assertIn("**2. 根因**", report)
        self.assertIn("CAN 链路异常", report)
        self.assertIn("**3. 建议**", report)
        self.assertIn("**4. 证据**", report)
        self.assertIn("rostopic echo /low_level_error -n1", report)
        self.assertIn("CAN bus停止发布数据", report)
        self.assertIn("建议继续检查底层链路", report)
        self.assertIn("底层链路抖动", report)
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

    def test_case_report_summarizes_provider_execute_lines_for_human_reading(self) -> None:
        report = format_case_report(
            route="rcs",
            target="192.168.1.170",
            severity="错误",
            root_cause="RCS 主机后端 API 未监听，当前是主业务服务未拉起或已退出，不是单纯接口慢。",
            executed=[{"command": "bash scripts/check_rcs_status.sh 192.168.1.170", "returncode": 0}],
            evidence=[
                "provider_execute[curl -s -S -m 3 http://127.0.0.1:3737/infos/ros/]: rc=7 curl: (7) Failed to connect to 127.0.0.1 port 3737: Connection refused",
                "provider_execute[docker exec docker-mysql_5_7-1 mysqladmin ping]: rc=0 mysqladmin: connect to server at 'localhost' failed error: 'Access denied for user 'root'@'localhost' (using password: NO)'",
                "provider_execute[journalctl -k -n 80 --no-pager]: rc=0 -- Logs begin at Thu 2026-05-07 18:23:04 CST -- -- No entries --",
            ],
            docs=[],
            provider_summary="已根据远程取证补齐主机服务状态。",
            provider_root_cause="RCS 主机后端 API 未监听，当前是主业务服务未拉起或已退出，不是单纯接口慢。",
            provider_next_steps=["检查 3737 端口对应进程"],
        )

        self.assertIn("后端 API 3737 端口连接被拒绝，说明服务当前未监听。", report)
        self.assertIn("MySQL 容器在运行，但当前探活账号/认证方式不匹配。", report)
        self.assertIn("kernel 日志未见明显系统级报错。", report)
        self.assertNotIn("provider_report:", report)

    def test_case_report_summarizes_amr_history_execute_lines_for_human_reading(self) -> None:
        report = format_case_report(
            route="amr",
            target="v001",
            severity="错误",
            root_cause="同时间段已存在 caution / bag 线索，且底层链路异常与扫描异常相互印证；应优先按首发底层异常解释本次故障，而不是只看恢复后的状态。",
            executed=[{"command": "bash scripts/collect_logs.sh v001 2026-06-13 00:44:15 2026-06-13 01:44:15 2026-06-13 01:14:15", "returncode": 0}],
            evidence=[
                "provider_execute[grep -i 'error\\|fail\\|exception\\|warn\\|usb\\|can\\|eb\\|motor\\|driver\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/mobile_base.launch | tail -n 120]: rc=0 connection dropped reset embedded system",
                "provider_execute[grep -i 'error\\|fail\\|exception\\|warn\\|laser\\|scan\\|lidar\\|radar\\|usb\\|can\\|eb\\|motor\\|connection dropped\\|reset embedded system' /home/robot/log/not_permanent/2026_06_12-14_05_04/default.launch | tail -n 120]: rc=0 registerError2 call timeout laser scan",
                "provider_execute[find /home/robot/autobag -maxdepth 1 -type f | grep '20260613' | tail -20]: rc=0 /home/robot/autobag/caution_v001_20260613_004555.bag.zip",
                "provider_execute[grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80]: rc=0 switch to manual",
                "provider_execute[grep -i 'manual\\|auto\\|release\\|recover\\|resume\\|retry\\|hand' /home/robot/log/not_permanent/2026_06_12-14_05_04/state_monitor_wrapper.launch | tail -n 80]: rc=0 switch to manual",
            ],
            docs=[],
        )

        self.assertIn("mobile_base.launch 在故障时段出现 CAN / EB / 驱动链路异常，优先指向底层通信失稳。", report)
        self.assertIn("default.launch 在故障时段出现扫描链路或错误监控异常，需结合底层链路判断是否为派生表现。", report)
        self.assertIn("同时间段存在 caution / bag 证据", report)
        self.assertIn("state_monitor_wrapper.launch 记录到手动 / 恢复 / 重试相关线索，应把它视为恢复动作而不是直接根因。", report)
        self.assertEqual(report.count("state_monitor_wrapper.launch 记录到手动 / 恢复 / 重试相关线索，应把它视为恢复动作而不是直接根因。"), 1)

    def test_case_report_humanizes_provider_mapping_summary(self) -> None:
        report = format_case_report(
            route="amr",
            target="v001",
            severity="错误",
            root_cause="底层通信异常",
            executed=[],
            evidence=[],
            docs=[],
            provider_summary="{'primary': '底层运动控制通信异常。', 'analysis': ['mobile_base 先报 CAN 异常。', '未见 OOM/swap 证据。']}",
            provider_root_cause="{'primary': '优先怀疑 CAN / EB 链路。'}",
        )

        self.assertIn("优先怀疑 CAN / EB 链路。", report)
        self.assertIn("底层运动控制通信异常。", report)
        self.assertIn("mobile_base 先报 CAN 异常。", report)
        self.assertIn("未见 OOM/swap 证据。", report)
        self.assertNotIn("{'primary':", report)

    def test_case_report_deduplicates_evidence_across_local_and_provider_sources(self) -> None:
        report = format_case_report(
            route="amr",
            target="v001",
            severity="错误",
            root_cause="底层通信异常",
            executed=[],
            evidence=[
                "provider_execute[lsusb -t]: rc=0 /:  Bus 02.Port 1",
                "provider_execute[rostopic echo /low_level_error -n1]: rc=127 bash: rostopic: command not found",
            ],
            docs=[],
            provider_evidence=[
                "provider_execute[lsusb -t]: rc=0 /:  Bus 02.Port 1",
                "provider_execute[rostopic echo /low_level_error -n1]: rc=127 bash: rostopic: command not found",
            ],
        )

        self.assertEqual(report.count("lsusb -t: /:  Bus 02.Port 1"), 1)
        self.assertEqual(report.count("rostopic echo /low_level_error -n1: bash: rostopic: command not found"), 1)


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
