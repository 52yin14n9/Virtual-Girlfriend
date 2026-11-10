from __future__ import annotations

from typing import Any

from .base import (
    BaseTool,
    ToolResult,
)
from ..memory.short_term import (
    ShortTermMemory,
)


class ConversationHistoryLookupTool(
    BaseTool
):
    name = (
        "conversation_history_lookup"
    )
    description = (
        "查询最近用户消息的精确时间。"
        "用于回答“我刚才问的时候”或"
        "“我开始休息的时候”之类问题。"
    )

    def __init__(
        self,
        memory: ShortTermMemory,
    ) -> None:
        self.memory = memory

    @property
    def input_schema(
        self,
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "latest",
                        "keyword",
                    ],
                },
                "keyword": {
                    "type": "string",
                },
            },
            "required": ["mode"],
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[
            str,
            Any,
        ],
    ) -> ToolResult:
        mode = str(
            arguments.get(
                "mode",
                "",
            )
        )
        keyword = str(
            arguments.get(
                "keyword",
                "",
            )
        )

        try:
            turn = (
                self.memory
                .find_user_turn(
                    mode=mode,
                    keyword=keyword,
                )
            )
        except ValueError as exc:
            return ToolResult(
                ok=False,
                content=None,
                error=str(exc),
            )

        if turn is None:
            return ToolResult(
                ok=True,
                content={
                    "found": False,
                    "mode": mode,
                    "keyword": keyword,
                },
            )

        return ToolResult(
            ok=True,
            content={
                "found": True,
                "mode": mode,
                "keyword": keyword,
                "user_text": str(
                    turn.get(
                        "user",
                        "",
                    )
                ),
                "user_at": str(
                    turn.get(
                        "user_at",
                        turn.get(
                            "at",
                            "",
                        ),
                    )
                ),
                "assistant_at": str(
                    turn.get(
                        "assistant_at",
                        "",
                    )
                ),
            },
        )
