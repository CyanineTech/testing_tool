import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_agent.config import LlmSettings, ProviderSettings, Settings, SshSettings, SystemSettings
from feishu_agent.deploy.cli import main as deploy_main
from feishu_agent.deploy.github_sync import check_remote_version, sync_from_github
from feishu_agent.deploy.manifest import load_manifest, validate_manifest
from feishu_agent.deploy.rollback import list_deploy_history, record_deploy, rollback_to_version


def make_settings(repo_root: Path) -> Settings:
    return Settings(
        repo_root=repo_root,
        knowledge_root=repo_root / "knowledge",
        prompts_root=repo_root / "prompts",
        deploy_root=repo_root / "feishu_agent" / "deploy",
        provider=ProviderSettings(),
        llm=LlmSettings(),
        ssh=SshSettings(),
        system=SystemSettings(),
    )


class DeployTests(unittest.TestCase):
    def test_manifest_has_no_overlap(self) -> None:
        manifest = load_manifest()
        issues = validate_manifest(manifest)
        self.assertEqual(issues, [])

    def test_record_and_list_deploy_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = make_settings(Path(tmp_dir))
            record_deploy("abc123", "2026-06-09 10:00:00", "dry-run", settings=settings)
            history = list_deploy_history(settings=settings)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].version, "abc123")
            self.assertEqual(
                rollback_to_version("abc123", settings=settings),
                "rollback target found: abc123 at 2026-06-09 10:00:00",
            )

    def test_deploy_cli_history_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = make_settings(Path(tmp_dir))
            record_deploy("abc123", "2026-06-09 10:00:00", "dry-run", settings=settings)
            exit_code = deploy_main(["history"], settings=settings)
            self.assertEqual(exit_code, 0)

    def test_sync_from_github_returns_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = make_settings(Path(tmp_dir))
            result = sync_from_github(dry_run=True, settings=settings)
        self.assertEqual(result.action, "sync_from_github")
        self.assertTrue(result.notes)

    def test_check_remote_version_returns_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = make_settings(Path(tmp_dir))
            result = check_remote_version(settings=settings)
        self.assertEqual(result.action, "check_remote_version")


if __name__ == "__main__":
    unittest.main()
