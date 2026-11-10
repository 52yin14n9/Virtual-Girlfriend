from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SkillContext:
    user_input: str
    now: datetime
    services: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    handled: bool
    response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    name: str
    priority: int = 100

    @abstractmethod
    def can_handle(self, context: SkillContext) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, context: SkillContext) -> SkillResult:
        raise NotImplementedError
