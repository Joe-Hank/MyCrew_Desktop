from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class PromptCtx:
    project_id: str = ""
    task_id: str = ""
    request_id: str = ""
    title: str = ""


@dataclass
class Choice:
    value: str
    label: str


class InteractionPort(Protocol):
    async def prompt_choice(self, ctx: PromptCtx, options: list[Choice]) -> str: ...
    async def prompt_text(self, ctx: PromptCtx, hint: str = "") -> str: ...
    async def prompt_confirm(self, ctx: PromptCtx) -> bool: ...
