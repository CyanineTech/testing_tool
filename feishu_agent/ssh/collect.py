from typing import Dict, List, Optional, Sequence

from feishu_agent.config import Settings
from feishu_agent.sandbox.ssh_executor import SandboxResult, execute_readonly_action
from feishu_agent.ssh.policy import allowed_commands_for_route


def collect_evidence(
    route: str,
    target: str,
    commands: Optional[Sequence[str]] = None,
    settings: Optional[Settings] = None,
) -> Dict[str, object]:
    requested_commands = list(commands or allowed_commands_for_route(route))
    results: List[SandboxResult] = [
        execute_readonly_action(route, target, command, settings=settings)
        for command in requested_commands
    ]
    return {
        "route": route,
        "target": target,
        "commands": requested_commands,
        "results": results,
    }


def collect_amr_evidence(target: str, settings: Optional[Settings] = None) -> Dict[str, object]:
    return collect_evidence("amr", target, settings=settings)


def collect_network_evidence(target: str, settings: Optional[Settings] = None) -> Dict[str, object]:
    return collect_evidence("network", target, settings=settings)


def collect_rcs_evidence(target: str, settings: Optional[Settings] = None) -> Dict[str, object]:
    return collect_evidence("rcs", target, settings=settings)


def collect_on_demand_evidence(
    route: str,
    target: str,
    command: str,
    settings: Optional[Settings] = None,
) -> Dict[str, object]:
    return collect_evidence(route, target, commands=[command], settings=settings)
