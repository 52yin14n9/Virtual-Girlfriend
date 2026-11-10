from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..memory.profile import UserProfileManager


class PreferredNameTool(BaseTool):
    name = "profile_set_preferred_name"
    description = (
        "保存用户明确要求使用的称呼。"
        "只有用户明确说以后叫他某个名字时才使用。"
    )

    def __init__(
        self,
        manager: UserProfileManager,
    ) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "用户要求使用的新称呼",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        name = str(
            arguments.get("name", "")
        ).strip()
        if not name:
            return ToolResult(
                ok=False,
                content=None,
                error="name 不能为空",
            )

        self.manager.set_preferred_name(
            name,
            reason=(
                "pae_explicit_name_preference"
            ),
        )
        return ToolResult(
            ok=True,
            content={
                "preferred_name": (
                    self.manager.preferred_name()
                ),
            },
        )
