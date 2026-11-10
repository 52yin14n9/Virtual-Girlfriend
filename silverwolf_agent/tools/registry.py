from __future__ import annotations

from typing import Any
import re

from .base import BaseTool, ToolResult


TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError("Tool name 不能为空")
        if not TOOL_NAME_PATTERN.fullmatch(tool.name):
            raise ValueError(
                "Tool name 只能包含英文字母、数字、下划线或连字符，且长度为 1-64："
                f"{tool.name!r}"
            )
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, content=None, error=f"未知工具：{name}")
        try:
            return tool.run(arguments)
        except Exception as exc:
            return ToolResult(ok=False, content=None, error=str(exc))

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.as_anthropic_schema() for tool in self._tools.values()]
