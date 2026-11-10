from __future__ import annotations

import copy
from datetime import (
    datetime,
    time,
    timedelta,
)
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import RoutineEvent
from .state import ProactiveStateStore
from ..paths import (
    TIME_PREFERENCES_PATH,
    ensure_directories,
)


TIME_PATTERN = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d$"
)


class TimeManager:
    DEFAULTS = {
        "schema_version": 1,
        "timezone": "Asia/Shanghai",
        "proactive_enabled": True,
        "message_gap_seconds": 0.9,
        "quiet_hours": {
            "start": "23:30",
            "end": "07:20",
        },
        "slots": {
            "morning": {
                "time": "08:00",
                "window_minutes": 45,
                "enabled": True,
                "weight": 72,
            },
            "noon": {
                "time": "12:10",
                "window_minutes": 40,
                "enabled": True,
                "weight": 70,
            },
            "evening": {
                "time": "18:30",
                "window_minutes": 50,
                "enabled": True,
                "weight": 72,
            },
        },
    }

    def __init__(
        self,
        path: Path = TIME_PREFERENCES_PATH,
        timezone: str = "Asia/Shanghai",
        *,
        jitter_enabled: bool = True,
        jitter_minutes: int = 10,
        pinned_days: int = 7,
    ) -> None:
        ensure_directories()
        self.path = path
        self._lock = threading.RLock()
        # Lv30: 关系型主动关心在窗口内做小幅抖动，避免准点打卡感。
        # 正式提醒（计划到期）不经过这里，永远准点。
        self.jitter_enabled = bool(jitter_enabled)
        self.jitter_minutes = max(0, min(120, int(jitter_minutes)))
        self.pinned_days = max(0, int(pinned_days))

        if not self.path.exists():
            data = copy.deepcopy(
                self.DEFAULTS
            )
            data["timezone"] = timezone
            self._write(data)
        else:
            self._migrate(timezone)

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
                return copy.deepcopy(
                    self.DEFAULTS
                )

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

    def _migrate(
        self,
        timezone: str,
    ) -> None:
        data = self._read()
        changed = False

        for key, value in (
            self.DEFAULTS.items()
        ):
            if key not in data:
                data[key] = copy.deepcopy(
                    value
                )
                changed = True

        data.setdefault(
            "timezone",
            timezone,
        )
        slots = data.setdefault(
            "slots",
            {},
        )
        for key, value in (
            self.DEFAULTS["slots"].items()
        ):
            if key not in slots:
                slots[key] = (
                    copy.deepcopy(value)
                )
                changed = True
            else:
                for sub_key, sub_value in (
                    value.items()
                ):
                    if (
                        sub_key
                        not in slots[key]
                    ):
                        slots[key][
                            sub_key
                        ] = sub_value
                        changed = True

        if changed:
            self._write(data)

    def snapshot(self) -> dict[str, Any]:
        return self._read()

    def timezone(self) -> ZoneInfo:
        value = str(
            self._read().get(
                "timezone",
                "Asia/Shanghai",
            )
        )
        try:
            return ZoneInfo(value)
        except Exception:
            return ZoneInfo(
                "Asia/Shanghai"
            )

    def is_quiet_time(self, now: datetime) -> bool:
        """判断当前是否位于睡眠静默时段，支持跨午夜区间。"""
        local = now.astimezone(self.timezone())
        quiet = self._read().get("quiet_hours", {})
        start_value = str(quiet.get("start", "23:30"))
        end_value = str(quiet.get("end", "07:20"))
        if not TIME_PATTERN.fullmatch(start_value) or not TIME_PATTERN.fullmatch(end_value):
            return False
        start_h, start_m = (int(part) for part in start_value.split(":"))
        end_h, end_m = (int(part) for part in end_value.split(":"))
        start = time(start_h, start_m)
        end = time(end_h, end_m)
        current = local.time().replace(tzinfo=None)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def proactive_enabled(self) -> bool:
        return bool(
            self._read().get(
                "proactive_enabled",
                True,
            )
        )

    def set_proactive_enabled(
        self,
        enabled: bool,
    ) -> None:
        data = self._read()
        data["proactive_enabled"] = (
            bool(enabled)
        )
        self._write(data)

    def slot(
        self,
        name: str,
    ) -> dict[str, Any]:
        slots = self._read().get(
            "slots",
            {},
        )
        value = slots.get(name)
        if not isinstance(value, dict):
            raise KeyError(
                f"未知时间槽：{name}"
            )
        return copy.deepcopy(value)

    def slot_time(
        self,
        name: str,
    ) -> str:
        return str(
            self.slot(name)["time"]
        )

    def set_slot(
        self,
        name: str,
        value: str,
        *,
        enabled: bool | None = None,
        window_minutes: int | None = None,
    ) -> dict[str, Any]:
        if name not in {
            "morning",
            "noon",
            "evening",
        }:
            raise ValueError(
                "slot 必须是 morning、"
                "noon 或 evening"
            )
        if not TIME_PATTERN.fullmatch(
            value
        ):
            raise ValueError(
                "时间格式必须为 HH:MM"
            )

        data = self._read()
        slot = (
            data.setdefault(
                "slots",
                {},
            )
            .setdefault(name, {})
        )
        slot["time"] = value

        if enabled is not None:
            slot["enabled"] = (
                bool(enabled)
            )
        if window_minutes is not None:
            slot["window_minutes"] = max(
                1,
                int(window_minutes),
            )

        # Lv30: 用户刚改过的时间，短时间内不抖动（pinned）
        slot["updated_at"] = datetime.now(
            self.timezone()
        ).isoformat(timespec="seconds")

        self._write(data)
        return copy.deepcopy(slot)

    def _is_pinned(
        self,
        slot: dict[str, Any],
        now: datetime,
    ) -> bool:
        """用户最近手动改过的时间槽位不抖动。"""
        if self.pinned_days <= 0:
            return False
        raw = slot.get("updated_at")
        if not raw:
            return False
        try:
            updated = datetime.fromisoformat(str(raw))
        except ValueError:
            return False
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=now.tzinfo)
        return (now - updated) < timedelta(days=self.pinned_days)

    def _jitter_offset(
        self,
        day: Any,
        key: str,
        base_time: str,
    ) -> int:
        """按日期 + 槽位散列出稳定的分钟偏移（同一天不会反复变）。"""
        if self.jitter_minutes <= 0:
            return 0
        seed = f"{day.isoformat()}|{key}|{base_time}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        span = self.jitter_minutes * 2 + 1
        return int(digest[:8], 16) % span - self.jitter_minutes

    def apply_jitter(
        self,
        scheduled: datetime,
        *,
        key: str,
        slot: dict[str, Any],
        now: datetime,
    ) -> datetime:
        """关系型主动关心的触发时刻（正式提醒不走这里）。"""
        if not self.jitter_enabled or self.jitter_minutes <= 0:
            return scheduled
        if self._is_pinned(slot, now):
            return scheduled
        offset = self._jitter_offset(
            scheduled.date(),
            key,
            str(slot.get("time", "")),
        )
        return scheduled + timedelta(minutes=offset)

    def due_routines(
        self,
        now: datetime,
        state: ProactiveStateStore,
    ) -> list[RoutineEvent]:
        if not self.proactive_enabled():
            return []

        now = now.astimezone(
            self.timezone()
        )
        events: list[RoutineEvent] = []
        data = self._read()

        for key, slot in (
            data.get(
                "slots",
                {},
            ).items()
        ):
            if not slot.get(
                "enabled",
                True,
            ):
                continue

            scheduled = self._combine(
                now,
                str(slot["time"]),
            )
            # Lv30: 关系型关心在窗口内抖动；pinned 槽位保持准点
            scheduled = self.apply_jitter(
                scheduled,
                key=key,
                slot=slot,
                now=now,
            )
            window = int(
                slot.get(
                    "window_minutes",
                    30,
                )
            )
            end = scheduled + timedelta(
                minutes=window
            )

            if not (
                scheduled
                <= now
                <= end
            ):
                continue
            if state.routine_sent(
                key,
                now.date().isoformat(),
            ):
                continue

            events.append(
                RoutineEvent(
                    key=key,
                    scheduled_at=(
                        scheduled.isoformat(
                            timespec="seconds"
                        )
                    ),
                    weight=int(
                        slot.get(
                            "weight",
                            70,
                        )
                    ),
                    window_minutes=window,
                )
            )

        return events

    def default_due_time(
        self,
        day: datetime,
        slot_name: str,
    ) -> datetime:
        return self._combine(
            day.astimezone(
                self.timezone()
            ),
            self.slot_time(
                slot_name
            ),
        )

    def _combine(
        self,
        now: datetime,
        value: str,
    ) -> datetime:
        hour, minute = (
            int(part)
            for part
            in value.split(":")
        )
        return datetime.combine(
            now.date(),
            time(
                hour=hour,
                minute=minute,
            ),
            tzinfo=self.timezone(),
        )
