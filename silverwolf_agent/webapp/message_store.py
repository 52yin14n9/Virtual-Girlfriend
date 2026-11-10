from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import datetime
import threading
from typing import Any


@dataclass
class WebMessageEvent:
    event_id: int
    role: str
    content: str
    timestamp: str
    source: str
    weight: int = 70
    category: str = "conversation"
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MessageStore:
    def __init__(
        self,
        max_events: int = 1000,
    ) -> None:
        self.max_events = max(
            50,
            int(max_events),
        )
        self._events: list[
            WebMessageEvent
        ] = []
        self._next_id = 1
        self._condition = (
            threading.Condition()
        )

    @staticmethod
    def _timestamp(
        value: datetime | str | None,
    ) -> str:
        if isinstance(value, str):
            return value

        current = (
            value
            or datetime.now().astimezone()
        )
        if current.tzinfo is None:
            current = current.astimezone()
        return current.isoformat(
            timespec="seconds"
        )

    def publish(
        self,
        *,
        role: str,
        content: str,
        timestamp: (
            datetime
            | str
            | None
        ) = None,
        source: str = "interactive",
        weight: int = 70,
        category: str = "conversation",
        metadata: (
            dict[str, Any]
            | None
        ) = None,
    ) -> WebMessageEvent:
        value = content.strip()
        if not value:
            raise ValueError(
                "网页消息不能为空"
            )

        with self._condition:
            event = WebMessageEvent(
                event_id=self._next_id,
                role=role,
                content=value,
                timestamp=(
                    self._timestamp(
                        timestamp
                    )
                ),
                source=source,
                weight=max(
                    0,
                    min(
                        100,
                        int(weight),
                    ),
                ),
                category=category,
                metadata=(
                    metadata or {}
                ),
            )
            self._next_id += 1
            self._events.append(
                event
            )
            if (
                len(self._events)
                > self.max_events
            ):
                self._events = (
                    self._events[
                        -self.max_events:
                    ]
                )
            self._condition.notify_all()
            return event

    def snapshot(
        self,
        *,
        after: int = 0,
    ) -> list[
        WebMessageEvent
    ]:
        with self._condition:
            return [
                event
                for event in self._events
                if event.event_id > after
            ]

    def wait_for_events(
        self,
        *,
        after: int,
        timeout: float = 15.0,
    ) -> list[
        WebMessageEvent
    ]:
        with self._condition:
            ready = [
                event
                for event in self._events
                if event.event_id > after
            ]
            if ready:
                return ready

            self._condition.wait(
                timeout=timeout
            )
            return [
                event
                for event in self._events
                if event.event_id > after
            ]
