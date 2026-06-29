import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from feishu_agent.knowledge.schema import PlaybookSchema


PLAYBOOK_DOCS: Dict[str, PlaybookSchema] = {
    "knowledge": PlaybookSchema(
        route="knowledge",
        title="知识库查询",
        summary="优先读取 knowledge 目录中的文档，再基于文档内容做总结或回答。",
        first_check="列出 knowledge 目录中的可用文档并读取相关文档内容",
        next_steps=[
            "列出 knowledge 目录中的候选文档",
            "读取与问题最相关的文档内容",
            "基于文档内容生成结构化总结",
        ],
        docs=["README.md"],
    ),
    "amr": PlaybookSchema(
        route="amr",
        title="AMR 机器人问题",
        summary="优先看本机状态、USB / CAN / 电机 / 定位 / 相机，再结合日志和 bag 定位。",
        first_check="bash scripts/check_amr_status.sh <amr_ip_or_hostname>",
        next_steps=[
            "确认 /low_level_error 和 ROS 节点状态",
            "检查 USB、CAN、相机和电机相关异常",
            "如果涉及取货 / 叉货，再看对应时间段 bag 和日志",
        ],
        docs=[],
    ),
    "network": PlaybookSchema(
        route="network",
        title="网络问题",
        summary="先确认机器人到主机的连通性，再看 WiFi、Tailscale、DNS 和 1300D 路由器。",
        first_check="bash scripts/network_diag.sh <amr_ip_or_hostname>",
        next_steps=[
            "确认能否 ping 通机器人和 RCS 主机",
            "确认 SSH 是否只卡在认证，不是网络不可达",
            "查看 WiFi / Tailscale / 路由器状态",
        ],
        docs=[],
    ),
    "rcs": PlaybookSchema(
        route="rcs",
        title="RCS 主机问题",
        summary="先看主机状态、调度中心、后端服务和消息链路，再看任务系统与日志。",
        first_check="bash scripts/check_rcs_status.sh 192.168.1.170",
        next_steps=[
            "确认后端、调度中心和数据库是否正常",
            "确认机器人是否在线、任务是否在队列中",
            "查看任务系统和后端日志定位异常",
        ],
        docs=[],
    ),
    "unknown": PlaybookSchema(
        route="unknown",
        title="待分类问题",
        summary="先补充设备、现象、时间、影响范围，再决定走网络、AMR 还是 RCS 分支。",
        first_check="请补充：设备/IP、现象、发生时间、影响范围",
        next_steps=[
            "说明是 AMR 从机还是 RCS 主机",
            "说明是否能 SSH / ping 通",
            "说明是否伴随错误码、日志或 bag 片段",
        ],
        docs=["README.md", "prompts/troubleshoot.prompt.md"],
    ),
}

_ROUTE_DIRECTORY_MAP: Dict[str, List[str]] = {
    "amr": ["hardware_bus", "ros", "task_dispatch", "cbs"],
    "network": ["network"],
    "rcs": ["backend", "task_dispatch", "cbs"],
}

_ROUTE_TOP_LEVEL_DOCS: Dict[str, List[str]] = {
    "amr": [
        "knowledge/common-faults.md",
        "knowledge/error-codes.md",
        "knowledge/error-tracing-methods.md",
        "knowledge/log-paths.md",
        "knowledge/cpu-high.md",
    ],
    "network": [
        "knowledge/common-faults.md",
        "knowledge/system-architecture.md",
        "knowledge/log-paths.md",
    ],
    "rcs": [
        "knowledge/common-faults.md",
        "knowledge/system-architecture.md",
        "knowledge/error-tracing-methods.md",
        "knowledge/log-paths.md",
        "knowledge/error-codes.md",
        "knowledge/deployment-ops.md",
    ],
}

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md)\)")
_TOKEN_PATTERN = re.compile(r"[0-9a-zA-Z]+|[\u4e00-\u9fff]+")


def resolve_playbook(route: str) -> PlaybookSchema:
    base = PLAYBOOK_DOCS.get(route, PLAYBOOK_DOCS["unknown"])
    if route not in _ROUTE_DIRECTORY_MAP:
        return base
    return PlaybookSchema(
        route=base.route,
        title=base.title,
        summary=base.summary,
        first_check=base.first_check,
        next_steps=list(base.next_steps),
        docs=_default_docs_for_route(route),
    )


