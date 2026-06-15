from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class PlaybookSchema:
    route: str
    title: str
    summary: str
    first_check: str
    next_steps: List[str]
    docs: List[str]
