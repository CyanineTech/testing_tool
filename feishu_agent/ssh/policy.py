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
            "free -h",
            "swapon --show",
            "cat /proc/meminfo",
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
            "systemctl status supervisor --no-pager",
            "systemctl --user status cyanine-os.service",
            "journalctl -n 50 --no-pager",
            "journalctl -u supervisor -n 80 --no-pager",
            "journalctl -u docker -n 80 --no-pager",
            "journalctl -k -n 80 --no-pager",
            "docker logs docker-mysql_5_7-1 --tail 80",
            "docker logs docker-backend_1 --tail 80",
            "docker inspect -f '{{.State.Status}} {{.State.Restarting}} {{.State.ExitCode}}' docker-mysql_5_7-1",
            "docker inspect -f '{{.State.Status}} {{.State.Restarting}} {{.State.ExitCode}}' docker-backend_1",
            "docker exec docker-mysql_5_7-1 mysqladmin ping -u root",
            "curl -s -S -m 3 http://127.0.0.1:3737/infos/ros/",
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
    if route == "amr":
        if re.match(r"^journalctl -k --since '.+' --until '.+' --no-pager$", normalized):
            return True
        if re.match(r"^journalctl --since '.+' --until '.+' --no-pager$", normalized):
            return True
        if normalized in {"free -h", "swapon --show", "cat /proc/meminfo"}:
            return True
    if route == "rcs":
        if re.match(r"^docker logs [a-zA-Z0-9_.-]+ --tail [0-9]+$", normalized):
            return True
        if re.match(r"^docker inspect -f '.*' [a-zA-Z0-9_.-]+$", normalized):
            return True
        if re.match(r"^docker exec [a-zA-Z0-9_.-]+ mysqladmin ping -u [a-zA-Z0-9_.-]+$", normalized):
            return True
        if re.match(r"^systemctl status [a-zA-Z0-9_.@-]+(?: --no-pager)?$", normalized):
            return True
        if re.match(r"^journalctl -u [a-zA-Z0-9_.@-]+ -n [0-9]+ --no-pager$", normalized):
            return True
        if re.match(r"^journalctl -k -n [0-9]+ --no-pager$", normalized):
            return True
        if re.match(r"^curl -s -S -m [0-9]+ http://127\\.0\\.0\\.1:[0-9]+/.*$", normalized):
            return True
    for candidate in allowed:
        if candidate == normalized:
            return True
        if "{target}" in candidate and normalized.startswith(candidate.split("{target}", 1)[0]):
            return True
    return False
