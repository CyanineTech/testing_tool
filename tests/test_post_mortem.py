import os
import tempfile
import unittest

from feishu_agent.core.post_mortem import PostMortem


class PostMortemTests(unittest.TestCase):
    def test_generate_draft_writes_under_drafts_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="drafts_") as tmpdir:
            post_mortem = PostMortem(tmpdir)
            result = post_mortem.generate_draft(
                conversation=[
                    {"role": "user", "content": "AMR 叉货有问题"},
                    {"role": "assistant", "content": "先检查叉货到位和 CAN 链路"},
                ],
                answer="当前结论：叉货到位失败，建议检查托盘偏位。",
                sop_path="knowledge/task_dispatch/fork-pickup-misalignment.md",
            )

            self.assertTrue(result.draft_path.startswith(os.path.realpath(tmpdir)))
            self.assertTrue(os.path.exists(result.draft_path))
            with open(result.draft_path, "r", encoding="utf-8") as fh:
                text = fh.read()

        self.assertIn("SOP 路径：knowledge/task_dispatch/fork-pickup-misalignment.md", text)
        self.assertIn("最终结论", text)
        self.assertIn("AMR 叉货有问题", text)

    def test_generate_draft_uses_trace_for_key_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="drafts_") as tmpdir:
            post_mortem = PostMortem(tmpdir)
            result = post_mortem.generate_draft(
                conversation=[],
                answer="已确认 CAN 异常。",
                sop_path="knowledge/hardware_bus/can-eb-communication-abnormal.md",
                trace=[
                    {
                        "type": "local_execution",
                        "command": "ip -details link show can0",
                        "returncode": 0,
                    }
                ],
            )

            with open(result.draft_path, "r", encoding="utf-8") as fh:
                text = fh.read()

        self.assertIn("关键命令", text)
        self.assertIn("ip -details link show can0", text)


if __name__ == "__main__":
    unittest.main()
