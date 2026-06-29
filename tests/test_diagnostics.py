import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from feishu_agent.diagnostics import CommandResult, TimeWindow, diagnose_route, extract_exact_time_anchor, extract_target, extract_time_key, extract_time_window, infer_target_role


class DiagnosticsTests(unittest.TestCase):
    def test_extract_target_prefers_prefixed_host(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 为什么失败"

        self.assertEqual(extract_target(text), "leefung-s1")

    def test_extract_time_key_supports_full_timestamp(self) -> None:
        text = "看一下主机leefung-s1这个时间2026-06-11 17:49:39.216 ros call 为什么失败"

        self.assertEqual(extract_time_key(text), "2026_06_11")

    def test_extract_time_window_supports_recent_relative_words(self) -> None:
        anchor = datetime(2026, 6, 15, 20, 0, 0)
        window = extract_time_window("检查刚刚主机为什么死机了", now=anchor)

        self.assertIsNotNone(window)
        self.assertEqual(window.label, "recent_8h")
        self.assertEqual(window.start, "2026-06-15 12:00:00")
        self.assertEqual(window.end, "2026-06-15 20:00:00")

    def test_extract_time_window_supports_today_with_clock_time(self) -> None:
        anchor = datetime(2026, 6, 15, 20, 0, 0)
        window = extract_time_window("今天17:40主机为什么异常", now=anchor)

        self.assertEqual(window.start, "2026-06-15 17:10:00")
        self.assertEqual(window.end, "2026-06-15 18:10:00")

    def test_extract_time_window_supports_explicit_month_day_and_hour(self) -> None:
        anchor = datetime(2026, 6, 15, 20, 0, 0)
        window = extract_time_window("看6月15日15点主机异常", now=anchor)

        self.assertEqual(window.start, "2026-06-15 14:30:00")
        self.assertEqual(window.end, "2026-06-15 15:30:00")

    def test_extract_exact_time_anchor_supports_full_timestamp(self) -> None:
        self.assertEqual(
            extract_exact_time_anchor("排查 2026-06-13 01:14:15 的故障"),
            "2026-06-13 01:14:15",
        )

    def test_infer_target_role_distinguishes_rcs_host(self) -> None:
        self.assertEqual(infer_target_role("leefung-s1"), "rcs")
        self.assertEqual(infer_target_role("leefung-t9"), "amr")

    def test_extract_target_ignores_service_words_without_host_shape(self) -> None:
        self.assertIsNone(extract_target("继续查 supervisor 为什么没运行，查 MySQL 异常的具体原因"))

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

    def test_historical_rcs_prefers_reboot_history_over_current_snapshot(self) -> None:
        calls = []

        def fake_run(command, timeout=1200):
            calls.append(command)
            joined = " ".join(command)
            if "check_rcs_reboot_history.sh" in joined:
                return CommandResult(
                    joined,
                    0,
                    "\n".join(
                        [
                            "当前开机时间: 2026-06-15 08:05:10",
                            "previous boot: 2026-06-14 21:40:52",
                            "provider_execute[curl -s -S -m 3 http://127.0.0.1:3737/infos/ros/]: Connection refused",
                            "provider_execute[docker logs docker-backend_1 --tail 120]: supervisor waiting for master_backend to die",
                            "2026-06-14 21:38:12 ubuntu-170 supervisord[4984]: waiting for master_backend, cbs_master_server to die",
                        ]
                    ),
                    "",
                )
            raise AssertionError(f"unexpected command: {joined}")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
            report = diagnose_route("rcs", "主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因", "192.168.1.170", None)

        self.assertEqual(len(calls), 1)
        self.assertIn("check_rcs_reboot_history.sh", " ".join(calls[0]))
        self.assertIn("应优先排查 backend / supervisor 拉起链路", report["root_cause"])
        self.assertIn("最近一次重启前的 boot 时间", report["evidence"])
        self.assertIn("关键 supervisor 线索", report["evidence"])

    def test_historical_rcs_passes_time_window_into_reboot_history_script(self) -> None:
        calls = []

        def fake_run(command, timeout=1200):
            calls.append(command)
            return CommandResult(" ".join(command), 0, "previous boot: 2026-06-14 21:40:52\n", "")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run), \
            patch("feishu_agent.diagnostics.extract_time_window", return_value=TimeWindow(
                start="2026-06-15 17:10:00",
                end="2026-06-15 18:10:00",
                label="2026-06-15 17:40:00",
            )):
            diagnose_route("rcs", "今天17:40主机为什么死机了", "192.168.1.170", None)

        self.assertIn("2026-06-15 17:10:00", " ".join(calls[0]))
        self.assertIn("2026-06-15 18:10:00", " ".join(calls[0]))

    def test_historical_network_passes_time_window_into_network_diag(self) -> None:
        calls = []

        def fake_run(command, timeout=1200):
            calls.append(command)
            return CommandResult(" ".join(command), 0, "wifi reconnect\n", "")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run), \
            patch("feishu_agent.diagnostics.extract_time_window", return_value=TimeWindow(
                start="2026-06-15 17:10:00",
                end="2026-06-15 18:10:00",
                label="2026-06-15 17:40:00",
            )):
            report = diagnose_route("network", "今天17:40网络掉线", "192.168.1.250", None)

        self.assertIn("network_diag.sh", " ".join(calls[0]))
        self.assertIn("2026-06-15 17:10:00", " ".join(calls[0]))
        self.assertIn("2026-06-15 18:10:00", " ".join(calls[0]))
        self.assertIn("17:40:00", report["root_cause"])

    def test_historical_amr_passes_time_window_into_collect_logs(self) -> None:
        calls = []

        def fake_run(command, timeout=1200):
            calls.append(command)
            return CommandResult(" ".join(command), 0, "[INFO] 未找到日志目录\n", "")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run), \
            patch("feishu_agent.diagnostics.extract_time_window", return_value=TimeWindow(
                start="2026-06-15 17:10:00",
                end="2026-06-15 18:10:00",
                label="2026-06-15 17:40:00",
            )):
            diagnose_route("amr", "刚刚从机leefung-t9为什么掉线了", "leefung-t9", None)

        self.assertIn("collect_logs.sh", " ".join(calls[0]))
        self.assertIn("2026-06-15 17:10:00", " ".join(calls[0]))
        self.assertIn("2026-06-15 18:10:00", " ".join(calls[0]))

    def test_historical_amr_prefers_exact_timestamp_over_date_key(self) -> None:
        calls = []

        def fake_run(command, timeout=1200):
            calls.append(command)
            return CommandResult(" ".join(command), 0, "[INFO] 未找到日志目录\n", "")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
            diagnose_route("amr", "排查从机 leefung-t9 在 2026-06-13 01:14:15 的故障", "leefung-t9", "2026_06_13")

        joined = " ".join(calls[0])
        self.assertIn("collect_logs.sh", joined)
        self.assertIn("2026-06-13 00:44:15", joined)
        self.assertIn("2026-06-13 01:44:15", joined)
        self.assertIn("2026-06-13 01:14:15", joined)
        self.assertNotIn("collect_logs.sh leefung-t9 2026_06_13", joined)

    def test_historical_amr_exact_window_evidence_refines_root_cause(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "mobile_base_exact.txt").write_text(
                "[1781284454.100000000] connection dropped\n[1781284455.200000000] reset embedded system\n",
                encoding="utf-8",
            )
            (collect_dir / "state_monitor_exact.txt").write_text(
                "[1781284461.000000000] switch to manual\n[1781284463.000000000] pause\n",
                encoding="utf-8",
            )

            def fake_run(command, timeout=1200):
                return CommandResult(
                    command=" ".join(command),
                    returncode=0,
                    stdout=f"输出目录: {collect_dir}\n日志目录: /home/robot/log/not_permanent/2026_06_12-14_05_04\n",
                    stderr="",
                )

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "排查从机 v001 在 2026-06-13 01:14:15 的故障", "v001", "2026_06_13")

        self.assertIn("mobile_base.launch 先出现 CAN / EB / driver 异常", report["root_cause"])
        self.assertIn("switch to manual", report["evidence"])

    def test_historical_amr_exact_window_without_time_key_still_uses_historical_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "mobile_base_exact.txt").write_text(
                "[1781284454.100000000] connection dropped\n",
                encoding="utf-8",
            )
            (collect_dir / "kernel_window_keywords.txt").write_text(
                "",
                encoding="utf-8",
            )

            def fake_run(command, timeout=1200):
                return CommandResult(
                    command=" ".join(command),
                    returncode=0,
                    stdout=f"输出目录: {collect_dir}\n日志目录: /home/robot/log/not_permanent/2026_06_12-14_05_04\n",
                    stderr="",
                )

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "排查从机 v001 在 2026-06-13 01:14:15 的故障", "v001", None)

        self.assertIn("2026-06-13 01:14:15 前后秒级证据", report["root_cause"])
        self.assertIn("不支持把 swap 作为首发根因", report["root_cause"])

    def test_historical_amr_memory_pressure_is_reported_as_parallel_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "mobile_base_exact.txt").write_text(
                "[1781284454.100000000] connection dropped\n",
                encoding="utf-8",
            )
            (collect_dir / "kernel_window_keywords.txt").write_text(
                "kernel: kswapd0: node 0, zone DMA32\nkernel: Out of memory: Killed process 1234\n",
                encoding="utf-8",
            )

            def fake_run(command, timeout=1200):
                return CommandResult(
                    command=" ".join(command),
                    returncode=0,
                    stdout=f"输出目录: {collect_dir}\n日志目录: /home/robot/log/not_permanent/2026_06_12-14_05_04\n",
                    stderr="",
                )

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "排查从机 v001 在 2026-06-13 01:14:15 的故障", "v001", None)

        self.assertIn("内存 / swap 压力线索", report["root_cause"])
        self.assertIn("Out of memory", report["evidence"])

    def test_historical_amr_reads_error_monitor_from_permanent_boot_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amr_diag_") as tmpdir:
            collect_dir = Path(tmpdir)
            (collect_dir / "mobile_base_exact.txt").write_text(
                "[1781284454.100000000] connection dropped\n",
                encoding="utf-8",
            )
            (collect_dir / "error_monitor_exact.txt").write_text(
                "[1781284458.000000000] code=34100017 trigger\n",
                encoding="utf-8",
            )

            def fake_run(command, timeout=1200):
                return CommandResult(
                    command=" ".join(command),
                    returncode=0,
                    stdout=f"输出目录: {collect_dir}\n日志目录: /home/robot/log/not_permanent/2026_06_12-14_05_04\n",
                    stderr="",
                )

            with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
                report = diagnose_route("amr", "排查从机 v001 在 2026-06-13 01:14:15 的故障", "v001", None)

        self.assertIn("34100017", report["evidence"])

    def test_historical_rcs_can_still_summarize_when_reboot_script_returns_nonzero(self) -> None:
        def fake_run(command, timeout=1200):
            joined = " ".join(command)
            if "check_rcs_reboot_history.sh" in joined:
                return CommandResult(
                    joined,
                    127,
                    "\n".join(
                        [
                            "[WARN] 上一个 boot 的 backend/mysql 日志获取失败",
                            "previous boot: 2026-06-14 21:40:52",
                            "2026-06-14 21:38:12 ubuntu-170 supervisord[4984]: waiting for master_backend, cbs_master_server to die",
                        ]
                    ),
                    "",
                )
            raise AssertionError(f"unexpected command: {joined}")

        with patch("feishu_agent.diagnostics.run_command", side_effect=fake_run):
            report = diagnose_route("rcs", "主机192.168.1.170今天出现了一次死机，重启才恢复正常检查原因", "192.168.1.170", None)

        self.assertEqual(report["severity"], "错误")
        self.assertIn("master_backend", report["root_cause"])
        self.assertIn("关键 supervisor 线索", report["evidence"])


if __name__ == "__main__":
    unittest.main()
