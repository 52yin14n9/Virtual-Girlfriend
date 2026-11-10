from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    content: Any
    error: str | None = None


class BaseTool(ABC):
    name: str
    description: str

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def as_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
