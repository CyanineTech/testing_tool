import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feishu_agent.core.cli_wrapper import CliSessionResult
from feishu_agent.protocols.actions import ACTION_READ_KNOWLEDGE, ACTION_REPORT, ACTION_SECURE_SSH_EXECUTE
from feishu_agent.providers.base import build_interactive_protocol_prompt
from feishu_agent.providers.base import ProviderRequest
from feishu_agent.providers.base import ProviderResult
from feishu_agent.providers.copilot_cli import CopilotCliProvider


class CopilotCliProviderTests(unittest.TestCase):
    def test_interactive_command_uses_stdin_prompt_by_default(self) -> None:
        provider = CopilotCliProvider()

        command = provider._interactive_command("copilot", "prompt body")

        self.assertEqual(command[:2], ["copilot", "-i"])
        self.assertNotIn("prompt body", command)
        self.assertIn("--available-tools=", command)
        self.assertIn("--disable-builtin-mcps", command)

    def test_interactive_prompt_uses_compact_protocol_instructions(self) -> None:
        request = ProviderRequest(
            route="amr",
            question="直接输出 report，不要 read_knowledge，不要 execute。",
            context="最小上下文。",
            evidence=[],
            target="probe-target",
        )

        prompt = build_interactive_protocol_prompt(request)

        self.assertIn("只允许以下三种输出之一", prompt)
        self.assertIn("report 代码块：正文必须是 JSON", prompt)
        self.assertIn("禁止使用 Copilot 内建 Search/Read/Check/shell 工具", prompt)
        self.assertIn("必须先输出 read_knowledge 或 execute 代码块", prompt)
        self.assertNotIn("report 输出格式要求", prompt)
        self.assertNotIn("所有字段内容都必须基于本轮问题和本轮证据生成", prompt)

    def test_interactive_prompt_uses_minimal_read_knowledge_first_probe(self) -> None:
        request = ProviderRequest(
            route="amr",
            question="只做动作连通性测试：第一步必须且只能输出一个 read_knowledge 代码块，正文只能是 knowledge/common-faults.md；不要 execute。收到文档后再决定是否 report。",
            context="这是最小 read_knowledge 动作探针。",
            evidence=["knowledge_candidates: knowledge/common-faults.md"],
            target="probe-target",
        )

        prompt = build_interactive_protocol_prompt(request)

        self.assertIn("第一步必须且只能输出一个 read_knowledge 代码块", prompt)
        self.assertIn("正文只能是 knowledge/common-faults.md", prompt)
        self.assertIn("不要输出 execute。不要输出 report。不要解释。", prompt)
        self.assertNotIn("route: amr", prompt)
        self.assertNotIn("只允许以下三种输出之一", prompt)

    def test_interactive_prompt_drops_bulky_doc_excerpt_evidence(self) -> None:
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常",
            context="已收到：AMR 机器人问题",
            evidence=[
                "knowledge_candidates: knowledge/error-codes.md, knowledge/error-tracing-methods.md",
                "doc_excerpt[knowledge/error-codes.md]: # 错误码对照表 " + ("X" * 500),
                "existing_observation: short note",
            ],
            target="leefung-t9",
        )

        prompt = build_interactive_protocol_prompt(request)

        self.assertIn("knowledge_candidates: knowledge/error-codes.md, knowledge/error-tracing-methods.md", prompt)
        self.assertIn("existing_observation: short note", prompt)
        self.assertNotIn("doc_excerpt[knowledge/error-codes.md]", prompt)
        self.assertLess(len(prompt), 1400)

    def test_interactive_stall_returns_explicit_provider_result(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="只做协议连通性测试：先补一条 knowledge，再根据结果输出 report。",
            context="已收到：AMR 机器人问题",
            evidence=["knowledge_candidates: knowledge/common-faults.md, knowledge/error-codes.md"],
            target="leefung-t9",
        )

        stalled_session = CliSessionResult(
            raw_output="● Working esc cancel",
            timed_out=True,
            stop_reason="stalled_no_blocks",
        )

        with patch.object(CopilotCliProvider, "_interactive_command", return_value=["copilot", "-i"]), \
            patch("feishu_agent.providers.copilot_cli.PtyCliWrapper.run", return_value=stalled_session) as mocked_run:
            result = provider._run_interactive_protocol("copilot", request, timeout_seconds=30)

        self.assertEqual(mocked_run.call_args.kwargs["initial_prompt"], build_interactive_protocol_prompt(request))
        self.assertEqual(result.summary, "copilotcli PTY 工作态卡住，未产出受控协议块。")
        self.assertEqual(result.root_cause, "PTY 会话进入工作态后持续无块输出，当前未拿到 read_knowledge、execute 或 report。")
        self.assertIn("pty_stalled_no_blocks", result.evidence)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)
        self.assertEqual(result.severity, "警告")
        self.assertEqual(result.confidence, "low")

    def test_interactive_partial_report_timeout_returns_explicit_provider_result(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="直接输出 report，不要 read_knowledge，不要 execute。",
            context="最小上下文。",
            evidence=[],
            target="probe-target",
        )

        partial_session = CliSessionResult(
            raw_output='{"summary":"x","root_cause":"y","severity":"unknown","next_steps":["z"]',
            timed_out=True,
            stop_reason="deadline_timeout",
        )

        with patch.object(CopilotCliProvider, "_interactive_command", return_value=["copilot", "-i"]), \
            patch("feishu_agent.providers.copilot_cli.PtyCliWrapper.run", return_value=partial_session) as mocked_run:
            result = provider._run_interactive_protocol("copilot", request, timeout_seconds=30)

        self.assertEqual(mocked_run.call_args.kwargs["initial_prompt"], build_interactive_protocol_prompt(request))
        self.assertEqual(result.summary, "copilotcli PTY 已输出报告片段，但未形成可解析的最终 report。")
        self.assertEqual(result.root_cause, "PTY 会话在超时前只输出了残缺或重复的 report-like JSON 片段，未形成可解析对象。")
        self.assertIn("pty_partial_report_timeout", result.evidence)
        self.assertEqual(result.severity, "警告")
        self.assertEqual(result.confidence, "low")

    def test_run_falls_back_to_single_shot_when_pty_stalls(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            context="已收到：AMR 机器人问题",
            evidence=["knowledge_candidates: knowledge/error-codes.md", "remote[rosnode list]: /rosout"],
            target="leefung-t9",
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {
                "COPILOTCLI_COMMAND": "copilot",
                "COPILOTCLI_ENABLE_PTY_PROTOCOL": "1",
                "COPILOTCLI_PTY_ROUTES": "amr",
            },
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_interactive_protocol",
            return_value=ProviderResult(
                provider_name="copilotcli",
                summary="copilotcli PTY 工作态卡住，未产出受控协议块。",
                next_steps=(),
                root_cause="PTY 会话进入工作态后持续无块输出，当前未拿到 read_knowledge、execute 或 report。",
                severity="警告",
                evidence=("pty_stalled_no_blocks",),
                confidence="low",
            ),
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(0, '{"summary":"已根据远端证据生成结论","root_cause":"低层错误码异常","severity":"警告","next_steps":["继续检查CAN"],"evidence":["remote[rosnode list]: /rosout"],"confidence":"medium"}', "", False),
        ) as mocked_single_shot:
            result = provider.run(request)

        self.assertTrue(mocked_single_shot.called)
        self.assertEqual(result.summary, "已根据远端证据生成结论")
        self.assertEqual(result.root_cause, "低层错误码异常")

    def test_run_falls_back_to_single_shot_when_pty_enters_clarification_ui(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            context="已收到：AMR 机器人问题",
            evidence=["knowledge_candidates: knowledge/error-codes.md", "remote[rosnode list]: /rosout"],
            target="leefung-t9",
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {
                "COPILOTCLI_COMMAND": "copilot",
                "COPILOTCLI_ENABLE_PTY_PROTOCOL": "1",
                "COPILOTCLI_PTY_ROUTES": "amr",
            },
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_interactive_protocol",
            side_effect=RuntimeError("pty interactive session entered unsupported tool/protocol flow"),
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(0, '{"summary":"已回退 single-shot 并生成结论","root_cause":"rosnode 可达，/low_level_error 未发布","severity":"信息","next_steps":["继续观察 topic 发布状态"],"evidence":["remote[rosnode list]: /rosout"],"confidence":"medium"}', "", False),
        ) as mocked_single_shot:
            result = provider.run(request)

        self.assertTrue(mocked_single_shot.called)
        self.assertEqual(result.summary, "已回退 single-shot 并生成结论")
        self.assertEqual(result.root_cause, "rosnode 可达，/low_level_error 未发布")

    def test_run_uses_partial_jsonl_output_when_single_shot_times_out(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            context="已收到：AMR 机器人问题",
            evidence=["remote[rosnode list]: /rosout"],
            target="leefung-t9",
        )
        partial_jsonl = "\n".join(
            [
                '{"type":"assistant.message_delta","data":{"deltaContent":"{\\"summary\\":\\"已根据部分输出得出结论\\",\\"root_cause\\":\\"rosnode 可达，/low_level_error 未发布\\",\\"severity\\":\\"信息\\",\\"next_steps\\":[\\"继续观察 topic 发布状态\\"],\\"evidence\\":[\\"remote[rosnode list]: /rosout\\"],\\"confidence\\":\\"medium\\"}"}}',
                '{"type":"assistant.message","data":{"content":"{\"summary\":\"已根据部分输出得出结论\",\"root_cause\":\"rosnode 可达，/low_level_error 未发布\",\"severity\":\"信息\",\"next_steps\":[\"继续观察 topic 发布状态\"],\"evidence\":[\"remote[rosnode list]: /rosout\"],\"confidence\":\"medium\"}"}}',
            ]
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {"COPILOTCLI_COMMAND": "copilot"},
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(-15, partial_jsonl, "", True),
        ):
            result = provider.run(request)

        self.assertEqual(result.summary, "已根据部分输出得出结论")
        self.assertEqual(result.root_cause, "rosnode 可达，/low_level_error 未发布")
        self.assertEqual(result.confidence, "medium")

    def test_run_does_not_treat_non_json_stream_as_valid_result_on_timeout(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 在6月7日掉线的是哪个雷达，什么原因导致的",
            context="已收到：AMR 机器人问题",
            evidence=["knowledge_candidates: knowledge/common-faults.md"],
            target="leefung-t9",
        )
        noisy_jsonl = "\n".join(
            [
                '{"type":"session.warning","data":{"warningType":"policy","message":"Third-party MCP servers are disabled by your organization\'s Copilot policy. Only built-in servers are available."}}',
                '{"type":"assistant.message_delta","data":{"deltaContent":"先确认目标可达，再直接取6月7日相关日志定位掉线的雷达与触发原因。"}}',
                '{"type":"assistant.message","data":{"content":"先确认目标可达，再直接取6月7日相关日志定位掉线的雷达与触发原因。"}}',
            ]
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {"COPILOTCLI_COMMAND": "copilot"},
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(-15, noisy_jsonl, "", True),
        ):
            result = provider.run(request)

        self.assertEqual(result.summary, "copilotcli 超时后已终止。")
        self.assertEqual(result.root_cause, "")
        self.assertIn(
            "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy. Only built-in servers are available.",
            result.evidence,
        )

    def test_run_returns_explicit_quota_result_for_single_shot(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            context="已收到：AMR 机器人问题",
            evidence=["remote[rosnode list]: /rosout"],
            target="leefung-t9",
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {"COPILOTCLI_COMMAND": "copilot"},
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(1, "✗ You have exceeded your monthly quota\nAI Credits: 0", "", False),
        ):
            result = provider.run(request)

        self.assertEqual(result.summary, "当前 Copilot 月度额度已用尽，模型复核暂时不可用。")
        self.assertEqual(result.root_cause, "Copilot CLI 返回月度额度耗尽，当前请求无法完成模型复核。")
        self.assertIn("copilot_quota_exhausted", result.evidence)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_run_suppresses_jsonl_event_stream_from_summary(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="rcs",
            question="看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 从机后端/limited_zone/request_states服务，为什么失败",
            context="已收到：RCS 主机问题",
            evidence=["knowledge_candidates: knowledge/backend/python-ros-call-chain-monitoring.md"],
            target="leefung-s1",
        )
        noisy_jsonl = "\n".join(
            [
                '{"type":"session.warning","data":{"warningType":"policy","message":"Third-party MCP servers are disabled by your organization\'s Copilot policy. Only built-in servers are available."}}',
                '{"type":"session.mcp_server_status_changed","data":{"serverName":"github-mcp-server","status":"connected"}}',
                '{"type":"session.mcp_servers_loaded","data":{"servers":[{"name":"github-mcp-server","status":"connected","source":"builtin","transport":"http"}]}}',
            ]
        )

        with patch.dict(
            "feishu_agent.providers.copilot_cli.os.environ",
            {"COPILOTCLI_COMMAND": "copilot"},
            clear=False,
        ), patch.object(
            CopilotCliProvider,
            "_run_single_shot",
            return_value=(0, noisy_jsonl, "", False),
        ):
            result = provider.run(request)

        self.assertEqual(result.summary, "copilotcli 未返回可解析诊断结果。")
        self.assertEqual(result.confidence, "low")
        self.assertIn(
            "policy_warning: Third-party MCP servers are disabled by your organization's Copilot policy. Only built-in servers are available.",
            result.evidence,
        )

    def test_interactive_quota_result_is_explicit(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态",
            context="已收到：AMR 机器人问题",
            evidence=["knowledge_candidates: knowledge/error-codes.md"],
            target="leefung-t9",
        )

        quota_session = CliSessionResult(
            raw_output="AI Credits: 0\n✗ You have exceeded your monthly quota",
            timed_out=False,
            stop_reason="quota_exhausted",
        )

        with patch.object(CopilotCliProvider, "_interactive_command", return_value=["copilot", "-i"]), \
            patch("feishu_agent.providers.copilot_cli.PtyCliWrapper.run", return_value=quota_session):
            result = provider._run_interactive_protocol("copilot", request, timeout_seconds=30)

        self.assertEqual(result.summary, "当前 Copilot 月度额度已用尽，模型复核暂时不可用。")
        self.assertIn("copilot_quota_exhausted", result.evidence)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_interactive_protocol_maps_observations_to_action_events(self) -> None:
        provider = CopilotCliProvider()
        request = ProviderRequest(
            route="amr",
            question="继续检查",
            context="已收到：AMR 机器人问题",
            evidence=[],
            target="leefung-t9",
        )
        report_payload = {
            "summary": "已生成结论",
            "root_cause": "底层通信波动",
            "severity": "warning",
            "next_steps": ["继续检查 CAN"],
            "evidence": ["remote: ok"],
            "confidence": "medium",
        }
        session = CliSessionResult(
            raw_output='{"summary":"已生成结论"}',
            report_payload=report_payload,
            observations=[
                SimpleNamespace(
                    command="knowledge/common-faults.md",
                    returncode=0,
                    stdout="知识摘要",
                    stderr="",
                    source="knowledge",
                ),
                SimpleNamespace(
                    command="ip -details link show can0",
                    returncode=0,
                    stdout="state UP",
                    stderr="",
                    source="ssh",
                ),
            ],
        )

        with patch.object(CopilotCliProvider, "_interactive_command", return_value=["copilot", "-i"]), \
            patch("feishu_agent.providers.copilot_cli.PtyCliWrapper.run", return_value=session):
            result = provider._run_interactive_protocol("copilot", request, timeout_seconds=30)

        self.assertEqual(result.action_events[0].type, ACTION_READ_KNOWLEDGE)
        self.assertEqual(result.action_events[1].type, ACTION_SECURE_SSH_EXECUTE)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)


if __name__ == "__main__":
    unittest.main()
