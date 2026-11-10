from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
from typing import Any

from ..paths import (
    PROACTIVE_STATE_PATH,
    ensure_directories,
)


class ProactiveStateStore:
    def __init__(
        self,
        path: Path = PROACTIVE_STATE_PATH,
    ) -> None:
        ensure_directories()
        self.path = path
        self._lock = threading.RLock()

        if not self.path.exists():
            self._write(
                self._default_state()
            )
        else:
            self._write(
                self._migrate(
                    self._read()
                )
            )

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "schema_version": 7,
            "routine_sent": {},
            "last_scheduler_run": None,
            "last_user_activity_at": None,
            "pending_follow_up": None,
            "last_follow_up": None,
            "proactive_template_history": [],
            "weather_sent_date": None,
            "memory_callback_sent_date": None,
            "weekend_suggestion_sent_date": None,
            "proactive_delivery_guard": {
                "failure_count": 0,
                "last_failure_at": None,
                "next_retry_at": None,
                "suspended": False,
                "last_error": None,
            },
            "engagement": {
                "relationship_sent": 0,
                "replies_after_proactive": 0,
                "consecutive_unanswered": 0,
                "last_relationship_sent_at": None,
                "awaiting_reply_since": None,
            },
        }

    def _migrate(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        merged = self._default_state()
        merged.update(data)
        merged["schema_version"] = 7
        if not isinstance(
            merged.get(
                "routine_sent"
            ),
            dict,
        ):
            merged["routine_sent"] = {}
        history = merged.get(
            "proactive_template_history"
        )
        if not isinstance(
            history,
            list,
        ):
            merged[
                "proactive_template_history"
            ] = []
        else:
            merged[
                "proactive_template_history"
            ] = [
                dict(item)
                for item in history
                if isinstance(
                    item,
                    dict,
                )
            ][-60:]

        engagement = merged.get("engagement")
        if not isinstance(engagement, dict):
            engagement = {}
        defaults = self._default_state()["engagement"]
        for key, value in defaults.items():
            engagement.setdefault(key, value)
        merged["engagement"] = engagement

        guard = merged.get("proactive_delivery_guard")
        if not isinstance(guard, dict):
            guard = {}
        guard_defaults = self._default_state()["proactive_delivery_guard"]
        for key, value in guard_defaults.items():
            guard.setdefault(key, value)
        merged["proactive_delivery_guard"] = guard

        pending = merged.get(
            "pending_follow_up"
        )
        if (
            pending is not None
            and not isinstance(
                pending,
                dict,
            )
        ):
            merged["pending_follow_up"] = None
        return merged

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                data = json.loads(
                    self.path.read_text(
                        encoding="utf-8"
                    )
                )
                if not isinstance(
                    data,
                    dict,
                ):
                    return self._default_state()
                return data
            except (
                FileNotFoundError,
                json.JSONDecodeError,
            ):
                return self._default_state()

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

    @staticmethod
    def _as_datetime(
        value: str,
    ) -> datetime:
        parsed = datetime.fromisoformat(
            value
        )
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed

    def routine_sent(
        self,
        key: str,
        date_value: str,
    ) -> bool:
        data = self._read()
        return (
            data.get(
                "routine_sent",
                {},
            ).get(key)
            == date_value
        )

    def mark_routine_sent(
        self,
        key: str,
        date_value: str,
    ) -> None:
        with self._lock:
            data = self._read()
            data.setdefault(
                "routine_sent",
                {},
            )[key] = date_value
            self._write(data)

    def set_last_run(
        self,
        value: str,
    ) -> None:
        with self._lock:
            data = self._read()
            data["last_scheduler_run"] = value
            self._write(data)

    def arm_follow_up(
        self,
        *,
        sent_at: datetime,
        due_at: datetime,
        expires_at: datetime,
        routine_key: str,
        original_content: str,
        original_message_id: str,
    ) -> bool:
        """
        为一条需要回应的主动关心消息建立一次追问。

        同一时间只保留一个 pending follow-up。新主动关心
        会替换尚未触发的旧追问，避免堆积催促。
        """
        if sent_at.tzinfo is None:
            sent_at = sent_at.astimezone()
        if due_at.tzinfo is None:
            due_at = due_at.astimezone()
        if expires_at.tzinfo is None:
            expires_at = expires_at.astimezone()

        with self._lock:
            data = self._read()

            # 用户可能已经从另一个线程回复，而 Scheduler
            # 还没来得及写入 pending 状态。此时不能再追问。
            last_user_raw = str(
                data.get(
                    "last_user_activity_at",
                    "",
                )
                or ""
            )
            if last_user_raw:
                try:
                    last_user_at = (
                        self._as_datetime(
                            last_user_raw
                        )
                    )
                except ValueError:
                    last_user_at = None

                if (
                    last_user_at is not None
                    and last_user_at >= sent_at
                ):
                    data["last_follow_up"] = {
                        "status": (
                            "suppressed_by_user_reply"
                        ),
                        "routine_key": routine_key,
                        "original_content": (
                            original_content
                        ),
                        "original_message_id": (
                            original_message_id
                        ),
                        "sent_at": (
                            sent_at.isoformat(
                                timespec="seconds"
                            )
                        ),
                        "resolved_at": (
                            last_user_at.isoformat(
                                timespec="seconds"
                            )
                        ),
                    }
                    data["pending_follow_up"] = None
                    self._write(data)
                    return False

            data["pending_follow_up"] = {
                "status": "waiting",
                "routine_key": routine_key,
                "original_content": (
                    original_content
                ),
                "original_message_id": (
                    original_message_id
                ),
                "sent_at": sent_at.isoformat(
                    timespec="seconds"
                ),
                "due_at": due_at.isoformat(
                    timespec="seconds"
                ),
                "expires_at": (
                    expires_at.isoformat(
                        timespec="seconds"
                    )
                ),
                "attempts": 0,
            }
            self._write(data)
            return True

    def proactive_delivery_allowed(self, at: datetime) -> bool:
        if at.tzinfo is None:
            at = at.astimezone()
        data = self._read()
        guard = data.get("proactive_delivery_guard", {})
        if not isinstance(guard, dict):
            return True
        if bool(guard.get("suspended", False)):
            return False
        next_retry_raw = str(guard.get("next_retry_at", "") or "")
        if not next_retry_raw:
            return True
        try:
            next_retry = self._as_datetime(next_retry_raw)
        except ValueError:
            return True
        return at >= next_retry

    def record_proactive_delivery_failure(
        self,
        *,
        at: datetime,
        error: str,
        max_failures: int = 3,
    ) -> dict[str, Any]:
        if at.tzinfo is None:
            at = at.astimezone()
        max_failures = max(1, int(max_failures))
        with self._lock:
            data = self._read()
            guard = data.setdefault(
                "proactive_delivery_guard",
                self._default_state()["proactive_delivery_guard"].copy(),
            )
            count = int(guard.get("failure_count", 0)) + 1
            guard["failure_count"] = count
            guard["last_failure_at"] = at.isoformat(timespec="seconds")
            guard["last_error"] = str(error)[:500]
            if count >= max_failures:
                guard["suspended"] = True
                guard["next_retry_at"] = None
            else:
                # 30s -> 2m. A third failure suspends until the channel proves
                # it is alive again via user activity or a successful send.
                delays = (30, 120, 600)
                delay_seconds = delays[min(count - 1, len(delays) - 1)]
                guard["next_retry_at"] = (
                    at + timedelta(seconds=delay_seconds)
                ).isoformat(timespec="seconds")
                guard["suspended"] = False
            self._write(data)
            return dict(guard)

    def reset_proactive_delivery_guard(self, *, reason: str = "recovered") -> None:
        with self._lock:
            data = self._read()
            guard = self._default_state()["proactive_delivery_guard"].copy()
            guard["last_error"] = None
            data["proactive_delivery_guard"] = guard
            data["proactive_delivery_guard_reset_reason"] = str(reason)
            self._write(data)

    def proactive_delivery_guard_snapshot(self) -> dict[str, Any]:
        data = self._read()
        guard = data.get("proactive_delivery_guard", {})
        return dict(guard) if isinstance(guard, dict) else {}

    def note_user_activity(
        self,
        at: datetime,
    ) -> bool:
        """
        登记用户发言，并取消该发言之前尚未发送的追问。

        返回 True 表示确实取消了一条等待中的追问。
        """
        if at.tzinfo is None:
            at = at.astimezone()

        with self._lock:
            data = self._read()
            data["last_user_activity_at"] = (
                at.isoformat(
                    timespec="seconds"
                )
            )

            guard = data.get("proactive_delivery_guard")
            if isinstance(guard, dict) and (
                int(guard.get("failure_count", 0)) > 0
                or bool(guard.get("suspended", False))
            ):
                data["proactive_delivery_guard"] = (
                    self._default_state()["proactive_delivery_guard"].copy()
                )
                data["proactive_delivery_guard_reset_reason"] = "user_activity"

            engagement = data.setdefault(
                "engagement",
                self._default_state()["engagement"].copy(),
            )
            awaiting_raw = str(
                engagement.get("awaiting_reply_since", "")
                or ""
            )
            if awaiting_raw:
                try:
                    awaiting = self._as_datetime(awaiting_raw)
                except ValueError:
                    awaiting = at
                if at >= awaiting:
                    engagement["replies_after_proactive"] = int(
                        engagement.get("replies_after_proactive", 0)
                    ) + 1
                    engagement["consecutive_unanswered"] = 0
                    engagement["awaiting_reply_since"] = None

            cancelled = False
            pending = data.get(
                "pending_follow_up"
            )
            if isinstance(
                pending,
                dict,
            ):
                sent_raw = str(
                    pending.get(
                        "sent_at",
                        "",
                    )
                )
                try:
                    sent_at = (
                        self._as_datetime(
                            sent_raw
                        )
                    )
                except ValueError:
                    sent_at = at

                if at >= sent_at:
                    data["last_follow_up"] = {
                        **pending,
                        "status": (
                            "cancelled_by_user_reply"
                        ),
                        "resolved_at": (
                            at.isoformat(
                                timespec="seconds"
                            )
                        ),
                    }
                    data["pending_follow_up"] = None
                    cancelled = True

            self._write(data)
            return cancelled

    def due_follow_up(
        self,
        now: datetime,
    ) -> dict[str, Any] | None:
        if now.tzinfo is None:
            now = now.astimezone()

        with self._lock:
            data = self._read()
            pending = data.get(
                "pending_follow_up"
            )
            if not isinstance(
                pending,
                dict,
            ):
                return None

            try:
                due_at = self._as_datetime(
                    str(
                        pending.get(
                            "due_at",
                            "",
                        )
                    )
                )
                expires_at = (
                    self._as_datetime(
                        str(
                            pending.get(
                                "expires_at",
                                "",
                            )
                        )
                    )
                )
            except ValueError:
                data["last_follow_up"] = {
                    **pending,
                    "status": (
                        "discarded_invalid_time"
                    ),
                    "resolved_at": (
                        now.isoformat(
                            timespec="seconds"
                        )
                    ),
                }
                data["pending_follow_up"] = None
                self._write(data)
                return None

            if now > expires_at:
                data["last_follow_up"] = {
                    **pending,
                    "status": "expired",
                    "resolved_at": (
                        now.isoformat(
                            timespec="seconds"
                        )
                    ),
                }
                data["pending_follow_up"] = None
                self._write(data)
                return None

            if now < due_at:
                return None

            if int(
                pending.get(
                    "attempts",
                    0,
                )
            ) >= 1:
                data["pending_follow_up"] = None
                self._write(data)
                return None

            return dict(pending)

    def is_follow_up_pending(
        self,
        original_message_id: str,
    ) -> bool:
        data = self._read()
        pending = data.get(
            "pending_follow_up"
        )
        return bool(
            isinstance(
                pending,
                dict,
            )
            and str(
                pending.get(
                    "original_message_id",
                    "",
                )
            )
            == original_message_id
            and str(
                pending.get(
                    "status",
                    "",
                )
            )
            == "waiting"
        )

    def mark_follow_up_sent(
        self,
        *,
        sent_at: datetime,
    ) -> None:
        if sent_at.tzinfo is None:
            sent_at = sent_at.astimezone()

        with self._lock:
            data = self._read()
            pending = data.get(
                "pending_follow_up"
            )
            if not isinstance(
                pending,
                dict,
            ):
                return

            data["last_follow_up"] = {
                **pending,
                "attempts": (
                    int(
                        pending.get(
                            "attempts",
                            0,
                        )
                    )
                    + 1
                ),
                "status": "sent",
                "resolved_at": (
                    sent_at.isoformat(
                        timespec="seconds"
                    )
                ),
            }
            data["pending_follow_up"] = None
            self._write(data)

    def clear_follow_up(
        self,
        *,
        reason: str,
        at: datetime,
    ) -> bool:
        if at.tzinfo is None:
            at = at.astimezone()

        with self._lock:
            data = self._read()
            pending = data.get(
                "pending_follow_up"
            )
            if not isinstance(
                pending,
                dict,
            ):
                return False

            data["last_follow_up"] = {
                **pending,
                "status": reason,
                "resolved_at": (
                    at.isoformat(
                        timespec="seconds"
                    )
                ),
            }
            data["pending_follow_up"] = None
            self._write(data)
            return True

    def weather_sent(
        self,
        date_value: str,
    ) -> bool:
        return (
            self._read().get("weather_sent_date")
            == date_value
        )

    def mark_weather_sent(
        self,
        date_value: str,
    ) -> None:
        with self._lock:
            data = self._read()
            data["weather_sent_date"] = date_value
            self._write(data)


    def memory_callback_sent(
        self,
        date_value: str,
    ) -> bool:
        return self._read().get("memory_callback_sent_date") == date_value

    def mark_memory_callback_sent(
        self,
        date_value: str,
    ) -> None:
        with self._lock:
            data = self._read()
            data["memory_callback_sent_date"] = date_value
            self._write(data)

    def weekend_suggestion_sent(
        self,
        date_value: str,
    ) -> bool:
        return self._read().get("weekend_suggestion_sent_date") == date_value

    def mark_weekend_suggestion_sent(
        self,
        date_value: str,
    ) -> None:
        with self._lock:
            data = self._read()
            data["weekend_suggestion_sent_date"] = date_value
            self._write(data)

    def self_share_allowed(
        self,
        now: datetime,
        *,
        per_week: int = 2,
    ) -> bool:
        """Lv32: 每周最多讲几次"她自己的事"。"""
        limit = max(0, int(per_week))
        if limit == 0:
            return False
        with self._lock:
            data = self._read()
        history = data.get("self_share_history", [])
        if not isinstance(history, list):
            return True
        recent = 0
        for raw in history:
            try:
                moment = datetime.fromisoformat(str(raw))
            except ValueError:
                continue
            if moment.tzinfo is None and now.tzinfo is not None:
                moment = moment.replace(tzinfo=now.tzinfo)
            if (now - moment).days < 7:
                recent += 1
        return recent < limit

    def record_self_share(self, now: datetime) -> None:
        with self._lock:
            data = self._read()
            history = data.get("self_share_history", [])
            if not isinstance(history, list):
                history = []
            history.append(now.isoformat(timespec="seconds"))
            data["self_share_history"] = history[-30:]
            self._write(data)

    def record_relationship_sent(
        self,
        *,
        sent_at: datetime,
        expects_reply: bool,
    ) -> None:
        if sent_at.tzinfo is None:
            sent_at = sent_at.astimezone()
        with self._lock:
            data = self._read()
            engagement = data.setdefault(
                "engagement",
                self._default_state()["engagement"].copy(),
            )
            if engagement.get("awaiting_reply_since"):
                engagement["consecutive_unanswered"] = int(
                    engagement.get("consecutive_unanswered", 0)
                ) + 1
            engagement["relationship_sent"] = int(
                engagement.get("relationship_sent", 0)
            ) + 1
            engagement["last_relationship_sent_at"] = sent_at.isoformat(
                timespec="seconds"
            )
            engagement["awaiting_reply_since"] = (
                sent_at.isoformat(timespec="seconds")
                if expects_reply
                else None
            )
            self._write(data)

    def recent_template_ids(
        self,
        *,
        group: str | None = None,
        limit: int = 6,
    ) -> list[str]:
        data = self._read()
        history = data.get(
            "proactive_template_history",
            [],
        )
        values: list[str] = []

        for item in reversed(
            history
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue
            if (
                group
                and str(
                    item.get(
                        "template_group",
                        "",
                    )
                )
                != group
            ):
                continue

            template_id = str(
                item.get(
                    "template_id",
                    "",
                )
            )
            if (
                template_id
                and template_id
                not in values
            ):
                values.append(
                    template_id
                )
            if len(values) >= max(
                1,
                int(limit),
            ):
                break

        return values

    def record_template_use(
        self,
        *,
        template_id: str,
        template_group: str,
        content: str,
        sent_at: datetime,
        category: str,
        semantic_tags: list[str] | tuple[str, ...] | None = None,
        source: str = "",
    ) -> None:
        if sent_at.tzinfo is None:
            sent_at = (
                sent_at.astimezone()
            )

        with self._lock:
            data = self._read()
            history = data.setdefault(
                "proactive_template_history",
                [],
            )
            if not isinstance(
                history,
                list,
            ):
                history = []
                data[
                    "proactive_template_history"
                ] = history

            history.append(
                {
                    "template_id": (
                        template_id
                    ),
                    "template_group": (
                        template_group
                    ),
                    "content": (
                        content[:500]
                    ),
                    "category": category,
                    "semantic_tags": [
                        str(tag)
                        for tag in (semantic_tags or [])
                        if str(tag)
                    ],
                    "sent_at": (
                        sent_at.isoformat(
                            timespec="seconds"
                        )
                    ),
                    # Lv31: 记录这句是语料生成的还是确定性兜底
                    "source": source or "template",
                }
            )
            data[
                "proactive_template_history"
            ] = history[-60:]
            self._write(data)

    def snapshot(self) -> dict[str, Any]:
        return self._migrate(
            self._read()
        )
