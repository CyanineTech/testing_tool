import os
import re
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]

IP_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
HOST_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+|[A-Za-z][A-Za-z0-9_]{2,})(?![A-Za-z0-9_])")
PREFIXED_HOST_RE = re.compile(r"(?:主机|从机|机器人|设备)\s*[:：]?\s*([A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+)")
TIME_KEY_RE = re.compile(r"(?<!\d)(?:\d{1,2}h|\d{8}|\d{4}_\d{2}_\d{2})(?!\d)")
FULL_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-_/](\d{1,2})[-_/](\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?!\d)")
CN_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
SLASH_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")

GENERIC_TARGET_TOKENS = {
    "amr",
    "rcs",
    "ros",
    "wifi",
    "dns",
    "ping",
    "bag",
    "call",
    "service",
    "backend",
    "frontend",
    "request",
    "states",
    "limited_zone",
    "request_states",
    "日志",
    "下一步",
    "继续",
    "查看",
    "问题",
    "什么",
    "导致",
}


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


def extract_target(text: str) -> Optional[str]:
    ip_match = IP_RE.search(text)
    if ip_match:
        return ip_match.group(0)

    prefixed_match = PREFIXED_HOST_RE.search(text)
    if prefixed_match:
        candidate = prefixed_match.group(1)
        if candidate.lower() not in GENERIC_TARGET_TOKENS:
            return candidate

    candidates = HOST_RE.findall(text)
    for candidate in candidates:
        lower_candidate = candidate.lower()
        if lower_candidate in GENERIC_TARGET_TOKENS:
            continue
        if len(candidate) >= 3:
            return candidate
    return None


def infer_target_role(target: str) -> str:
    normalized = (target or "").strip().lower()
    if not normalized:
        return "unknown"
    if normalized == "192.168.1.170":
        return "rcs"
    if re.search(r"(?:^|-)s\d+$", normalized):
        return "rcs"
    if re.search(r"(?:^|-)t\d+$", normalized):
        return "amr"
    if any(token in normalized for token in ("master", "server", "scheduler", "dispatch", "backend", "rcs")):
        return "rcs"
    return "unknown"


