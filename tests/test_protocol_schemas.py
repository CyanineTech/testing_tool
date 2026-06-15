import unittest

from feishu_agent.protocols.schemas import (
    DraftResult,
    ExecutionResult,
    OrchestratorRunResult,
    ReportResult,
    RouteResult,
    TraceEntry,
)


class ProtocolSchemasTests(unittest.TestCase):
    def test_route_result_defaults(self) -> None:
        result = RouteResult(
            domain="hardware_bus",
            sop_path="knowledge/hardware_bus/can_bus_error.md",
            sop_text="# CAN SOP",
        )

        self.assertEqual(result.domain, "hardware_bus")
        self.assertEqual(result.matched_keywords, [])
        self.assertEqual(result.route_reason, "")

    def test_execution_result_fields(self) -> None:
        result = ExecutionResult(
            ok=True,
            type="secure_ssh_execute",
            command="ip -details link show can0",
            stdout="state UP",
            stderr="",
            return_code=0,
            duration_ms=123,
            provider="openai_sdk",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.rejection_reason, None)
        self.assertEqual(result.host, "")

    def test_report_result_defaults(self) -> None:
        result = ReportResult(
            summary="CAN 异常",
            root_cause="总线错误",
            severity="critical",
        )

        self.assertEqual(result.next_steps, [])
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.confidence, 0.0)
        self.assertFalse(result.human_intervention_required)

    def test_draft_result_sets_created_at(self) -> None:
        result = DraftResult(
            draft_path="knowledge/_ai_drafts/can_bus_error.md",
            title="CAN 总线异常草稿",
            source_sop="knowledge/hardware_bus/can_bus_error.md",
        )

        self.assertTrue(result.created_at)
        self.assertIn("T", result.created_at)

    def test_orchestrator_run_result_exports_conversation_state(self) -> None:
        result = OrchestratorRunResult(
            final_answer="排障完成",
            messages=[{"role": "assistant", "content": "排障完成"}],
            trace=[TraceEntry.from_mapping({"type": "knowledge_candidates", "route": "network", "target": "192.168.1.250"})],
            sop_path="knowledge/common-faults.md",
            domain="network",
            reply_kind="progress",
            route="network",
            target="192.168.1.250",
            time_key="2026_06_13",
            conversation_key="chat_1:root_1",
            step_index=2,
            draft_result=DraftResult(
                draft_path="knowledge/_ai_drafts/network_case.md",
                title="网络排障草稿",
                source_sop="knowledge/common-faults.md",
            ),
        )

        state = result.to_conversation_state()

        self.assertEqual(state["route"], "network")
        self.assertEqual(state["target"], "192.168.1.250")
        self.assertEqual(state["time_key"], "2026_06_13")
        self.assertEqual(state["step_index"], 2)
        self.assertEqual(state["reply_kind"], "progress")
        self.assertEqual(state["domain"], "network")
        self.assertEqual(state["sop_path"], "knowledge/common-faults.md")
        self.assertEqual(state["draft_path"], "knowledge/_ai_drafts/network_case.md")


if __name__ == "__main__":
    unittest.main()
