import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feishu_agent.protocols.actions import ACTION_READ_KNOWLEDGE, ACTION_REPORT, ACTION_SECURE_SSH_EXECUTE
from feishu_agent.providers.manager import ProviderManager
from feishu_agent.providers.openai_sdk import OpenAIProvider
from feishu_agent.providers.base import ProviderRequest


class OpenAIProviderTests(unittest.TestCase):
    def test_available_returns_false_without_api_key(self) -> None:
        provider = OpenAIProvider()

        with patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict("os.environ", {}, clear=True):
            self.assertFalse(provider.available())

    def test_available_returns_false_when_sdk_missing(self) -> None:
        provider = OpenAIProvider()

        with patch("feishu_agent.providers.openai_sdk.OpenAI", None), patch.dict(
            "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
        ):
            self.assertFalse(provider.available())

    def test_available_returns_true_with_api_key_and_sdk(self) -> None:
        provider = OpenAIProvider()

        with patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
        ):
            self.assertTrue(provider.available())

    def test_provider_manager_prefers_openai_provider_when_available(self) -> None:
        manager = ProviderManager(providers=[OpenAIProvider()])

        with patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
        ):
            provider = manager.select_provider()

        self.assertIsNotNone(provider)
        self.assertEqual(provider.name, "openai_sdk")

    def test_provider_manager_uses_configured_provider_order(self) -> None:
        with patch("feishu_agent.providers.manager.SETTINGS") as mocked_settings:
            mocked_settings.provider.mode = "copilot_cli"
            mocked_settings.provider.fallback_mode = "openai_sdk"
            manager = ProviderManager()

        self.assertEqual(manager.providers[0].name, "copilotcli")
        self.assertEqual(manager.providers[1].name, "openai_sdk")

    def test_run_calls_responses_api_with_required_flags(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="rcs",
            question="RCS 主机后端接口超时",
            context="已收到：RCS 主机问题",
            evidence=["knowledge_candidates: knowledge/backend/service-timeout.md"],
            target="leefung-s1",
        )
        fake_response = SimpleNamespace(
            output_text='{"summary":"已收到 RCS 问题","root_cause":"后端接口超时","severity":"warning","next_steps":["检查后端服务"],"evidence":["HTTP 500"],"confidence":"medium"}'
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: fake_response
            )
        )

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None), patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://pikachu.claudecode.love",
                "OPENAI_MODEL": "gpt-4.1",
            },
            clear=False,
        ), patch.object(OpenAIProvider, "_client", return_value=fake_client):
            with patch.object(fake_client.responses, "create", wraps=fake_client.responses.create) as mocked_create:
                result = provider.run(request)

        mocked_create.assert_called_once()
        kwargs = mocked_create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4.1")
        self.assertFalse(kwargs["parallel_tool_calls"])
        self.assertFalse(kwargs["store"])
        self.assertNotIn("tools", kwargs)
        self.assertEqual(result.summary, "已收到 RCS 问题")
        self.assertEqual(result.root_cause, "后端接口超时")
        self.assertEqual(result.confidence, "medium")
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_build_instructions_disables_tool_calls_by_default(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="amr",
            question="看下历史掉线原因",
            context="已收到：AMR 机器人问题",
            evidence=[],
            target="leefung-t9",
        )

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None):
            instructions = provider._build_instructions(request)

        self.assertIn("本轮不要申请任何函数调用", instructions)
        self.assertIn("不要输出 Markdown", instructions)

    def test_parse_response_payload_salvages_plain_text_output(self) -> None:
        provider = OpenAIProvider()
        raw_output = "\n".join(
            [
                "已定位到历史问题方向",
                "根因: 前雷达历史通信波动",
                "严重程度: 警告",
                "建议下一步: 核对 caution 包与 default.launch",
                "证据: 2026_06_07 对应日志缺失",
            ]
        )

        payload = provider._parse_response_payload(raw_output)

        self.assertEqual(payload["summary"], "已定位到历史问题方向")
        self.assertEqual(payload["root_cause"], "前雷达历史通信波动")
        self.assertEqual(payload["severity"], "warning")
        self.assertTrue(payload["next_steps"])
        self.assertTrue(payload["evidence"])

    def test_run_returns_unavailable_result_when_sdk_or_key_missing(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="amr",
            question="AMR 当前状态",
            context="已收到：AMR 机器人问题",
            evidence=[],
            target="leefung-t9",
        )

        with patch("feishu_agent.providers.openai_sdk.OpenAI", None), patch.dict("os.environ", {}, clear=True):
            result = provider.run(request)

        self.assertEqual(result.summary, "openai_sdk provider 当前不可用。")
        self.assertEqual(result.confidence, "low")

    def test_run_handles_read_knowledge_function_call_roundtrip(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="rcs",
            question="RCS 主机后端接口超时",
            context="已收到：RCS 主机问题",
            evidence=["knowledge_candidates: knowledge/backend/service-timeout.md"],
            target="leefung-s1",
        )
        first_response = SimpleNamespace(
            id="resp_1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_1",
                    name="read_knowledge",
                    arguments='{"path":"knowledge/backend/service-timeout.md"}',
                )
            ],
            output_text="",
        )
        second_response = SimpleNamespace(
            id="resp_2",
            output_text='{"summary":"已补知识后生成结论","root_cause":"后端接口超时","severity":"warning","next_steps":["检查后端服务"],"evidence":["service-timeout"],"confidence":"medium"}',
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace()
        )
        fake_client.responses.create = Mock(side_effect=[first_response, second_response])

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None), patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://pikachu.claudecode.love",
                "OPENAI_MODEL": "gpt-4.1",
                "OPENAI_ENABLE_TOOL_CALLS": "1",
            },
            clear=False,
        ), patch.object(OpenAIProvider, "_client", return_value=fake_client), patch(
            "feishu_agent.providers.openai_sdk.load_knowledge_excerpt",
            return_value=("服务超时知识摘要", ""),
        ):
            result = provider.run(request)

        self.assertEqual(fake_client.responses.create.call_count, 2)
        second_call = fake_client.responses.create.call_args_list[1].kwargs
        self.assertEqual(second_call["previous_response_id"], "resp_1")
        self.assertEqual(second_call["input"][0]["type"], "function_call_output")
        self.assertEqual(result.summary, "已补知识后生成结论")
        self.assertEqual(result.root_cause, "后端接口超时")
        self.assertEqual(result.action_events[0].type, ACTION_READ_KNOWLEDGE)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_run_handles_secure_ssh_execute_function_call_roundtrip(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="rcs",
            question="检查主机服务状态",
            context="已收到：RCS 主机问题",
            evidence=[],
            target="leefung-s1",
        )
        first_response = SimpleNamespace(
            id="resp_exec_1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_exec_1",
                    name="secure_ssh_execute",
                    arguments='{"command":"systemctl status supervisor"}',
                )
            ],
            output_text="",
        )
        second_response = SimpleNamespace(
            id="resp_exec_2",
            output_text='{"summary":"已检查主机服务","root_cause":"supervisor 未运行","severity":"error","next_steps":["拉起 supervisor"],"evidence":["systemctl status supervisor"],"confidence":"medium"}',
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace()
        )
        fake_client.responses.create = Mock(side_effect=[first_response, second_response])
        fake_result = SimpleNamespace(
            command="systemctl status supervisor",
            returncode=0,
            stdout="supervisor inactive",
            stderr="",
        )

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None), patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://pikachu.claudecode.love",
                "OPENAI_MODEL": "gpt-4.1",
                "OPENAI_ENABLE_TOOL_CALLS": "1",
            },
            clear=False,
        ), patch.object(OpenAIProvider, "_client", return_value=fake_client), patch(
            "feishu_agent.providers.openai_sdk.collect_on_demand_evidence",
            return_value={"results": [fake_result]},
        ):
            result = provider.run(request)

        self.assertEqual(fake_client.responses.create.call_count, 2)
        second_call = fake_client.responses.create.call_args_list[1].kwargs
        self.assertEqual(second_call["previous_response_id"], "resp_exec_1")
        self.assertEqual(second_call["input"][0]["type"], "function_call_output")
        self.assertEqual(result.summary, "已检查主机服务")
        self.assertEqual(result.root_cause, "supervisor 未运行")
        self.assertEqual(result.action_events[0].type, ACTION_SECURE_SSH_EXECUTE)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_run_falls_back_when_previous_response_id_is_unsupported(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="rcs",
            question="检查主机服务状态",
            context="已收到：RCS 主机问题",
            evidence=[],
            target="leefung-s1",
        )
        first_response = SimpleNamespace(
            id="resp_exec_1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_exec_1",
                    name="secure_ssh_execute",
                    arguments='{"command":"systemctl status supervisor"}',
                )
            ],
            output_text="",
        )
        second_response = SimpleNamespace(
            id="resp_exec_2",
            output_text='{"summary":"已检查主机服务","root_cause":"supervisor 未运行","severity":"error","next_steps":["拉起 supervisor"],"evidence":["systemctl status supervisor"],"confidence":"medium"}',
        )
        fake_client = SimpleNamespace(responses=SimpleNamespace())
        fake_client.responses.create = Mock(
            side_effect=[
                first_response,
                Exception("previous_response_id is only supported on Responses WebSocket v2"),
                second_response,
            ]
        )
        fake_result = SimpleNamespace(
            command="systemctl status supervisor",
            returncode=0,
            stdout="supervisor inactive",
            stderr="",
        )

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None), patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://pikachu.claudecode.love",
                "OPENAI_MODEL": "gpt-4.1",
                "OPENAI_ENABLE_TOOL_CALLS": "1",
            },
            clear=False,
        ), patch.object(OpenAIProvider, "_client", return_value=fake_client), patch(
            "feishu_agent.providers.openai_sdk.collect_on_demand_evidence",
            return_value={"results": [fake_result]},
        ):
            result = provider.run(request)

        self.assertEqual(fake_client.responses.create.call_count, 3)
        retry_call = fake_client.responses.create.call_args_list[2].kwargs
        self.assertNotIn("previous_response_id", retry_call)
        self.assertEqual(retry_call["input"][0]["type"], "function_call_output")
        self.assertEqual(result.summary, "已检查主机服务")
        self.assertEqual(result.action_events[0].type, ACTION_SECURE_SSH_EXECUTE)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)

    def test_run_falls_back_to_text_followup_when_function_call_output_is_unsupported(self) -> None:
        provider = OpenAIProvider()
        request = ProviderRequest(
            route="rcs",
            question="检查主机服务状态",
            context="已收到：RCS 主机问题",
            evidence=[],
            target="leefung-s1",
        )
        first_response = SimpleNamespace(
            id="resp_exec_1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_exec_1",
                    name="secure_ssh_execute",
                    arguments='{"command":"systemctl status supervisor"}',
                )
            ],
            output_text="",
        )
        final_response = SimpleNamespace(
            id="resp_exec_3",
            output_text='{"summary":"已检查主机服务","root_cause":"supervisor 未运行","severity":"error","next_steps":["拉起 supervisor"],"evidence":["systemctl status supervisor"],"confidence":"medium"}',
        )
        fake_client = SimpleNamespace(responses=SimpleNamespace())
        fake_client.responses.create = Mock(
            side_effect=[
                first_response,
                Exception("previous_response_id is only supported on Responses WebSocket v2"),
                Exception("function_call_output requires item_reference ids matching each call_id on HTTP requests"),
                final_response,
            ]
        )
        fake_result = SimpleNamespace(
            command="systemctl status supervisor",
            returncode=0,
            stdout="supervisor inactive",
            stderr="",
        )

        with patch("feishu_agent.providers.openai_sdk.SETTINGS", None), patch("feishu_agent.providers.openai_sdk.OpenAI", object()), patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://pikachu.claudecode.love",
                "OPENAI_MODEL": "gpt-4.1",
                "OPENAI_ENABLE_TOOL_CALLS": "1",
            },
            clear=False,
        ), patch.object(OpenAIProvider, "_client", return_value=fake_client), patch(
            "feishu_agent.providers.openai_sdk.collect_on_demand_evidence",
            return_value={"results": [fake_result]},
        ):
            result = provider.run(request)

        self.assertEqual(fake_client.responses.create.call_count, 4)
        fallback_call = fake_client.responses.create.call_args_list[3].kwargs
        self.assertNotIn("previous_response_id", fallback_call)
        self.assertEqual(fallback_call["input"][0]["role"], "user")
        self.assertIn("provider_execute[systemctl status supervisor]", fallback_call["input"][0]["content"])
        self.assertEqual(result.summary, "已检查主机服务")
        self.assertEqual(result.action_events[0].type, ACTION_SECURE_SSH_EXECUTE)
        self.assertEqual(result.action_events[-1].type, ACTION_REPORT)


if __name__ == "__main__":
    unittest.main()