def match_symptom(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ["knowledge", "文档", "目录", "知识库", "readme"]):
        return "knowledge"
    if any(keyword in lowered for keyword in ["cpu", "占用", "负载", "高负载", "过高", "吃满", "卡顿", "卡住", "变慢", "超慢"]):
        if any(keyword in text for keyword in ["RCS", "主机", "调度", "派发", "后台", "服务", "数据库", "任务"]):
            return "rcs"
        return "amr"
    if any(keyword in text for keyword in ["bag", "取货", "放货", "叉货", "定位", "相机", "usb", "can", "雷达", "激光", "雷射", "lidar", "laser", "scan", "扫描", "amr", "从机", "机器人", "AGV"]):
        return "amr"
    if any(keyword in text for keyword in ["RCS", "主机", "调度", "派发", "后台"]):
        return "rcs"
    if any(keyword in lowered for keyword in ["wifi", "dns", "ping", "tailscale", "掉线", "网络", "连不上"]):
        return "network"
    return "unknown"


def match_supporting_docs(text: str, route: str) -> List[str]:
    if route == "knowledge":
        return _knowledge_inventory()
    query_tokens = set(_tokenize(text))
    docs: List[str] = []
    for doc in _linked_docs_for_route(route):
        doc_tokens = _load_doc_match_tokens(doc)
        if query_tokens & doc_tokens:
            docs.append(doc)
    for doc in _boosted_docs_for_query(text, route):
        if doc not in docs:
            docs.append(doc)
    return docs


def _boosted_docs_for_query(text: str, route: str) -> List[str]:
    lowered = text.lower()
    boosted: List[str] = []

    if route == "amr":
        if (
            any(keyword in lowered for keyword in ["uvcvideo", "pcan", "ch341", "usb", "can"])
            and any(keyword in text for keyword in ["摄像头", "相机", "雷达", "总线", "嵌入式"])
        ):
            boosted.extend(
                [
                    "knowledge/hardware_bus/usb-device-troubleshooting.md",
                    "knowledge/hardware_bus/can-eb-communication-abnormal.md",
                    "knowledge/hardware_bus/history-case-usb-can-cascade-failure.md",
                ]
            )
        if any(keyword in text for keyword in ["定位", "丢失", "漂移", "重定位", "tf", "地图", "切图", "scan"]):
            boosted.extend(
                [
                    "knowledge/ros/location-loss.md",
                    "knowledge/ros/tf-tree-incomplete-or-jumping.md",
                    "knowledge/ros/map-loading-or-switch-failure.md",
                    "knowledge/ros/history-case-location-ok-but-map-or-tf-mismatch.md",
                ]
            )
        if any(keyword in text for keyword in ["任务卡住", "状态不推进", "状态不动", "回执", "事件没回", "执行到一半"]):
            boosted.extend(
                [
                    "knowledge/task_dispatch/task-state-not-advancing.md",
                    "knowledge/task_dispatch/history-case-task-sent-but-no-state-feedback.md",
                    "knowledge/task_dispatch/event-condition-not-satisfied.md",
                ]
            )

    if route == "network":
        if any(keyword in text for keyword in ["漫游", "电梯口", "多楼层", "移动就掉线", "某个位置掉线"]):
            boosted.extend(
                [
                    "knowledge/network/wifi-roaming-instability.md",
                    "knowledge/network/customer-site-multi-floor-or-elevator-network-special-cases.md",
                ]
            )

    if route == "rcs":
        if any(keyword in text for keyword in ["重启后恢复", "服务拉起失败", "端口不通", "3737", "supervisor"]):
            boosted.extend(
                [
                    "knowledge/backend/rcs-backend-service-failure.md",
                    "knowledge/backend/history-case-rcs-host-reboot-recovers-but-backend-chain-broken.md",
                ]
            )

    selected: List[str] = []
    for doc in boosted:
        if doc not in selected:
            selected.append(doc)
    return selected


def _knowledge_inventory() -> List[str]:
    knowledge_dir = _knowledge_root()
    if not knowledge_dir.exists():
        return []
    return [
        str(path.relative_to(knowledge_dir.parent)).replace("\\", "/")
        for path in sorted(knowledge_dir.rglob("*.md"))
        if "_ai_drafts" not in path.parts
    ]


def _knowledge_root() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge"


def _extract_markdown_links(relative_path: str) -> List[str]:
    path = _knowledge_root().parent / relative_path
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8", errors="ignore")
    selected: List[str] = []
    for raw_link in _MARKDOWN_LINK_RE.findall(content):
        normalized = raw_link.strip().replace("\\", "/")
        if normalized.startswith("../"):
            resolved = (path.parent / normalized).resolve()
            try:
                relative = resolved.relative_to(_knowledge_root().parent)
            except ValueError:
                continue
            normalized = str(relative).replace("\\", "/")
        elif not normalized.startswith("knowledge/"):
            parent_relative = path.parent.relative_to(_knowledge_root())
            normalized = f"knowledge/{parent_relative.as_posix()}/{normalized}"
            normalized = normalized.replace("/./", "/")
        if normalized.endswith(".md") and normalized not in selected:
            selected.append(normalized)
    return selected


