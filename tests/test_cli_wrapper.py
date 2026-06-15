import unittest
from unittest.mock import patch

from feishu_agent.core.cli_wrapper import CliObservation, PtyCliWrapper


class PtyCliWrapperTests(unittest.TestCase):
    def test_terminal_setup_prompt_blocks_ready_state(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                " / commands · ? help\n",
                " GPT-5.4 mini\n",
                " Set up terminal for multi-line input support\n",
                " Would you like to add this key binding to your terminal configuration?\n",
            ]
        )

        self.assertTrue(wrapper._has_pending_terminal_setup_prompt(transcript))
        self.assertFalse(wrapper._is_ready_for_prompt(transcript))

    def test_terminal_setup_resolution_restores_ready_state(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                " / commands · ? help\n",
                " GPT-5.4 mini\n",
                " Set up terminal for multi-line input support\n",
                " Would you like to add this key binding to your terminal configuration?\n",
                " Added key binding for shift+enter for VS Code successfully.\n",
            ]
        )

        self.assertFalse(wrapper._has_pending_terminal_setup_prompt(transcript))
        self.assertTrue(wrapper._is_ready_for_prompt(transcript))

    def test_prompt_echo_counts_as_acknowledged(self) -> None:
        wrapper = PtyCliWrapper()
        prompt = "你是 AMR/RCS 排障专家。\n第一步必须且只能输出一个 read_knowledge 代码块。"
        transcript = "❯ 你是 AMR/RCS 排障专家。  第一步必须且只能输出一个 read_knowledge 代码块。"

        self.assertTrue(wrapper._is_prompt_acknowledged(transcript, prompt))

    def test_protocol_correction_prompt_is_not_treated_as_fatal(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "❯ 协议违规：你刚才输出了普通文本或裸命令，但没有使用受控协议块。\n",
                "现在仅按协议继续。\n",
            ]
        )

        self.assertFalse(wrapper._has_fatal_protocol_marker(transcript))

    def test_copilot_clarification_prompt_is_treated_as_fatal(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "● Clarifying what you want next.\n",
                "What would you like me to do in this repository?\n",
                "❯ Type your answer...\n",
            ]
        )

        self.assertTrue(wrapper._has_fatal_protocol_marker(transcript))

    def test_working_chunk_is_treated_as_stall_signal(self) -> None:
        wrapper = PtyCliWrapper()

        self.assertTrue(wrapper._is_stall_chunk("● Working esc cancel"))
        self.assertFalse(wrapper._is_stall_chunk("```read_knowledge\nknowledge/error-codes.md\n```"))

    def test_parse_report_payload_prefers_latest_json_object(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "prompt echo {'ignored': true}\n".replace("'", '"'),
                "some text before result\n",
                '{"summary":"final","root_cause":"probe","severity":"信息","next_steps":[],"evidence":["ok"],"confidence":"high"}',
            ]
        )

        payload = wrapper._parse_report_payload(transcript)

        self.assertEqual(payload.get("summary"), "final")
        self.assertEqual(payload.get("root_cause"), "probe")

    def test_parse_report_payload_salvages_streamed_partial_json(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                '●  {\n',
                '    "summary":     "summary":\n',
                '    "summary": "已读取常见故障知识，当前仅能确认排查方向涉及 USB 设备识别与内核 USB 日志。",\n',
                '    "root_cause": "证据不足，无法确定具体故障根因。",\n',
                '    "severity": "unknown",\n',
                '    "next_steps": ["查看内核 USB 日志", "确认设备连接"],\n',
                '    "confidence": "low"\n',
            ]
        )

        payload = wrapper._parse_report_payload(transcript)

        self.assertEqual(payload.get("summary"), "已读取常见故障知识，当前仅能确认排查方向涉及 USB 设备识别与内核 USB 日志。")
        self.assertEqual(payload.get("root_cause"), "证据不足，无法确定具体故障根因。")
        self.assertEqual(payload.get("severity"), "unknown")
        self.assertEqual(payload.get("confidence"), "low")
        self.assertEqual(payload.get("next_steps"), ["查看内核 USB 日志", "确认设备连接"])

    def test_parse_report_payload_rejects_single_char_severity_from_noisy_transcript(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                '●  {\n',
                '    "summary": "当前未拿到 leefung-t9 的 /low_level_error 与 rosnode 实时结果，无法确认是否存在雷达或底层通信异常。",\n',
                '    "root_cause": "证据不足：只有排障知识摘要，没有现场状态数据。",\n',
                '    "severity": "u",\n',
                '    "next_steps": ["补充 leefung-t9 上 /low_level_error 的当前输出", "补充 rosnode list / rosnode info 关键节点状态"],\n',
                '    "confidence": 0.08\n',
                '  }\n',
            ]
        )

        payload = wrapper._parse_report_payload(transcript)

        self.assertEqual(payload.get("summary"), "当前未拿到 leefung-t9 的 /low_level_error 与 rosnode 实时结果，无法确认是否存在雷达或底层通信异常。")
        self.assertEqual(payload.get("root_cause"), "证据不足：只有排障知识摘要，没有现场状态数据。")
        self.assertNotIn("severity", payload)
        self.assertEqual(payload.get("next_steps"), ["补充 leefung-t9 上 /low_level_error 的当前输出", "补充 rosnode list / rosnode info 关键节点状态"])

    def test_parse_report_payload_salvages_unterminated_streamed_fields(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                '● Working esc cancel GPT-5.4 mini\n',
                '    "summary": "当前只有排障方法知识，没有 leefung-t9 的实时 /low_level_error 或 rosnode 状态，无法确认是否存在\n',
                '● Working esc cancel GPT-5.4 mini\n',
                '    "root_cause": "证据不足，尚未获得目标从机的运行状态或错误码输出\n',
            ]
        )

        payload = wrapper._parse_report_payload(transcript)

        self.assertEqual(
            payload.get("summary"),
            "当前只有排障方法知识，没有 leefung-t9 的实时 /low_level_error 或 rosnode 状态，无法确认是否存在",
        )
        self.assertEqual(
            payload.get("root_cause"),
            "证据不足，尚未获得目标从机的运行状态或错误码输出",
        )

    def test_normalize_report_payload_prefers_richer_list_candidates(self) -> None:
        wrapper = PtyCliWrapper()
        payload = {
            "summary": "当前未拿到实时结果。",
            "root_cause": "证据不足。",
            "next_steps": ["补充 /low_level_error"],
            "evidence": ["仅有知识摘要"],
        }
        transcript = "".join(
            [
                '"summary": "当前未拿到实时结果。"',
                '"root_cause": "证据不足。"',
                '"next_steps": ["补充 /low_level_error"]',
                '"next_steps": ["补充 /low_level_error", "补充 rosnode list / rosnode info 关键节点状态"]',
                '"evidence": ["仅有知识摘要"]',
                '"evidence": ["仅有知识摘要", "未提供 leefung-t9 的实时 /low_level_error 或 rosnode 结果"]',
            ]
        )

        normalized = wrapper._normalize_report_payload(payload, transcript)

        self.assertEqual(
            normalized.get("next_steps"),
            ["补充 /low_level_error", "补充 rosnode list / rosnode info 关键节点状态"],
        )
        self.assertEqual(
            normalized.get("evidence"),
            ["仅有知识摘要", "未提供 leefung-t9 的实时 /low_level_error 或 rosnode 结果"],
        )

    def test_looks_like_report_payload_requires_more_than_summary_for_early_finish(self) -> None:
        wrapper = PtyCliWrapper()

        self.assertFalse(wrapper._looks_like_report_payload({"summary": "only summary"}, require_complete=True))
        self.assertFalse(
            wrapper._looks_like_report_payload(
                {"summary": "done", "root_cause": "未"},
                require_complete=True,
            )
        )

    def test_normalize_report_payload_prefers_longer_cleaner_values(self) -> None:
        wrapper = PtyCliWrapper()
        payload = {
            "summary": "当前证据仅显示常见 USB 设备识别排障点，核心动作",
            "root_cause": "未能从现有证据确认具体根因 ◉ Working esc cancel GPT-5.4 mini",
        }
        transcript = "".join(
            [
                '{"summary":"当前证据仅显示常见 USB 设备识别排障点，核心动作"}',
                '"summary": "当前证据仅显示常见 USB 设备识别排障点，核心动作是查看内核 USB 日志。"',
                '"root_cause": "未能从现有证据确认具体根因；更像是 USB 设备识别类问题。"',
            ]
        )

        normalized = wrapper._normalize_report_payload(payload, transcript)

        self.assertEqual(normalized.get("summary"), "当前证据仅显示常见 USB 设备识别排障点，核心动作是查看内核 USB 日志。")
        self.assertEqual(normalized.get("root_cause"), "未能从现有证据确认具体根因；更像是 USB 设备识别类问题。")
        self.assertTrue(
            wrapper._looks_like_report_payload(
                {"summary": "done", "root_cause": "insufficient evidence"},
                require_complete=True,
            )
        )

    def test_parse_report_payload_filters_transcript_noise_from_lists(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                '执行结果：```result {"command":"rosnode list","returncode":127,"stderr":"list: rosnode: command not found"}```\n',
                '●  {\n',
                '  "summary": "当前无法直接读取 /low_level_error 和 rosnode 状态。",\n',
                '  "root_cause": "远端未进入 ROS 环境或相关工具未安装。",\n',
                '  "severity": "medium",\n',
                '  "next_steps": ["先在目标机加载 ROS 环境后重试 rostopic echo /low_level_error -n1 与 rosnode list。", "补充采集底层服务/进程状态后，再判断是否为雷达或底层通信异常。"],\n',
                '  "evidence": ["rostopic echo /low_level_error -n1 -> returncode 127, stderr: rostopic: command not found", "rosnode list -> returncode 127, stderr: list: rosnode: command not found"]\n',
                '}\n',
                '● Working esc cancel GPT-5.4 mini\n',
                'command\nreturncode\nstdout\nstderr\nsource\n',
            ]
        )

        payload = wrapper._parse_report_payload(transcript)

        self.assertEqual(
            payload.get("next_steps"),
            [
                "先在目标机加载 ROS 环境后重试 rostopic echo /low_level_error -n1 与 rosnode list。",
                "补充采集底层服务/进程状态后，再判断是否为雷达或底层通信异常。",
            ],
        )
        self.assertEqual(
            payload.get("evidence"),
            [
                "rostopic echo /low_level_error -n1 -> returncode 127, stderr: rostopic: command not found",
                "rosnode list -> returncode 127, stderr: list: rosnode: command not found",
            ],
        )

    def test_find_naked_report_payload_after_ready_prompt(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "●  knowledge/error-tracing-methods.md\n",
                "❯ 已读取知识摘要。文档: knowledge/error-tracing-methods.md。摘要: # 机器常见错误追溯方法。\n",
                '●  {\n',
                '    "summary": "当前未发现可直接证明雷达或底层通信异常的证据。",\n',
                '    "root_cause": "从机 leefung-t9 的 /low_level_error 当前未发布，且 rosnode list 正常返回，现有证据更像是当前未出现低层错误。",\n',
                '    "severity": "信息",\n',
                '    "next_steps": ["继续观察 /low_level_error 是否后续发布", "进一步检查雷达相关节点日志与话题连通性"],\n',
                '    "evidence": ["/low_level_error 当前未发布", "rosnode list 成功返回多个 ROS 节点"],\n',
                '    "confidence": "medium"\n',
                ' }\n',
                " / commands · ? help\n",
            ]
        )

        payload = wrapper._find_naked_report_payload(transcript)

        self.assertEqual(payload.get("summary"), "当前未发现可直接证明雷达或底层通信异常的证据。")
        self.assertEqual(payload.get("severity"), "信息")
        self.assertEqual(payload.get("confidence"), "medium")

    def test_find_next_action_accepts_naked_knowledge_path_output(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "❯ 你是 AMR/RCS 排障专家。正文只能是 knowledge/common-faults.md。\n",
                "●  knowledge/common-faults.md   `\n",
            ]
        )

        action = wrapper._find_next_action(transcript, set())

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.kind, "read_knowledge")
        self.assertEqual(action.body, "knowledge/common-faults.md")

    def test_find_next_action_accepts_naked_execute_pseudo_action(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "".join(
            [
                "●  check_low_level_error_and_rosnode leefung-t9\n",
            ]
        )

        action = wrapper._find_next_action(transcript, set())

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.kind, "execute")
        self.assertEqual(action.body, "rostopic echo /low_level_error -n1")

    def test_find_next_action_extracts_allowed_commands_from_naked_ssh_line(self) -> None:
        wrapper = PtyCliWrapper()
        transcript = "●  ssh leefung-t9 'rosnode list && rostopic echo -n 1 /low_level_error'\n"

        first_action = wrapper._find_next_action(transcript, set())

        self.assertIsNotNone(first_action)
        assert first_action is not None
        self.assertEqual(first_action.kind, "execute")
        self.assertEqual(first_action.body, "rosnode list")
        self.assertEqual(first_action.raw_block, "rosnode list")

        second_action = wrapper._find_next_action(transcript, {"rosnode list"})

        self.assertIsNotNone(second_action)
        assert second_action is not None
        self.assertEqual(second_action.kind, "execute")
        self.assertEqual(second_action.body, "rostopic echo /low_level_error -n1")
        self.assertEqual(second_action.raw_block, "rostopic echo -n 1 /low_level_error")

    def test_should_send_protocol_correction_after_stall_delay(self) -> None:
        wrapper = PtyCliWrapper()
        wrapper._protocol_correction_enabled = True
        wrapper._protocol_correction_delay_seconds = 2.5

        with patch("feishu_agent.core.cli_wrapper.time.monotonic", return_value=10.0):
            should_send = wrapper._should_send_protocol_correction(
                stalled_since=7.0,
                prompt_sent=True,
                prompt_acknowledged=True,
                corrective_prompt_sent=False,
                action_count=0,
                has_report=False,
            )

        self.assertTrue(should_send)

    def test_send_message_submits_after_writing_payload(self) -> None:
        wrapper = PtyCliWrapper()

        with patch("feishu_agent.core.cli_wrapper.os.write") as mock_write:
            with patch("feishu_agent.core.cli_wrapper.time.sleep"):
                wrapper._send_message(7, ["copilot"], "line1\nline2\n", reason="test")

        self.assertEqual(mock_write.call_count, 2)
        self.assertEqual(mock_write.call_args_list[0].args[1], b"line1\nline2")
        self.assertEqual(mock_write.call_args_list[1].args[1], b"\r")

    def test_send_observation_enqueues_then_submits(self) -> None:
        wrapper = PtyCliWrapper()

        with patch("feishu_agent.core.cli_wrapper.os.write") as mock_write:
            with patch("feishu_agent.core.cli_wrapper.time.sleep"):
                wrapper._send_observation(7, ["copilot"], "line1\nline2\n", source="knowledge")

        self.assertEqual(mock_write.call_count, 3)
        self.assertEqual(mock_write.call_args_list[0].args[1], b"line1\nline2")
        self.assertEqual(mock_write.call_args_list[1].args[1], b"\x11")
        self.assertEqual(mock_write.call_args_list[2].args[1], b"\r")


if __name__ == "__main__":
    unittest.main()