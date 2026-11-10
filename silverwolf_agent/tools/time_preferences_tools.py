from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..proactive.time_manager import (
    TimeManager,
)


class TimePreferencesGetTool(BaseTool):
    name = "time_preferences_get"
    description = (
        "读取银狼当前的主动关心时间设置。"
    )

    def __init__(
        self,
        manager: TimeManager,
    ) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        return ToolResult(
            ok=True,
            content=(
                self.manager.snapshot()
            ),
        )


class TimePreferencesSetTool(BaseTool):
    name = "time_preferences_set"
    description = (
        "修改早晨、中午或晚上的主动关心时间。"
    )

    def __init__(
        self,
        manager: TimeManager,
    ) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slot": {
                    "type": "string",
                    "enum": [
                        "morning",
                        "noon",
                        "evening",
                    ],
                },
                "time": {
                    "type": "string",
                    "description": "HH:MM",
                },
                "enabled": {
                    "type": "boolean",
                },
                "window_minutes": {
                    "type": "integer",
                },
            },
            "required": [
                "slot",
                "time",
            ],
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        slot = self.manager.set_slot(
            str(arguments["slot"]),
            str(arguments["time"]),
            enabled=(
                bool(arguments["enabled"])
                if "enabled"
                in arguments
                else None
            ),
            window_minutes=(
                int(
                    arguments[
                        "window_minutes"
                    ]
                )
                if "window_minutes"
                in arguments
                else None
            ),
        )
        return ToolResult(
            ok=True,
            content={
                "slot": str(
                    arguments["slot"]
                ),
                "settings": slot,
            },
        )
