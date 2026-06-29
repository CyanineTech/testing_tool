import os
import re
import subprocess
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]

IP_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
HOST_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+|[A-Za-z][A-Za-z0-9_]*\d[A-Za-z0-9_]*)(?![A-Za-z0-9_])")
PREFIXED_HOST_RE = re.compile(r"(?:主机|从机|机器人|设备)\s*[:：]?\s*([A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+|[A-Za-z][A-Za-z0-9_]*\d[A-Za-z0-9_]*|[A-Za-z][A-Za-z0-9_]*)")
TIME_KEY_RE = re.compile(r"(?<!\d)(?:\d{1,2}h|\d{8}|\d{4}_\d{2}_\d{2})(?!\d)")
FULL_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-_/](\d{1,2})[-_/](\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?!\d)")
CN_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
SLASH_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")
TIME_OF_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?::(\d{2}))?(?!\d)")
CN_HOUR_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[点时](?:\s*(\d{1,2})\s*分?)?")
RELATIVE_HISTORY_RE = re.compile(r"(刚刚|刚才|今天|今天早些时候|今天上午|今天下午|今天晚上)")
MEMORY_PRESSURE_RE = re.compile(
    r"oom|out of memory|killed process|kswapd|swap|page allocation failure|allocstall|memory pressure|"
    r"invoked oom-killer|compact_stall",
    re.IGNORECASE,
)

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
    "api",
    "backend",
    "controller",
    "daemon",
    "db",
    "docker",
    "dispatch",
    "gateway",
    "日志",
    "下一步",
    "继续",
    "查看",
    "问题",
    "什么",
    "导致",
    "mongo",
    "mongodb",
    "mysql",
    "postgres",
    "redis",
    "scheduler",
    "service",
    "supervisor",
    "task",
    "worker",
}


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TimeWindow:
    start: str
    end: str
    label: str


def extract_target(text: str) -> Optional[str]:
    def _normalize(candidate: str) -> str:
        return str(candidate or "").strip().strip(".,;:，。！？")

    def _is_plausible_target(candidate: str, *, prefixed: bool = False) -> bool:
        normalized = _normalize(candidate)
        if not normalized:
            return False
        lower_candidate = normalized.lower()
        if lower_candidate in GENERIC_TARGET_TOKENS:
            return False
        if IP_RE.fullmatch(normalized):
            return True
        if prefixed:
            return True
        return bool(re.search(r"[\d_-]", normalized))

    ip_match = IP_RE.search(text)
    if ip_match:
        return ip_match.group(0)

    prefixed_match = PREFIXED_HOST_RE.search(text)
    if prefixed_match:
        candidate = _normalize(prefixed_match.group(1))
        if _is_plausible_target(candidate, prefixed=True):
            return candidate

    candidates = HOST_RE.findall(text)
    for candidate in candidates:
        if _is_plausible_target(candidate):
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


def extract_exact_time_anchor(text: str, now: Optional[datetime] = None) -> Optional[str]:
    current = now or datetime.now()
    normalized = str(text or "").strip()
    if not normalized:
        return None

    full_date_match = FULL_DATE_RE.search(normalized)
    time_of_day_match = TIME_OF_DAY_RE.search(normalized)
    cn_hour_match = CN_HOUR_RE.search(normalized)

    if full_date_match and time_of_day_match:
        year = int(full_date_match.group(1))
        month = int(full_date_match.group(2))
        day = int(full_date_match.group(3))
        hour = int(time_of_day_match.group(1))
        minute = int(time_of_day_match.group(2))
        second = int(time_of_day_match.group(3) or 0)
        return _format_ts(datetime(year, month, day, hour, minute, second))

    if full_date_match and cn_hour_match:
        year = int(full_date_match.group(1))
        month = int(full_date_match.group(2))
        day = int(full_date_match.group(3))
        hour = int(cn_hour_match.group(1))
        minute = int(cn_hour_match.group(2) or 0)
        return _format_ts(datetime(year, month, day, hour, minute, 0))

    for pattern in (CN_MONTH_DAY_RE, SLASH_MONTH_DAY_RE):
        match = pattern.search(normalized)
        if not match:
            continue
        month = int(match.group(1))
        day = int(match.group(2))
        year = current.year
        if time_of_day_match:
            hour = int(time_of_day_match.group(1))
            minute = int(time_of_day_match.group(2))
            second = int(time_of_day_match.group(3) or 0)
            return _format_ts(datetime(year, month, day, hour, minute, second))
        if cn_hour_match:
            hour = int(cn_hour_match.group(1))
            minute = int(cn_hour_match.group(2) or 0)
            return _format_ts(datetime(year, month, day, hour, minute, 0))

    if "今天" in normalized and time_of_day_match:
        hour = int(time_of_day_match.group(1))
        minute = int(time_of_day_match.group(2))
        second = int(time_of_day_match.group(3) or 0)
        return _format_ts(datetime(current.year, current.month, current.day, hour, minute, second))

    if "今天" in normalized and cn_hour_match:
        hour = int(cn_hour_match.group(1))
        minute = int(cn_hour_match.group(2) or 0)
        return _format_ts(datetime(current.year, current.month, current.day, hour, minute, 0))

    return None


