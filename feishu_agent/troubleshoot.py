from typing import Dict, List, Optional


PLAYBOOKS: Dict[str, Dict[str, object]] = {
    "network": {
        "title": "网络问题",
        "summary": "先确认机器人到主机的连通性，再看 WiFi、Tailscale、DNS 和 1300D 路由器。",
        "first_check": "bash scripts/network_diag.sh <amr_ip_or_hostname>",
        "next_steps": [
            "确认能否 ping 通机器人和 RCS 主机",
            "确认 SSH 是否只卡在认证，不是网络不可达",
            "查看 WiFi / Tailscale / 路由器状态",
        ],
        "docs": ["knowledge/common-faults.md", "knowledge/system-architecture.md"],
    },
    "amr": {
        "title": "AMR 机器人问题",
        "summary": "优先看本机状态、USB / CAN / 电机 / 定位 / 相机，再结合日志和 bag 定位。",
        "first_check": "bash scripts/check_amr_status.sh <amr_ip_or_hostname>",
        "next_steps": [
            "确认 /low_level_error 和 ROS 节点状态",
            "检查 USB、CAN、相机和电机相关异常",
            "如果涉及取货 / 叉货，再看对应时间段 bag 和日志",
        ],
        "docs": ["knowledge/common-faults.md", "knowledge/error-codes.md", "knowledge/error-tracing-methods.md"],
    },
    "rcs": {
        "title": "RCS 主机问题",
        "summary": "先看主机状态、调度中心、后端服务和消息链路，再看任务系统与日志。",
        "first_check": "bash scripts/check_rcs_status.sh 192.168.1.170",
        "next_steps": [
            "确认后端、调度中心和数据库是否正常",
            "确认机器人是否在线、任务是否在队列中",
            "查看任务系统和后端日志定位异常",
        ],
        "docs": ["knowledge/task_dispatch/rcs-task-system.md", "knowledge/error-tracing-methods.md"],
    },
    "unknown": {
        "title": "待分类问题",
        "summary": "先补充设备、现象、时间、影响范围，再决定走网络、AMR 还是 RCS 分支。",
        "first_check": "请补充：设备/IP、现象、发生时间、影响范围",
        "next_steps": [
            "说明是 AMR 从机还是 RCS 主机",
            "说明是否能 SSH / ping 通",
            "说明是否伴随错误码、日志或 bag 片段",
        ],
        "docs": ["README.md", "prompts/troubleshoot.prompt.md"],
    },
}


def build_troubleshoot_plan(route: str, text: str) -> Dict[str, object]:
    playbook = PLAYBOOKS.get(route, PLAYBOOKS["unknown"])
    return {
        "route": route,
        "title": playbook["title"],
        "summary": playbook["summary"],
        "first_check": playbook["first_check"],
        "next_steps": playbook["next_steps"],
        "docs": playbook["docs"],
        "input": text,
    }


def get_step_text(plan: Dict[str, object], step_index: int) -> Optional[str]:
    next_steps = plan.get("next_steps", [])
    if step_index < 0 or step_index >= len(next_steps):
        return None
    return next_steps[step_index]


def format_troubleshoot_plan(plan: Dict[str, object], step_index: int = 0) -> str:
    next_steps = plan.get("next_steps", [])
    docs = plan.get("docs", [])
    current_step = get_step_text(plan, step_index)

    lines: List[str] = [
        f"已收到：{plan.get('title', '问题')}",
        f"摘要：{plan.get('summary', '')}",
        f"首查命令：{plan.get('first_check', '')}",
    ]

    if current_step:
        lines.append(f"当前步骤：{step_index + 1}. {current_step}")
    else:
        lines.append("当前步骤：已没有下一步，建议直接收集日志或 bag 证据。")

    if next_steps and step_index + 1 < len(next_steps):
        lines.append("后续步骤：")
        for index, step in enumerate(next_steps[step_index + 1 :], start=step_index + 2):
            lines.append(f"{index}. {step}")

    if docs:
        lines.append(f"候选文档：{'、'.join(docs)}")

    return "\n".join(lines)
