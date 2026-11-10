from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)
import json
from pathlib import Path
import re
import threading
from typing import Any

from .contracts import ScheduledPlan
from ..paths import (
    SCHEDULED_PLANS_PATH,
    ensure_directories,
)


class PlanManager:
    EVENT_RESOLUTION_PATTERNS = {
        "行程": re.compile(r"(?:已经)?(?:到(?:了|啦|咯)|到家(?:了|啦|咯)?|抵达(?:了|啦|咯)?)"),
        "面试": re.compile(r"(?:面完(?:了|啦|咯)?|面试.{0,6}(?:结束|完)(?:了|啦|咯)?)"),
        "考试": re.compile(r"(?:考完(?:了|啦|咯)?|考试.{0,6}(?:结束|完)(?:了|啦|咯)?)"),
        "答辩": re.compile(r"(?:答辩.{0,6}(?:结束|完|搞定)(?:了|啦|咯)?)"),
        "会议": re.compile(r"(?:开完会(?:了|啦|咯)?|会开完(?:了|啦|咯)?|会议.{0,6}(?:结束|完)(?:了|啦|咯)?)"),
        "体检": re.compile(r"(?:体检.{0,6}(?:结束|做完|完)(?:了|啦|咯)?)"),
        "看病": re.compile(r"(?:看完病(?:了|啦|咯)?|看病.{0,6}(?:结束|完)(?:了|啦|咯)?|从医院出来(?:了|啦|咯)?)"),
        "部署": re.compile(r"(?:部署.{0,8}(?:完成|搞定|好了|完)(?:了|啦|咯)?)"),
        "上线": re.compile(r"(?:已经上线|上线.{0,8}(?:完成|搞定|好了)(?:了|啦|咯)?)"),
        "作业提交": re.compile(r"(?:作业.{0,8}(?:交了|提交了|交完|提交完)|已经交作业)"),
    }
    GENERIC_EVENT_RESOLUTION_PATTERN = re.compile(
        r"^(?:我)?(?:已经)?(?:搞定|完成|做完|弄完|结束)(?:了|啦|咯)?[～~!！。 ]*$"
    )
    def __init__(
        self,
        path: Path = SCHEDULED_PLANS_PATH,
    ) -> None:
        ensure_directories()
        self.path = path
        self._lock = threading.RLock()

        if not self.path.exists():
            self._write(
                {
                    "schema_version": 1,
                    "plans": [],
                }
            )

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(
                    self.path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                FileNotFoundError,
                json.JSONDecodeError,
            ):
                return {
                    "schema_version": 1,
                    "plans": [],
                }

    def _write(
        self,
        data: dict[str, Any],
    ) -> None:
        with self._lock:
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self.path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def create(
        self,
        *,
        title: str,
        details: str,
        due_at: str,
        importance: int,
        recurrence: str = "none",
        source_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ScheduledPlan:
        datetime.fromisoformat(due_at)
        if recurrence not in {
            "none",
            "daily",
            "weekly",
        }:
            raise ValueError(
                "recurrence 必须是 "
                "none、daily 或 weekly"
            )

        existing = self.find_duplicate(
            title=title,
            due_at=due_at,
        )
        if existing is not None:
            return existing

        plan = ScheduledPlan.create(
            title=title,
            details=details,
            due_at=due_at,
            importance=importance,
            recurrence=recurrence,
            source_text=source_text,
            metadata=metadata,
        )

        data = self._read()
        data.setdefault(
            "plans",
            [],
        ).append(
            plan.to_dict()
        )
        self._write(data)
        return plan

    def find_duplicate(
        self,
        *,
        title: str,
        due_at: str,
    ) -> ScheduledPlan | None:
        target_time = datetime.fromisoformat(
            due_at
        )
        normalized = title.strip().lower()

        for plan in self.list_plans(
            active_only=True
        ):
            if (
                plan.title.strip().lower()
                != normalized
            ):
                continue

            existing_time = (
                datetime.fromisoformat(
                    plan.due_at
                )
            )
            if abs(
                (
                    existing_time
                    - target_time
                ).total_seconds()
            ) <= 60:
                return plan

        return None

    def list_plans(
        self,
        *,
        active_only: bool = False,
    ) -> list[ScheduledPlan]:
        plans = [
            ScheduledPlan.from_dict(
                item
            )
            for item in self._read().get(
                "plans",
                [],
            )
        ]
        if active_only:
            plans = [
                plan
                for plan in plans
                if plan.status
                == "pending"
            ]

        return sorted(
            plans,
            key=lambda item: (
                item.status
                != "pending",
                item.due_at,
                -item.importance,
            ),
        )

    def due(
        self,
        now: datetime,
        *,
        overdue_grace_hours: int = 24,
    ) -> list[ScheduledPlan]:
        earliest = now - timedelta(
            hours=overdue_grace_hours
        )
        result: list[ScheduledPlan] = []

        for plan in self.list_plans(
            active_only=True
        ):
            due_at = datetime.fromisoformat(
                plan.due_at
            )
            if due_at.tzinfo is None:
                due_at = due_at.replace(
                    tzinfo=now.tzinfo
                )

            if (
                earliest
                <= due_at
                <= now
            ):
                result.append(plan)

        return sorted(
            result,
            key=lambda item: (
                -item.importance,
                item.due_at,
            ),
        )

    def mark_triggered(
        self,
        plan_id: str,
        now: datetime,
    ) -> None:
        data = self._read()
        changed = False

        for item in data.get(
            "plans",
            [],
        ):
            if item.get(
                "plan_id"
            ) != plan_id:
                continue

            item[
                "last_triggered_at"
            ] = now.isoformat(
                timespec="seconds"
            )

            recurrence = item.get(
                "recurrence",
                "none",
            )
            if recurrence == "daily":
                due_at = (
                    datetime.fromisoformat(
                        item["due_at"]
                    )
                    + timedelta(days=1)
                )
                item["due_at"] = (
                    due_at.isoformat(
                        timespec="seconds"
                    )
                )
            elif recurrence == "weekly":
                due_at = (
                    datetime.fromisoformat(
                        item["due_at"]
                    )
                    + timedelta(days=7)
                )
                item["due_at"] = (
                    due_at.isoformat(
                        timespec="seconds"
                    )
                )
            else:
                item["status"] = (
                    "completed"
                )

            changed = True
            break

        if changed:
            self._write(data)

    def resolve_relationship_followups(
        self,
        text: str,
        at: datetime,
    ) -> list[str]:
        """用户已经报告事件完成时，自动结束对应关系型回访。"""
        cleaned = text.strip()
        if not cleaned:
            return []

        candidates = [
            plan
            for plan in self.list_plans(active_only=True)
            if plan.metadata.get("kind") == "relationship_event_follow_up"
        ]
        if not candidates:
            return []

        matched: list[ScheduledPlan] = []
        for plan in candidates:
            label = str(plan.metadata.get("event_label", "")).strip()
            pattern = self.EVENT_RESOLUTION_PATTERNS.get(label)
            if pattern is not None and pattern.search(cleaned):
                matched.append(plan)

        # “搞定了/结束了”本身没有事件名时，只在当前恰好只有一个
        # 关系型回访的情况下消解，避免误取消别的长期事项。
        if (
            not matched
            and len(candidates) == 1
            and self.GENERIC_EVENT_RESOLUTION_PATTERN.search(cleaned)
        ):
            matched = [candidates[0]]

        if not matched:
            return []

        # 同类型事件同时存在时，只结束最临近的一件，不把历史计划全清掉。
        matched.sort(key=lambda item: item.due_at)
        target = matched[0]
        data = self._read()
        for item in data.get("plans", []):
            if item.get("plan_id") != target.plan_id or item.get("status") != "pending":
                continue
            item["status"] = "completed"
            item.setdefault("metadata", {})["resolved_by_user"] = True
            item["metadata"]["resolved_at"] = at.isoformat(timespec="seconds")
            item["metadata"]["resolution_reason"] = "user_reported_complete"
            self._write(data)
            return [target.plan_id]
        return []

    def expire_relationship_followup(
        self,
        plan_id: str,
        at: datetime,
        *,
        reason: str,
    ) -> bool:
        """关系型回访过期时静默作废，正式提醒不使用该路径。"""
        data = self._read()
        for item in data.get("plans", []):
            if item.get("plan_id") != plan_id or item.get("status") != "pending":
                continue
            if item.get("metadata", {}).get("kind") != "relationship_event_follow_up":
                return False
            item["status"] = "cancelled"
            item.setdefault("metadata", {})["expired_at"] = at.isoformat(timespec="seconds")
            item["metadata"]["expiry_reason"] = reason
            self._write(data)
            return True
        return False

    def cancel(
        self,
        plan_id: str,
    ) -> bool:
        data = self._read()
        changed = False

        for item in data.get(
            "plans",
            [],
        ):
            if (
                item.get("plan_id")
                == plan_id
                and item.get("status")
                == "pending"
            ):
                item["status"] = (
                    "cancelled"
                )
                changed = True
                break

        if changed:
            self._write(data)
        return changed

    def cancel_by_query(
        self,
        query: str,
    ) -> list[str]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        data = self._read()
        cancelled: list[str] = []

        for item in data.get(
            "plans",
            [],
        ):
            if item.get(
                "status"
            ) != "pending":
                continue

            title = str(
                item.get("title", "")
            )
            source_text = str(
                item.get(
                    "source_text",
                    "",
                )
            )
            if (
                normalized in title.lower()
                or normalized
                in source_text.lower()
                or title.lower()
                in normalized
            ):
                item["status"] = (
                    "cancelled"
                )
                cancelled.append(
                    str(
                        item["plan_id"]
                    )
                )

        if cancelled:
            self._write(data)
        return cancelled