def _format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def extract_time_window(text: str, now: Optional[datetime] = None) -> Optional[TimeWindow]:
    current = now or datetime.now()
    normalized = str(text or "").strip()
    if not normalized:
        return None

    full_date_match = FULL_DATE_RE.search(normalized)
    time_of_day_match = TIME_OF_DAY_RE.search(normalized)
    cn_hour_match = CN_HOUR_RE.search(normalized)

    if full_date_match:
        year = int(full_date_match.group(1))
        month = int(full_date_match.group(2))
        day = int(full_date_match.group(3))
        hour = 0
        minute = 0
        second = 0
        if time_of_day_match:
            hour = int(time_of_day_match.group(1))
            minute = int(time_of_day_match.group(2))
            second = int(time_of_day_match.group(3) or 0)
            anchor = datetime(year, month, day, hour, minute, second)
            return TimeWindow(
                start=_format_ts(anchor - timedelta(minutes=30)),
                end=_format_ts(anchor + timedelta(minutes=30)),
                label=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
            )
        if cn_hour_match:
            hour = int(cn_hour_match.group(1))
            minute = int(cn_hour_match.group(2) or 0)
            anchor = datetime(year, month, day, hour, minute, second)
            return TimeWindow(
                start=_format_ts(anchor - timedelta(minutes=30)),
                end=_format_ts(anchor + timedelta(minutes=30)),
                label=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
            )
        day_start = datetime(year, month, day, 0, 0, 0)
        day_end = datetime(year, month, day, 23, 59, 59)
        return TimeWindow(
            start=_format_ts(day_start),
            end=_format_ts(day_end),
            label=f"{year:04d}-{month:02d}-{day:02d}",
        )

    for pattern in (CN_MONTH_DAY_RE, SLASH_MONTH_DAY_RE):
        match = pattern.search(normalized)
        if not match:
            continue
        month = int(match.group(1))
        day = int(match.group(2))
        year = current.year
        if time_of_day_match:
            hour = int(time_of_day_match.group(1))
            minute = int(time_of_day_match.group(2))
            second = int(time_of_day_match.group(3) or 0)
            anchor = datetime(year, month, day, hour, minute, second)
            return TimeWindow(
                start=_format_ts(anchor - timedelta(minutes=30)),
                end=_format_ts(anchor + timedelta(minutes=30)),
                label=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
            )
        if cn_hour_match:
            hour = int(cn_hour_match.group(1))
            minute = int(cn_hour_match.group(2) or 0)
            anchor = datetime(year, month, day, hour, minute, 0)
            return TimeWindow(
                start=_format_ts(anchor - timedelta(minutes=30)),
                end=_format_ts(anchor + timedelta(minutes=30)),
                label=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00",
            )
        day_start = datetime(year, month, day, 0, 0, 0)
        day_end = datetime(year, month, day, 23, 59, 59)
        return TimeWindow(
            start=_format_ts(day_start),
            end=_format_ts(day_end),
            label=f"{year:04d}-{month:02d}-{day:02d}",
        )

    if "今天" in normalized and (time_of_day_match or cn_hour_match):
        if time_of_day_match:
            hour = int(time_of_day_match.group(1))
            minute = int(time_of_day_match.group(2))
            second = int(time_of_day_match.group(3) or 0)
        else:
            hour = int(cn_hour_match.group(1))
            minute = int(cn_hour_match.group(2) or 0)
            second = 0
        anchor = datetime(current.year, current.month, current.day, hour, minute, second)
        return TimeWindow(
            start=_format_ts(anchor - timedelta(minutes=30)),
            end=_format_ts(anchor + timedelta(minutes=30)),
            label=f"{anchor:%Y-%m-%d %H:%M:%S}",
        )

    if "今天" in normalized:
        return TimeWindow(
            start=_format_ts(datetime(current.year, current.month, current.day, 0, 0, 0)),
            end=_format_ts(current),
            label="today",
        )

    if any(token in normalized for token in ("刚刚", "刚才")):
        return TimeWindow(
            start=_format_ts(current - timedelta(hours=8)),
            end=_format_ts(current),
            label="recent_8h",
        )

    if time_of_day_match:
        hour = int(time_of_day_match.group(1))
        minute = int(time_of_day_match.group(2))
        second = int(time_of_day_match.group(3) or 0)
        anchor = datetime(current.year, current.month, current.day, hour, minute, second)
        return TimeWindow(
            start=_format_ts(anchor - timedelta(minutes=30)),
            end=_format_ts(anchor + timedelta(minutes=30)),
            label=f"{anchor:%Y-%m-%d %H:%M:%S}",
        )

    if cn_hour_match:
        hour = int(cn_hour_match.group(1))
        minute = int(cn_hour_match.group(2) or 0)
        anchor = datetime(current.year, current.month, current.day, hour, minute, 0)
        return TimeWindow(
            start=_format_ts(anchor - timedelta(minutes=30)),
            end=_format_ts(anchor + timedelta(minutes=30)),
            label=f"{anchor:%Y-%m-%d %H:%M:%S}",
        )

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


