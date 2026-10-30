"""Общий тип задачи и схемы ответов для всех наборов."""
from dataclasses import dataclass, field
from typing import Callable

RID = {"type": "string", "pattern": r"^REQ-\d+$"}
MSG = {"type": "string"}
SUCCESS_SCHEMA = {"type": "object", "required": ["success", "message"],
                  "properties": {"success": {"type": "boolean"}, "message": MSG}}


@dataclass
class Task:
    id: str
    scenario: str
    title: str
    prompt: str
    answer_schema: dict
    answer_example: str
    allowed_tools: list
    answer_ok: Callable
    state_ok: Callable
    expected: list = field(default_factory=list)
    faults: dict = field(default_factory=dict)
    requires_observation: bool = False
    source_text: str = ""
    extra_tickets: list = field(default_factory=list)


def g(d, k, default=None):
    return d.get(k, default) if isinstance(d, dict) else default