def _route_readmes(route: str) -> List[str]:
    return [f"knowledge/{directory}/README.md" for directory in _ROUTE_DIRECTORY_MAP.get(route, [])]


def _linked_docs_for_route(route: str) -> List[str]:
    docs: List[str] = []
    for readme_path in _route_readmes(route):
        for doc in _extract_markdown_links(readme_path):
            if doc not in docs:
                docs.append(doc)
    return docs


def _default_docs_for_route(route: str) -> List[str]:
    docs: List[str] = []
    for doc in _ROUTE_TOP_LEVEL_DOCS.get(route, []):
        if doc not in docs:
            docs.append(doc)
    for readme_path in _route_readmes(route):
        if readme_path not in docs:
            docs.append(readme_path)
    return docs


def _load_doc_match_tokens(doc: str) -> Set[str]:
    root = _knowledge_root().parent
    path = root / doc
    stem_tokens = _tokenize(Path(doc).stem.replace("-", " ").replace("_", " "))
    if not path.exists():
        return set(stem_tokens)
    content = path.read_text(encoding="utf-8", errors="ignore")
    sample_lines: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        sample_lines.append(stripped)
        if len(sample_lines) >= 12:
            break
    content_tokens = _tokenize(" ".join(sample_lines))
    return set(stem_tokens + content_tokens)


def _doc_stem_tokens(doc: str) -> Set[str]:
    return set(_tokenize(Path(doc).stem.replace("-", " ").replace("_", " ")))


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    for chunk in _TOKEN_PATTERN.findall(text.lower()):
        if not chunk:
            continue
        if all("\u4e00" <= ch <= "\u9fff" for ch in chunk):
            if len(chunk) <= 2:
                tokens.append(chunk)
            else:
                for index in range(len(chunk) - 1):
                    tokens.append(chunk[index : index + 2])
                if len(chunk) <= 4:
                    tokens.append(chunk)
            continue
        if len(chunk) >= 2:
            tokens.append(chunk)
    seen: List[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen


def select_relevant_docs(text: str, route: str, limit: int = 6) -> List[str]:
    limit = max(1, limit)
    playbook = resolve_playbook(route)
    supporting = match_supporting_docs(text, route)
    inventory = _knowledge_inventory()
    query_tokens = set(_tokenize(text))
    lowered = text.lower()
    linked_docs = set(_linked_docs_for_route(route))

    scored: List[Tuple[int, int, str]] = []
    for index, doc in enumerate(inventory):
        score = 0
        if doc in playbook.docs:
            score += 100
        if doc in supporting:
            score += 140
        if doc in linked_docs:
            score += 24
        doc_tokens = _load_doc_match_tokens(doc)
        stem_tokens = _doc_stem_tokens(doc)
        for token in query_tokens:
            if token in doc_tokens:
                score += 8
            if token in stem_tokens:
                score += 18
        if route in _ROUTE_DIRECTORY_MAP:
            for directory in _ROUTE_DIRECTORY_MAP[route]:
                if f"/{directory}/" in doc:
                    score += 6
                    if not doc.endswith("/README.md"):
                        score += 14
                        if directory == "task_dispatch" and any(
                            keyword in text for keyword in ["任务", "状态", "回执", "事件", "卡住", "推进"]
                        ):
                            score += 18
                            if "history-case-task-sent-but-no-state-feedback" in doc:
                                score += 30
                        if directory == "ros" and any(
                            keyword in text for keyword in ["定位", "tf", "地图", "漂移", "重定位"]
                        ):
                            score += 18
                        if directory == "hardware_bus" and any(
                            keyword in lowered for keyword in ["usb", "can", "pcan", "ch341", "uvcvideo"]
                        ):
                            score += 18
        if doc.endswith("/README.md"):
            score -= 20
        elif doc.count("/") <= 1 and doc.startswith("knowledge/"):
            score -= 18
        if route == "knowledge":
            score += 5
        if score > 0:
            scored.append((-score, index, doc))

    if not scored:
        return list(playbook.docs)[:limit]

    selected: List[str] = []
    for _, _, doc in sorted(scored):
        if doc not in selected:
            selected.append(doc)
        if len(selected) >= limit:
            break
    return selected