def _extract_memory_pressure_lines(evidence: str, limit: int = 4) -> List[str]:
    lines: List[str] = []
    for line in evidence.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if MEMORY_PRESSURE_RE.search(stripped):
            lines.append(stripped)
    return lines[:limit]


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
    exact_mobile = []
    exact_default = []
    exact_state = []
    exact_error_monitor = []
    memory_pressure_lines = _extract_memory_pressure_lines(evidence)
    for line in evidence.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in ("connection dropped", "reset embedded system", "cannot read eb", "cannot write eb", "can bus", "pcan", "driver")):
            exact_mobile.append(stripped)
        if any(token in lowered for token in ("laserscan", "front radar", "rear radar", "laser", "scan", "error_list timeout", "registererror2")):
            exact_default.append(stripped)
        if any(token in lowered for token in ("switch to manual", "manual", "recover", "resume", "retry", "release", "paused", "pause")):
            exact_state.append(stripped)
        if any(token in lowered for token in ("341", "registererror", "error_monitor", "trigger", "解除", "clear", "code=")):
            exact_error_monitor.append(stripped)

    if exact_mobile and exact_state:
        cause = (
            f"{time_key} 前后秒级证据显示 mobile_base.launch 先出现 CAN / EB / driver 异常，"
            "随后 state_monitor_wrapper 出现手动/恢复/暂停线索；首发更像底层通信异常，恢复动作属于派生表现。"
        )
        evidence_lines = (exact_mobile[:2] + exact_state[:2] + exact_error_monitor[:2])[:6]
        if memory_pressure_lines:
            cause += " 同时间窗口还能看到内存 / swap 压力线索，需要并列怀疑资源抖动放大了底层通信失稳。"
            evidence_lines.extend(memory_pressure_lines[:2])
        else:
            cause += " 同时间窗口未见 OOM / swap / 明显内存压力证据，现有证据不支持把 swap 作为首发根因。"
        return {
            "severity": "错误",
            "cause": cause,
            "evidence": "\n".join(evidence_lines[:6]),
        }

    if exact_mobile:
        cause = f"{time_key} 前后秒级证据显示 mobile_base.launch 中存在 CAN / EB / driver 异常，优先按底层通信链路失稳解释本次故障。"
        evidence_lines = list((exact_mobile[:4] + exact_error_monitor[:2])[:6])
        if memory_pressure_lines:
            cause += " 同时间窗口还出现了内存 / swap 压力线索，需要继续核对资源抖动是否放大了通信异常。"
            evidence_lines.extend(memory_pressure_lines[:2])
        else:
            cause += " 同时间窗口未见 OOM / swap / 明显内存压力证据，现有证据不支持把 swap 作为首发根因。"
        return {
            "severity": "错误",
            "cause": cause,
            "evidence": "\n".join(evidence_lines[:6]),
        }

    if exact_default:
        cause = f"{time_key} 前后秒级证据显示扫描链路存在异常，需结合底层链路继续判断它是否为首发问题。"
        evidence_lines = list((exact_default[:4] + exact_error_monitor[:2])[:6])
        if memory_pressure_lines:
            cause += " 同时间窗口还出现了内存 / swap 压力线索，但当前仍缺少能直接证明其先于扫描异常出现的证据。"
            evidence_lines.extend(memory_pressure_lines[:2])
        return {
            "severity": "错误",
            "cause": cause,
            "evidence": "\n".join(evidence_lines[:6]),
        }

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

    if memory_pressure_lines:
        return {
            "severity": "警告",
            "cause": f"{time_key} 前后窗口内出现内存 / swap 压力线索，但当前还缺少足够证据证明它已经传导为首发硬件链路异常。",
            "evidence": "\n".join(memory_pressure_lines[:4]),
        }

    return _summarize_amr(evidence)


