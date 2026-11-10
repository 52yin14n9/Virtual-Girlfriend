from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..proactive.plan_manager import (
    PlanManager,
)
from ..proactive.schedule_intent import clean_schedule_title


class PlanCreateTool(BaseTool):
    name = "plan_create"
    description = (
        "创建需要未来主动提醒的持久计划。"
        "只有 Planner 判断事项重要且需要提醒时使用。"
    )

    def __init__(
        self,
        manager: PlanManager,
    ) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                },
                "details": {
                    "type": "string",
                },
                "due_at": {
                    "type": "string",
                    "description": (
                        "带时区的 ISO 8601 时间"
                    ),
                },
                "importance": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "recurrence": {
                    "type": "string",
                    "enum": [
                        "none",
                        "daily",
                        "weekly",
                    ],
                },
                "source_text": {
                    "type": "string",
                },
            },
            "required": [
                "title",
                "due_at",
                "importance",
            ],
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        raw_title = str(arguments["title"])
        title = clean_schedule_title(raw_title) or raw_title.strip()
        plan = self.manager.create(
            title=title,
            details=str(
                arguments.get(
                    "details",
                    "",
                )
            ),
            due_at=str(
                arguments["due_at"]
            ),
            importance=int(
                arguments["importance"]
            ),
            recurrence=str(
                arguments.get(
                    "recurrence",
                    "none",
                )
            ),
            source_text=str(
                arguments.get(
                    "source_text",
                    "",
                )
            ),
        )
        return ToolResult(
            ok=True,
            content=plan.to_dict(),
        )


class PlanListTool(BaseTool):
    name = "plan_list"
    description = (
        "列出仍在等待执行的计划。"
    )

    def __init__(
        self,
        manager: PlanManager,
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
        plans = [
            plan.to_dict()
            for plan
            in self.manager.list_plans(
                active_only=True
            )
        ]
        return ToolResult(
            ok=True,
            content={
                "plans": plans,
            },
        )


class PlanCancelTool(BaseTool):
    name = "plan_cancel"
    description = (
        "按计划 ID 或关键词取消计划。"
    )

    def __init__(
        self,
        manager: PlanManager,
    ) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                },
                "query": {
                    "type": "string",
                },
            },
            "additionalProperties": False,
        }

    def run(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        plan_id = str(
            arguments.get(
                "plan_id",
                "",
            )
        ).strip()
        query = str(
            arguments.get(
                "query",
                "",
            )
        ).strip()

        cancelled: list[str] = []
        if plan_id:
            if self.manager.cancel(
                plan_id
            ):
                cancelled.append(
                    plan_id
                )
        elif query:
            cancelled = (
                self.manager
                .cancel_by_query(query)
            )
        else:
            return ToolResult(
                ok=False,
                content=None,
                error=(
                    "plan_id 和 query "
                    "至少需要一个"
                ),
            )

        return ToolResult(
            ok=True,
            content={
                "cancelled": cancelled,
            },
        )
