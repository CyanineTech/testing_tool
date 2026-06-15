from dataclasses import dataclass
from typing import Dict, List
import re


@dataclass(frozen=True)
class CommandPolicy:
    route: str
    commands: List[str]


POLICIES: Dict[str, CommandPolicy] = {
    "amr": CommandPolicy(
        route="amr",
        commands=[
            "rostopic echo /robot_state -n1",
            "rosnode list",
            "rostopic echo /low_level_error -n1",
            "ip -s -d link show can0",
            "lsusb -t",
            "chronyc sources",
            "find /home/robot/log/not_permanent -maxdepth 4 \\( -type f -o -type l \\) -name 'caution*'",
            "find /home/robot -maxdepth 5 \\( -type f -o -type l \\) -name '*bag*'",
        ],
    ),
    "network": CommandPolicy(
        route="network",
        commands=[
            "ping -c 3 {target}",
            "ip a",
            "ip route",
            "chronyc sources",
        ],
    ),
    "rcs": CommandPolicy(
        route="rcs",
        commands=[
            "docker ps --format '{{.Names}} {{.Status}}'",
            "systemctl --user status cyanine-os.service",
            "journalctl -n 50 --no-pager",
        ],
    ),
}


def allowed_commands_for_route(route: str) -> List[str]:
    policy = POLICIES.get(route)
    return list(policy.commands) if policy else []


def validate_command(route: str, command: str) -> bool:
    allowed = allowed_commands_for_route(route)
    normalized = command.strip()
    if route in {"amr", "rcs"}:
        if re.match(r"^(?:find|grep|tail|head|awk|ls)\b", normalized):
            return True
    for candidate in allowed:
        if candidate == normalized:
            return True
        if "{target}" in candidate and normalized.startswith(candidate.split("{target}", 1)[0]):
            return True
    return False
