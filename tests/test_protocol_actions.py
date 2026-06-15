import unittest

from feishu_agent.protocols.actions import (
    ACTION_READ_KNOWLEDGE,
    ACTION_REPORT,
    ACTION_SECURE_SSH_EXECUTE,
    ActionEvent,
    build_action_event,
    is_valid_action_type,
)


class ProtocolActionsTests(unittest.TestCase):
    def test_valid_action_types_are_recognized(self) -> None:
        self.assertTrue(is_valid_action_type(ACTION_READ_KNOWLEDGE))
        self.assertTrue(is_valid_action_type(ACTION_SECURE_SSH_EXECUTE))
        self.assertTrue(is_valid_action_type(ACTION_REPORT))
        self.assertFalse(is_valid_action_type("execute"))

    def test_build_action_event_creates_expected_fields(self) -> None:
        event = build_action_event(
            action_type=ACTION_READ_KNOWLEDGE,
            source="openai_sdk",
            payload={"path": "knowledge/common-faults.md"},
        )

        self.assertEqual(event.type, ACTION_READ_KNOWLEDGE)
        self.assertEqual(event.source, "openai_sdk")
        self.assertEqual(event.payload["path"], "knowledge/common-faults.md")
        self.assertTrue(event.action_id)
        self.assertIn("T", event.created_at)

    def test_action_event_rejects_unsupported_type(self) -> None:
        with self.assertRaises(ValueError):
            ActionEvent(
                type="execute",
                source="copilot_cli",
                payload={"command": "ip a"},
            )


if __name__ == "__main__":
    unittest.main()