def _is_historical_amr_request(text: str, time_key: Optional[str]) -> bool:
    normalized = str(text or "").strip()
    if time_key:
        return True
    if extract_exact_time_anchor(normalized):
        return True
    if extract_time_window(normalized):
        return True
    return bool(RELATIVE_HISTORY_RE.search(normalized))


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


def _summarize_historical_network(evidence: str, window: TimeWindow) -> Dict[str, str]:
    severity = "错误"
    cause = f"{window.label} 前后网络历史证据不足，仍需继续核对对应时间窗口的链路日志。"
    if re.search(r"disconnect|reconnect|carrier|wifi|wlan", evidence, re.IGNORECASE):
        cause = f"{window.label} 前后存在网络链路抖动或无线侧异常，优先回看 WiFi / 网卡 / 路由链路历史日志。"
    if re.search(r"tailscale|vpn", evidence, re.IGNORECASE):
        cause = f"{window.label} 前后存在 VPN / Tailscale 侧历史异常，需核对 overlay 网络是否中断。"
    if re.search(r"ssh|authentication|permission denied", evidence, re.IGNORECASE):
        cause = f"{window.label} 前后存在 SSH 认证或链路异常，需区分当时是认证失败还是网络不可达。"
    lines = [line.strip() for line in evidence.splitlines() if line.strip()]
    return {"severity": severity, "cause": cause, "evidence": "\n".join(lines[-6:])}


def _summarize_rcs(evidence: str) -> Dict[str, str]:
    severity = "警告"
    cause = "RCS 服务需要进一步核对"
    if re.search(r"FAIL|down|error|closed|refused|not running|stopped", evidence, re.IGNORECASE):
        severity = "错误"
        cause = "RCS 侧存在服务异常或端口不可用"
    return {"severity": severity, "cause": cause, "evidence": evidence[-800:]}


def _is_historical_rcs_request(text: str, time_key: Optional[str]) -> bool:
    normalized = str(text or "").lower()
    if time_key:
        return True
    if extract_time_window(text):
        return True
    return any(token in normalized for token in ("死机", "重启才恢复", "重启后恢复", "历史", "之前"))


def is_historical_rcs_request(text: str, time_key: Optional[str]) -> bool:
    return _is_historical_rcs_request(text, time_key)


