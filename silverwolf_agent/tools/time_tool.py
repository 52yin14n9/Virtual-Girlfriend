from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .base import BaseTool, ToolResult


class CurrentTimeTool(BaseTool):
    name = "time_now"
    description = (
        "获取当前日期、时间、时区和星期。"
    )

    def __init__(
        self,
        timezone: str = "Asia/Shanghai",
        now_provider: (
            Callable[[], datetime] | None
        ) = None,
    ) -> None:
        self.timezone = timezone
        self._now_provider = now_provider

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
        if self._now_provider is None:
            now = datetime.now(
                ZoneInfo(self.timezone)
            )
        else:
            now = self._now_provider()
            if now.tzinfo is None:
                now = now.replace(
                    tzinfo=ZoneInfo(
                        self.timezone
                    )
                )
            else:
                now = now.astimezone(
                    ZoneInfo(
                        self.timezone
                    )
                )

        return ToolResult(
            ok=True,
            content={
                "iso": now.isoformat(
                    timespec="seconds"
                ),
                "date": now.strftime(
                    "%Y-%m-%d"
                ),
                "time": now.strftime(
                    "%H:%M:%S"
                ),
                "weekday": now.strftime(
                    "%A"
                ),
                "weekday_cn": {
                    0: "星期一",
                    1: "星期二",
                    2: "星期三",
                    3: "星期四",
                    4: "星期五",
                    5: "星期六",
                    6: "星期日",
                }[now.weekday()],
                "timezone": self.timezone,
            },
        )