def extract_time_key(text: str) -> Optional[str]:
    match = TIME_KEY_RE.search(text)
    if match:
        return match.group(0)

    match = FULL_DATE_RE.search(text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}_{month:02d}_{day:02d}"

    current_year = datetime.now().year
    for pattern in (CN_MONTH_DAY_RE, SLASH_MONTH_DAY_RE):
        match = pattern.search(text)
        if not match:
            continue
        month = int(match.group(1))
        day = int(match.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{current_year}_{month:02d}_{day:02d}"
    return None


def run_command(command: List[str], timeout: int = 1200) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=" ".join(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _collect_output_text(result: CommandResult) -> str:
    parts = [result.stdout or "", result.stderr or ""]
    return "\n".join(part for part in parts if part)


def _read_latest_collect_dir(output: str) -> Optional[Path]:
    match = re.search(r"输出目录:\s*(/tmp/[^\s]+)", output)
    if match:
        collect_dir = Path(match.group(1))
        if collect_dir.exists():
            return collect_dir
    return None


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _build_evidence_excerpt(evidence: str, limit: int = 12) -> str:
    evidence_lines: List[str] = []
    for line in evidence.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("TX:") or stripped.startswith("RX:"):
            continue
        if stripped.startswith("/home/robot/autobag/"):
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in ["drop", "disconnect", "reset", "laser", "scan", "usb", "can", "eb", "motor", "timeout", "error", "caution_"]) or "LaserScan" in line:
            evidence_lines.append(stripped)
    return "\n".join(evidence_lines[-limit:]) if evidence_lines else ""


def _summarize_caution_files(evidence: str, limit: int = 3) -> str:
    caution_files = sorted(set(re.findall(r"caution_[^\s]+\.bag\.zip", evidence)))
    if not caution_files:
        return ""
    preview = "、".join(caution_files[:limit])
    if len(caution_files) > limit:
        preview = f"{preview} 等 {len(caution_files)} 份 caution 录包"
    return preview


def _summarize_amr(evidence: str) -> Dict[str, str]:
    severity = "警告"
    cause = "未发现足够明确的根因"
    if re.search(r"LaserScan.*front|front.*LaserScan|/front_scan|front lidar|front radar", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "前雷达 / 前向 LaserScan 节点存在掉线或数据异常"
    elif re.search(r"LaserScan.*rear|rear.*LaserScan|/rear_scan|rear lidar|rear radar", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "后雷达 / 后向 LaserScan 节点存在掉线或数据异常"
    elif re.search(r"❌\|LaserScan\|.*\(/scan|❌\|LaserScan\|.*front|❌\|LaserScan\|.*rear", evidence):
        severity = "错误"
        cause = "雷达 / LaserScan 节点存在间歇性掉线或启动异常"
    elif re.search(r"The connection was dropped|resume eb_interrupt|reset embedded system|Driving motor error code|CAN bus停止发布数据|cannot read eb|cannot write eb", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "底层嵌入式 / CAN / 电机链路不稳定，导致上层扫描链路间歇中断"
    elif re.search(r"can0: .*ERROR-ACTIVE|pcan_usb|CAN bus|can0", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "CAN / PCAN 链路异常或波动，优先检查底层总线和嵌入式通信"
    elif re.search(r"Intel深度相机|Orbbec深度相机|CH341.*未检测到|以下设备未检测到|未检测到.*USB", evidence):
        severity = "错误"
        cause = "USB 设备枚举异常，可能波及雷达/电机/嵌入式通信"
    elif re.search(r"Velocity command timeout|Stuck timer", evidence, re.IGNORECASE):
        severity = "警告"
        cause = "运动控制链路不稳定，需结合日志确认是否伴随底层通信异常"

    return {
        "severity": severity,
        "cause": cause,
        "evidence": _build_evidence_excerpt(evidence),
    }


def _summarize_historical_amr(evidence: str, time_key: str) -> Dict[str, str]:
    if re.search(r"LaserScan.*front|front.*LaserScan|/front_scan|front lidar|front radar", evidence, re.IGNORECASE):
        return {
            "severity": "错误",
            "cause": f"前雷达 / 前向 LaserScan 在 {time_key} 相关历史证据中存在掉线或数据异常",
            "evidence": _build_evidence_excerpt(evidence),
        }

    if re.search(r"LaserScan.*rear|rear.*LaserScan|/rear_scan|rear lidar|rear radar", evidence, re.IGNORECASE):
        return {
            "severity": "错误",
            "cause": f"后雷达 / 后向 LaserScan 在 {time_key} 相关历史证据中存在掉线或数据异常",
            "evidence": _build_evidence_excerpt(evidence),
        }

    if re.search(r"\[INFO\]\s*未找到日志目录", evidence):
        caution_files = sorted(set(re.findall(r"caution_[^\s]+(?:\.bag\.zip|\.jpg)", evidence)))
        caution_bags = [name for name in caution_files if name.endswith(".bag.zip")]
        if caution_bags:
            cause = f"未找到 {time_key} 对应的 ROS 原始日志；当前只能确认同日存在 {len(caution_bags)} 份 caution 录包，无法仅凭现有文本证据判定具体前/后雷达和直接原因"
        else:
            cause = f"未找到 {time_key} 对应的 ROS 原始日志，现有文本证据不足，无法判定具体掉线雷达和直接原因"
        caution_summary = _summarize_caution_files(evidence)
        return {
            "severity": "警告",
            "cause": cause,
            "evidence": caution_summary,
        }

    return _summarize_amr(evidence)


def _summarize_network(evidence: str) -> Dict[str, str]:
    severity = "警告"
    cause = "网络连通性需要进一步确认"
    if re.search(r"Ping 不通|ping fail|fail", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "目标不可达，优先检查本机网络、路由器或 VPN"
    if re.search(r"SSH 连接失败|authentication|Permission denied", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "网络可达但 SSH 认证失败或权限受限"
    return {"severity": severity, "cause": cause, "evidence": evidence[-800:]}


def _summarize_rcs(evidence: str) -> Dict[str, str]:
    severity = "警告"
    cause = "RCS 服务需要进一步核对"
    if re.search(r"FAIL|down|error|closed|refused|not running|stopped", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "RCS 侧存在服务异常或端口不可用"
    return {"severity": severity, "cause": cause, "evidence": evidence[-800:]}


def diagnose_route(route: str, text: str, target: Optional[str], time_key: Optional[str]) -> Dict[str, object]:
    if route == "unknown":
        return {
            "need_more_info": True,
            "missing": "请补充设备/IP 或主机名，以及现象。",
        }

    if route in {"amr", "network"} and not target:
        return {
            "need_more_info": True,
            "missing": "请补充目标设备/IP 或主机名，我才能自动执行排查。",
        }

    if route == "rcs" and not target:
        target = "192.168.1.170"

    executed: List[Dict[str, object]] = []
    combined_evidence: List[str] = []

    if route == "amr":
        collect_args = ["bash", "scripts/collect_logs.sh", target or ""]
        if time_key:
            collect_args.append(time_key)
        else:
            check_result = run_command(["bash", "scripts/check_amr_status.sh", target or ""])
            executed.append({"command": check_result.command, "returncode": check_result.returncode})
            combined_evidence.append(_collect_output_text(check_result))

        collect_result = run_command(collect_args, timeout=2400)
        executed.append({"command": collect_result.command, "returncode": collect_result.returncode})
        collect_output = _collect_output_text(collect_result)
        combined_evidence.append(collect_output)

        collect_dir = _read_latest_collect_dir(collect_output)
        if collect_dir:
            for filename in ["system_info.txt", "usb_tree.txt", "dmesg.txt", "default_launch.txt", "mobile_base_launch.txt", "pure_laser_amcl.txt", "state_monitor_wrapper.txt", "errors_default.txt", "errors_mobile_base.txt", "radar_keywords.txt", "backend_log.txt", "can_status.txt", "chrony.txt", "caution_files.txt"]:
                combined_evidence.append(_read_text(collect_dir / filename))

        if time_key:
            summary = _summarize_historical_amr("\n".join(combined_evidence), time_key)
        else:
            summary = _summarize_amr("\n".join(combined_evidence))
        return {
            "need_more_info": False,
            "route": route,
            "target": target,
            "executed": executed,
            "severity": summary["severity"],
            "root_cause": summary["cause"],
            "evidence": summary["evidence"],
            "text": text,
        }

    if route == "network":
        result = run_command(["bash", "scripts/network_diag.sh", target or ""])
        executed.append({"command": result.command, "returncode": result.returncode})
        evidence = _collect_output_text(result)
        summary = _summarize_network(evidence)
        return {
            "need_more_info": False,
            "route": route,
            "target": target,
            "executed": executed,
            "severity": summary["severity"],
            "root_cause": summary["cause"],
            "evidence": summary["evidence"],
            "text": text,
        }

    if route == "rcs":
        result = run_command(["bash", "scripts/check_rcs_status.sh", target or "192.168.1.170"])
        executed.append({"command": result.command, "returncode": result.returncode})
        evidence = _collect_output_text(result)
        summary = _summarize_rcs(evidence)
        return {
            "need_more_info": False,
            "route": route,
            "target": target,
            "executed": executed,
            "severity": summary["severity"],
            "root_cause": summary["cause"],
            "evidence": summary["evidence"],
            "text": text,
        }

    return {
        "need_more_info": True,
        "missing": "暂不支持该问题类型，请补充更具体的现象。",
    }


def format_diagnostic_report(report: Dict[str, object], sender_display_name: str) -> str:
    if report.get("need_more_info"):
        return f"@{sender_display_name} {report.get('missing', '请补充信息后重试')}"

    route = report.get("route", "unknown")
    target = report.get("target") or "未指定"
    severity = report.get("severity", "警告")
    cause = report.get("root_cause", "未明确")
    evidence = str(report.get("evidence") or "").strip()
    executed = report.get("executed", [])

    lines: List[str] = [
        f"已收到：{route} 自动排障",
        f"目标：{target}",
        f"严重程度：{severity}",
        f"根因分析：{cause}",
        "已执行检查：",
    ]

    for index, item in enumerate(executed, start=1):
        command = item.get("command", "")
        returncode = item.get("returncode", "")
        lines.append(f"{index}. {command} (rc={returncode})")

    if evidence:
        lines.append("证据摘要：")
        lines.append(evidence)

    lines.append("修复建议：")
    if route == "amr":
        lines.extend([
            "1. 先检查底层嵌入式、电机、CAN 和 USB 供电/连接是否稳定。",
            "2. 如果日志里持续出现 connection dropped / reset embedded system，优先处理 EB/CAN 侧，不要先把责任归到雷达节点。",
            "3. 若仍复现，再按对应时间点取 bag 和 default.launch / mobile_base.launch 深挖。",
        ])
    elif route == "network":
        lines.extend([
            "1. 先确认目标可达性和 SSH 认证。",
            "2. 再检查 WiFi / Tailscale / 路由器链路。",
        ])
    elif route == "rcs":
        lines.extend([
            "1. 先检查主机服务和端口状态。",
            "2. 再看调度中心、数据库和任务队列。",
        ])

    return "\n".join(lines)


def format_diagnostic_markdown(report: Dict[str, object]) -> str:
    if report.get("need_more_info"):
        return f"**需要补充信息**\n- {report.get('missing', '请补充信息后重试')}"

    route = report.get("route", "unknown")
    target = report.get("target") or "未指定"
    severity = report.get("severity", "警告")
    cause = report.get("root_cause", "未明确")
    evidence = str(report.get("evidence") or "").strip()
    executed = report.get("executed", [])

    lines: List[str] = [
        f"**诊断结果**：{route} 自动排障",
        f"**目标**：{target}",
        f"**严重程度**：{severity}",
        f"**根因分析**：{cause}",
        "**已执行检查**：",
    ]

    for index, item in enumerate(executed, start=1):
        command = item.get("command", "")
        returncode = item.get("returncode", "")
        lines.append(f"- {index}. `{command}` (rc={returncode})")

    if evidence:
        lines.append("**证据摘要**：")
        for line in evidence.splitlines()[-12:]:
            cleaned = line.replace("`", "'")
            lines.append(f"- {cleaned}")

    lines.append("**修复建议**：")
    if route == "amr":
        lines.extend([
            "- 先检查底层嵌入式、电机、CAN 和 USB 供电 / 连接是否稳定。",
            "- 如果日志里持续出现 `connection dropped` / `reset embedded system`，优先处理 EB/CAN 侧，不要先把责任归到雷达节点。",
            "- 若仍复现，再按对应时间点取 bag 和 `default.launch` / `mobile_base.launch` 深挖。",
        ])
    elif route == "network":
        lines.extend([
            "- 先确认目标可达性和 SSH 认证。",
            "- 再检查 WiFi / Tailscale / 路由器链路。",
        ])
    elif route == "rcs":
        lines.extend([
            "- 先检查主机服务和端口状态。",
            "- 再看调度中心、数据库和任务队列。",
        ])

    lines.extend([
        "**下一步**：如果你要我用模型复核一遍根因，回复：`模型复核`",
        "**说明**：当前默认以本地脚本和日志结论为准，模型复核是可选步骤。",
    ])

    return "\n".join(lines)
