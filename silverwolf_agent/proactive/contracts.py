from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import datetime
import json
from typing import Any
import uuid


@dataclass
class ScheduleDecision:
    should_persist: bool
    importance: int
    reason: str
    title: str = ""
    due_at: str = ""
    recurrence: str = "none"
    source_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScheduledPlan:
    plan_id: str
    title: str
    details: str
    due_at: str
    importance: int
    recurrence: str
    source_text: str
    status: str
    created_at: str
    last_triggered_at: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def create(
        cls,
        *,
        title: str,
        details: str,
        due_at: str,
        importance: int,
        recurrence: str = "none",
        source_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ScheduledPlan":
        return cls(
            plan_id=str(uuid.uuid4()),
            title=title.strip(),
            details=details.strip(),
            due_at=due_at,
            importance=max(
                0,
                min(100, int(importance)),
            ),
            recurrence=recurrence,
            source_text=source_text,
            status="pending",
            created_at=(
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ScheduledPlan":
        return cls(
            plan_id=str(
                data["plan_id"]
            ),
            title=str(data["title"]),
            details=str(
                data.get("details", "")
            ),
            due_at=str(
                data["due_at"]
            ),
            importance=int(
                data.get(
                    "importance",
                    70,
                )
            ),
            recurrence=str(
                data.get(
                    "recurrence",
                    "none",
                )
            ),
            source_text=str(
                data.get(
                    "source_text",
                    "",
                )
            ),
            status=str(
                data.get(
                    "status",
                    "pending",
                )
            ),
            created_at=str(
                data.get(
                    "created_at",
                    datetime.now().isoformat(
                        timespec="seconds"
                    ),
                )
            ),
            last_triggered_at=(
                str(
                    data[
                        "last_triggered_at"
                    ]
                )
                if data.get(
                    "last_triggered_at"
                )
                else None
            ),
            metadata=dict(
                data.get("metadata", {})
            ),
        )


@dataclass
class RoutineEvent:
    key: str
    scheduled_at: str
    weight: int
    window_minutes: int
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProactivePlan:
    proactive_plan_id: str
    schema_version: str
    created_at: str
    planned_messages: list[
        dict[str, Any]
    ]
    routine_keys: list[str]
    scheduled_plan_ids: list[str]
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def create(
        cls,
        *,
        planned_messages: list[
            dict[str, Any]
        ],
        routine_keys: list[str],
        scheduled_plan_ids: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> "ProactivePlan":
        return cls(
            proactive_plan_id=str(
                uuid.uuid4()
            ),
            schema_version="1.0",
            created_at=(
                datetime.now().isoformat(
                    timespec="seconds"
                )
            ),
            planned_messages=(
                planned_messages
            ),
            routine_keys=routine_keys,
            scheduled_plan_ids=(
                scheduled_plan_ids
            ),
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(
        cls,
        value: str,
    ) -> "ProactivePlan":
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError(
                "ProactivePlan JSON "
                "顶层必须是 object"
            )
        return cls(
            proactive_plan_id=str(
                data[
                    "proactive_plan_id"
                ]
            ),
            schema_version=str(
                data.get(
                    "schema_version",
                    "1.0",
                )
            ),
            created_at=str(
                data["created_at"]
            ),
            planned_messages=[
                dict(item)
                for item in data.get(
                    "planned_messages",
                    [],
                )
            ],
            routine_keys=[
                str(item)
                for item in data.get(
                    "routine_keys",
                    [],
                )
            ],
            scheduled_plan_ids=[
                str(item)
                for item in data.get(
                    "scheduled_plan_ids",
                    [],
                )
            ],
            metadata=dict(
                data.get("metadata", {})
            ),
        )
