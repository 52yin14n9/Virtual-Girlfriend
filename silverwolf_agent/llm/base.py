from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import ChatMessage, LLMResponse


class BaseLLMClient(ABC):
    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