def _summarize_historical_rcs(evidence: str) -> Dict[str, str]:
    severity = "错误"
    cause = "重启前历史证据不足，仍需继续核对上一个 boot 的系统与服务日志。"
    evidence_lines: List[str] = []
    backend_refused = re.search(r"Connection refused", evidence, re.IGNORECASE) and "127.0.0.1:3737" in evidence
    supervisor_backend_issue = re.search(r"master_backend|cbs_master_server", evidence, re.IGNORECASE)
    mysql_auth_mismatch = re.search(r"Access denied", evidence, re.IGNORECASE) and re.search(r"mysqladmin", evidence, re.IGNORECASE)

    def add(line: str) -> None:
        cleaned = str(line or "").strip()
        if cleaned and cleaned not in evidence_lines:
            evidence_lines.append(cleaned)

    def extract_focus_line(pattern: str) -> Optional[str]:
        for line in evidence.splitlines():
            stripped = line.strip()
            if re.search(pattern, stripped, re.IGNORECASE):
                return stripped
        return None

    previous_boot_match = re.search(r"previous boot:\s*([^\n]+)", evidence, re.IGNORECASE)
    if previous_boot_match:
        add(f"最近一次重启前的 boot 时间：{previous_boot_match.group(1).strip()}")

    if backend_refused:
        cause = "重启前后端 3737 端口未监听，说明主业务 backend 当时未正常拉起。"
        add("重启前后端 API 3737 端口连接被拒绝，说明主业务服务当时未监听。")

    if supervisor_backend_issue:
        cause = "重启前 supervisor 托管的 backend 链路存在退出/等待结束异常，优先排查 master_backend 拉起失败。"
        add("重启前 supervisor 日志出现 master_backend / cbs_master_server 退出或等待结束记录。")
        focus_line = extract_focus_line(r"master_backend|cbs_master_server|backoff|spawnerr|fatal|waiting for")
        if focus_line:
            add(f"关键 supervisor 线索：{focus_line}")

    if mysql_auth_mismatch:
        add("MySQL 容器在运行，但当前看到的是探活鉴权不匹配，不应直接判成数据库宕机。")

    if backend_refused and supervisor_backend_issue and mysql_auth_mismatch:
        cause = (
            "重启前 3737 端口未监听，且 supervisor 日志显示 master_backend / cbs_master_server 异常退出或等待结束；"
            "应优先排查 backend / supervisor 拉起链路，MySQL 当前更像探活鉴权不匹配而非容器宕机。"
        )
    elif backend_refused and supervisor_backend_issue:
        cause = (
            "重启前 3737 端口未监听，且 supervisor 日志显示 master_backend / cbs_master_server 异常退出或等待结束；"
            "应优先排查 backend / supervisor 拉起链路。"
        )

    if re.search(r"-- no entries --", evidence, re.IGNORECASE) and re.search(r"kernel", evidence, re.IGNORECASE):
        add("上一个 boot 的 kernel 日志未见明显系统级报错。")
    if re.search(r"-- no entries --", evidence, re.IGNORECASE) and re.search(r"docker", evidence, re.IGNORECASE):
        add("上一个 boot 的 docker 服务日志未见明显异常。")

    if not evidence_lines:
        for line in evidence.splitlines():
            stripped = line.strip()
            if stripped:
                evidence_lines.append(stripped)
            if len(evidence_lines) >= 6:
                break

    return {
        "severity": severity,
        "cause": cause,
        "evidence": "\n".join(evidence_lines[:6]),
    }


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
        time_window = extract_time_window(text)
        exact_anchor = extract_exact_time_anchor(text)
        historical_request = _is_historical_amr_request(text, time_key)
        if exact_anchor and time_window:
            collect_args.extend(["", time_window.start, time_window.end, exact_anchor])
        elif time_window:
            collect_args.extend(["", time_window.start, time_window.end])
        elif time_key:
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
            for filename in [
                "system_info.txt",
                "usb_tree.txt",
                "dmesg.txt",
                "default_launch.txt",
                "mobile_base_launch.txt",
                "pure_laser_amcl.txt",
                "state_monitor_wrapper.txt",
                "errors_default.txt",
                "errors_mobile_base.txt",
                "radar_keywords.txt",
                "backend_log.txt",
                "can_status.txt",
                "chrony.txt",
                "caution_files.txt",
                "kernel_window.txt",
                "kernel_window_keywords.txt",
                "system_window_keywords.txt",
                "default_launch_window.txt",
                "mobile_base_window.txt",
                "state_monitor_window.txt",
                "error_monitor_server.txt",
                "error_monitor_window.txt",
                "exact_window_meta.txt",
                "default_launch_exact.txt",
                "mobile_base_exact.txt",
                "state_monitor_exact.txt",
                "error_monitor_exact.txt",
            ]:
                combined_evidence.append(_read_text(collect_dir / filename))

        if historical_request:
            historical_label = exact_anchor or time_key or (time_window.label if time_window else "") or "历史时间窗口"
            summary = _summarize_historical_amr("\n".join(combined_evidence), historical_label)
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
        time_window = extract_time_window(text)
        command = ["bash", "scripts/network_diag.sh", target or ""]
        if time_window:
            command.extend([time_window.start, time_window.end])
        result = run_command(command)
        executed.append({"command": result.command, "returncode": result.returncode})
        evidence = _collect_output_text(result)
        summary = _summarize_historical_network(evidence, time_window) if time_window else _summarize_network(evidence)
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
        if _is_historical_rcs_request(text, time_key):
            time_window = extract_time_window(text)
            command = ["bash", "scripts/check_rcs_reboot_history.sh", target or "192.168.1.170"]
            if time_window:
                command.extend([time_window.start, time_window.end])
            result = run_command(command)
            executed.append({"command": result.command, "returncode": result.returncode})
            evidence = _collect_output_text(result)
            summary = _summarize_historical_rcs(evidence)
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
