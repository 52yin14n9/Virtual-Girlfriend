from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseTool, ToolResult
from ..proactive.plan_manager import PlanManager
from ..world import WeatherService, WorldContextManager


class WeatherLookupTool(BaseTool):
    name = "weather_lookup"
    description = "查询用户当前设置地点的真实天气；接口失败时返回不可用，禁止编造。"

    def __init__(self, service: WeatherService, now_provider) -> None:
        self.service = service
        self.now_provider = now_provider

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "force": {"type": "boolean"},
            },
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        result = self.service.lookup(
            now=self.now_provider(),
            force=bool(arguments.get("force", False)),
        )
        return ToolResult(
            ok=bool(result.get("available")),
            content=result,
            error=(None if result.get("available") else str(result.get("error", "天气暂时不可用"))),
        )


class WorldContextGetTool(BaseTool):
    name = "world_context_get"
    description = "读取用户当前地点、天气偏好和互动偏好。"

    def __init__(self, manager: WorldContextManager, now_provider) -> None:
        self.manager = manager
        self.now_provider = now_provider

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, content=self.manager.snapshot(self.now_provider()))


class WorldContextUpdateTool(BaseTool):
    name = "world_context_update"
    description = "按用户明确要求修改长期地点、临时地点或天气偏好。"

    def __init__(self, manager: WorldContextManager) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "set_home_location",
                        "set_temporary_location",
                        "clear_temporary_location",
                        "set_weather_preferences",
                    ],
                },
                "query": {"type": "string"},
                "starts_at": {"type": "string"},
                "ends_at": {"type": "string"},
                "updates": {"type": "object"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = str(arguments["action"])
        if action == "set_home_location":
            content = {
                "action": action,
                "location": self.manager.set_home_location(str(arguments.get("query", ""))),
            }
        elif action == "set_temporary_location":
            content = {
                "action": action,
                "location": self.manager.set_temporary_location(
                    str(arguments.get("query", "")),
                    starts_at=str(arguments.get("starts_at", "")),
                    ends_at=str(arguments.get("ends_at", "")),
                ),
            }
        elif action == "clear_temporary_location":
            content = {"action": action, **self.manager.clear_temporary_location()}
        elif action == "set_weather_preferences":
            updates = arguments.get("updates", {})
            if not isinstance(updates, dict):
                raise ValueError("updates 必须是 object")
            content = {
                "action": action,
                "preferences": self.manager.set_weather_preferences(updates),
            }
        else:
            raise ValueError(f"未知 action：{action}")
        return ToolResult(ok=True, content=content)


class InteractionPreferencesSetTool(BaseTool):
    name = "interaction_preferences_set"
    description = "修改主动联系频率、静默时间和周末建议等互动偏好。"

    def __init__(
        self,
        manager: WorldContextManager,
        plan_manager: PlanManager | None = None,
    ) -> None:
        self.manager = manager
        self.plan_manager = plan_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"updates": {"type": "object"}},
            "required": ["updates"],
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        updates = arguments.get("updates", {})
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是 object")
        preferences = self.manager.set_interaction_preferences(updates)
        cancelled_event_follow_ups: list[str] = []
        if (
            updates.get("event_follow_up_enabled") is False
            and self.plan_manager is not None
        ):
            for plan in self.plan_manager.list_plans(active_only=True):
                if plan.metadata.get("kind") == "relationship_event_follow_up":
                    if self.plan_manager.cancel(plan.plan_id):
                        cancelled_event_follow_ups.append(plan.plan_id)
        return ToolResult(
            ok=True,
            content={
                "preferences": preferences,
                "updated_keys": sorted(updates),
                "cancelled_event_follow_ups": cancelled_event_follow_ups,
            },
        )


class EventFollowUpCreateTool(BaseTool):
    name = "event_follow_up_create"
    description = "为用户明确提到的重要近期事件创建一次克制的关系型后续关心。"

    def __init__(self, manager: PlanManager) -> None:
        self.manager = manager

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "event_label": {"type": "string"},
                "title": {"type": "string"},
                "due_at": {"type": "string"},
                "source_text": {"type": "string"},
                "explicit_request": {"type": "boolean"},
            },
            "required": ["event_label", "title", "due_at"],
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        due_at = str(arguments["due_at"])
        datetime.fromisoformat(due_at)
        label = str(arguments["event_label"]).strip()
        plan = self.manager.create(
            title=str(arguments["title"]),
            details=f"在事件结束后自然问一次，不作为正式闹钟：{label}",
            due_at=due_at,
            importance=74,
            recurrence="none",
            source_text=str(arguments.get("source_text", "")),
            metadata={
                "kind": "relationship_event_follow_up",
                "event_label": label,
                "expects_reply": True,
                "no_secondary_follow_up": True,
                "no_late_delivery": True,
                "max_lateness_minutes": 90,
            },
        )
        return ToolResult(ok=True, content=plan.to_dict())
