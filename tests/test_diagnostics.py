import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_agent.diagnostics import CommandResult, diagnose_route, extract_target, extract_time_key, infer_target_role


class DiagnosticsTests(unittest.TestCase):
    def test_extract_target_prefers_prefixed_host(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 为什么失败"

        self.assertEqual(extract_target(text), "leefung-s1")

    def test_extract_time_key_supports_full_timestamp(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 为什么失败"

        self.assertEqual(extract_time_key(text), "2026_06_11")

    def test_infer_target_role_distinguishes_rcs_host(self) -> None:
        self.assertEqual(infer_target_role("leefung-s1"), "rcs")
        self.assertEqual(infer_target_role("leefung-t9"), "amr")

    def test_historical_amr_uses_only_time_scoped_collect_and_reports_missing_logs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "caution_files.txt").write_text(
                "caution_T9_20260607_154805.bag.zip\n"
                "caution_T9_20260607_154850.bag.zip\n",
                encoding="utf-8",
            )
            (collect_dir / "can_status.txt").write_text(
                "TX: bytes  packets  errors  dropped carrier collsns\n"
                "can0: ERROR-ACTIVE\n",
                encoding="utf-8",
            )

            calls = []

            def fake_run(command, timeout=1200):
                calls.append(command)
                self.assertNotIn("check_amr_status.sh", " ".join(command))
                return CommandResult(
                    command=" ".join(command),
                    returncode=0,
                    stdout=f"输出目录: {collect_dir}\n  [INFO] 未找到日志目录\n",
                    stderr="",
                )

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "看下从机leefung-t9在6月7日掉线的是哪个雷达", "leefung-t9", "2026_06_07")

            self.assertEqual(len(calls), 1)
            self.assertIn("collect_logs.sh", " ".join(calls[0]))
            self.assertIn("未找到 2026_06_07 对应的 ROS 原始日志", report["root_cause"])
            self.assertIn("2 份 caution 录包", report["root_cause"])
            self.assertIn("caution_T9_20260607_154805.bag.zip", report["evidence"])
            self.assertNotIn("TX: bytes", report["evidence"])
            self.assertNotIn("can0:", report["evidence"])

    def test_current_amr_still_runs_snapshot_and_collect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "can_status.txt").write_text("can0: ERROR-ACTIVE\n", encoding="utf-8")

            calls = []

            def fake_run(command, timeout=1200):
                calls.append(command)
                joined = " ".join(command)
                if "check_amr_status.sh" in joined:
                    return CommandResult(joined, 0, "can0: ERROR-ACTIVE\n", "")
                return CommandResult(joined, 0, f"输出目录: {collect_dir}\n日志目录: /home/robot/log/not_permanent/2026_06_11\n", "")

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "看下当前状态", "leefung-t9", None)

            self.assertEqual(len(calls), 2)
            self.assertIn("check_amr_status.sh", " ".join(calls[0]))
            self.assertIn("collect_logs.sh", " ".join(calls[1]))
            self.assertEqual(report["severity"], "错误")
            self.assertIn("CAN / PCAN", report["root_cause"])


if __name__ == "__main__":
    unittest.main()
