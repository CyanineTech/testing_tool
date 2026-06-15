import tempfile
import unittest
from pathlib import Path

from feishu_agent.config import Settings
from feishu_agent.knowledge.loader import load_knowledge_excerpt, normalize_knowledge_path


class KnowledgeLoaderTests(unittest.TestCase):
    def test_load_knowledge_excerpt_prefers_descriptive_lines_over_commands(self) -> None:
        excerpt, error = load_knowledge_excerpt("knowledge/common-faults.md", max_chars=240, max_lines=8)

        self.assertEqual(error, "")
        self.assertIn("常见故障排查指南", excerpt)
        self.assertIn("USB 设备故障", excerpt)
        self.assertNotIn("supervisorctl status", excerpt)
        self.assertNotIn("docker ps", excerpt)
        self.assertNotIn("# 检查后端日志", excerpt)
        self.assertLessEqual(len(excerpt.splitlines()), 8)

    def test_load_knowledge_excerpt_uses_explicit_settings_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="knowledge_") as tmpdir:
            repo_root = Path(tmpdir)
            knowledge_root = repo_root / "knowledge"
            knowledge_root.mkdir(parents=True, exist_ok=True)
            (knowledge_root / "demo.md").write_text(
                "# Demo\n\n这是一条临时知识。\n\nsupervisorctl status\n",
                encoding="utf-8",
            )
            settings = Settings(
                repo_root=repo_root,
                knowledge_root=knowledge_root,
                prompts_root=repo_root / "prompts",
                deploy_root=repo_root / "feishu_agent" / "deploy",
            )

            excerpt, error = load_knowledge_excerpt(
                "knowledge/demo.md",
                max_chars=120,
                max_lines=6,
                settings=settings,
            )

        self.assertEqual(error, "")
        self.assertIn("这是一条临时知识。", excerpt)
        self.assertNotIn("supervisorctl status", excerpt)

    def test_normalize_knowledge_path_maps_legacy_flat_path_to_layered_path(self) -> None:
        normalized, error = normalize_knowledge_path("knowledge/usb-device-troubleshooting.md")

        self.assertEqual(error, "")
        self.assertEqual(normalized, "knowledge/hardware_bus/usb-device-troubleshooting.md")


if __name__ == "__main__":
    unittest.main()
