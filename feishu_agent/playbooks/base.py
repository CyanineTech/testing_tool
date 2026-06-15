from dataclasses import dataclass
from typing import Dict, List

from feishu_agent.knowledge.index import resolve_playbook
from feishu_agent.knowledge.schema import PlaybookSchema


@dataclass(frozen=True)
class PlaybookStep:
    index: int
    text: str


@dataclass(frozen=True)
class Playbook:
    route: str
    title: str
    summary: str
    first_check: str
    steps: List[PlaybookStep]
    docs: List[str]


def build_playbook(route: str) -> Playbook:
    schema: PlaybookSchema = resolve_playbook(route)
    steps = [PlaybookStep(index=idx + 1, text=step) for idx, step in enumerate(schema.next_steps)]
    return Playbook(
        route=schema.route,
        title=schema.title,
        summary=schema.summary,
        first_check=schema.first_check,
        steps=steps,
        docs=schema.docs,
    )


def next_step(playbook: Playbook, step_index: int) -> str:
    if step_index < 0 or step_index >= len(playbook.steps):
        return "当前步骤：已没有下一步，建议直接收集日志或 bag 证据。"
    return f"当前步骤：{playbook.steps[step_index].index}. {playbook.steps[step_index].text}"


def is_complete(playbook: Playbook, step_index: int) -> bool:
    return step_index >= len(playbook.steps)
