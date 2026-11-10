from __future__ import annotations

from typing import Any

from .base import BaseLLMClient
from ..models import ChatMessage, LLMResponse


class EchoLLMClient(BaseLLMClient):
    """无 Key 时使用的离线客户端。"""

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        last = messages[-1].content if messages else ""
        return LLMResponse(
            text=f"离线测试模式已接入。你刚才说：{last}"
        )
