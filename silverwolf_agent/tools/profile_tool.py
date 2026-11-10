from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..memory.profile import UserProfileManager


class ProfileUpdateTool(BaseTool):
    name = "profile_update"
    description = (
        "更新用户档案。仅在用户明确提供新的个人事实或明确要求修改档案时使用；"
        "不得根据猜测更新。"
    )

    def __init__(self, manager: UserProfileManager) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "以 stable. 或 dynamic. 开头的档案路径",
                },
                "value": {
                    "description": "要保存的新值",
                },
                "reason": {
                    "type": "string",
                    "description": "用户明确表达的新事实摘要",
                },
            },
            "required": ["path", "value", "reason"],
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path = str(arguments.get("path", ""))
        reason = str(arguments.get("reason", "")).strip()
        if not reason:
            return ToolResult(ok=False, content=None, error="reason 不能为空")
        self.manager.set_path(
            path,
            arguments.get("value"),
            reason=f"agent_tool:{reason}",
        )
        return ToolResult(ok=True, content={"updated": path})
