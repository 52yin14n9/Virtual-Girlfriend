from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import datetime
import json
from typing import Any, Callable


def normalize_chat_terminal_punctuation(value: str) -> str:
    """QQ/IM 风格：普通消息末尾不保留全角句号。

    只处理最终的“。”，不删除句内标点，也不碰问号、感叹号、
    省略号等承载语气的信息。
    """
    cleaned = value.strip()
    if cleaned.endswith("。"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned
import uuid


@dataclass
class OutboundMessage:
    content: str
    weight: int
    category: str
    source: str
    sequence: int = 0
    delay_seconds: float = 0.0
    goal_kinds: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    message_id: str = field(
        default_factory=lambda: str(
            uuid.uuid4()
        )
    )
    created_at: str = field(
        default_factory=lambda: (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )
    )

    def __post_init__(self) -> None:
        self.content = normalize_chat_terminal_punctuation(self.content)

    def validate(self) -> None:
        self.content = normalize_chat_terminal_punctuation(self.content)
        if not self.content:
            raise ValueError(
                "消息内容不能为空"
            )
        self.weight = max(
            0,
            min(100, int(self.weight)),
        )
        self.sequence = int(self.sequence)
        self.delay_seconds = max(
            0.0,
            float(self.delay_seconds),
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "OutboundMessage":
        message = cls(
            content=str(
                data["content"]
            ),
            weight=int(
                data.get("weight", 50)
            ),
            category=str(
                data.get(
                    "category",
                    "conversation",
                )
            ),
            source=str(
                data.get(
                    "source",
                    "interactive",
                )
            ),
            sequence=int(
                data.get("sequence", 0)
            ),
            delay_seconds=float(
                data.get(
                    "delay_seconds",
                    0.0,
                )
            ),
            goal_kinds=[
                str(item)
                for item in data.get(
                    "goal_kinds",
                    [],
                )
            ],
            metadata=dict(
                data.get("metadata", {})
            ),
            message_id=str(
                data.get(
                    "message_id",
                    uuid.uuid4(),
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
        )
        message.validate()
        return message


@dataclass
class ReplyBundle:
    messages: list[OutboundMessage]
    minimum_weight: int = 40
    maximum_messages: int = 3
    bundle_id: str = field(
        default_factory=lambda: str(
            uuid.uuid4()
        )
    )

    def selected_messages(
        self,
    ) -> list[OutboundMessage]:
        candidates = [
            message
            for message in self.messages
            if (
                message.weight
                >= self.minimum_weight
            )
        ]
        if not candidates:
            candidates = sorted(
                self.messages,
                key=lambda item: (
                    item.weight,
                    -item.sequence,
                ),
                reverse=True,
            )[:1]

        if (
            len(candidates)
            > self.maximum_messages
        ):
            selected_ids = {
                message.message_id
                for message in sorted(
                    candidates,
                    key=lambda item: (
                        item.weight,
                        -item.sequence,
                    ),
                    reverse=True,
                )[
                    : self.maximum_messages
                ]
            }
            candidates = [
                message
                for message in candidates
                if (
                    message.message_id
                    in selected_ids
                )
            ]

        return sorted(
            candidates,
            key=lambda item: (
                item.sequence,
                -item.weight,
            ),
        )

    def joined_text(
        self,
    ) -> str:
        return "\n\n".join(
            message.content
            for message
            in self.selected_messages()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "minimum_weight": (
                self.minimum_weight
            ),
            "maximum_messages": (
                self.maximum_messages
            ),
            "messages": [
                message.to_dict()
                for message in self.messages
            ],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ReplyBundle":
        return cls(
            messages=[
                OutboundMessage.from_dict(
                    item
                )
                for item in data.get(
                    "messages",
                    [],
                )
            ],
            minimum_weight=int(
                data.get(
                    "minimum_weight",
                    40,
                )
            ),
            maximum_messages=int(
                data.get(
                    "maximum_messages",
                    3,
                )
            ),
            bundle_id=str(
                data.get(
                    "bundle_id",
                    uuid.uuid4(),
                )
            ),
        )

    @classmethod
    def from_json(
        cls,
        value: str,
    ) -> "ReplyBundle":
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError(
                "ReplyBundle JSON "
                "顶层必须是 object"
            )
        return cls.from_dict(data)


class MessageSink(ABC):
    @abstractmethod
    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        raise NotImplementedError


class ConsoleMessageSink(MessageSink):
    def __init__(
        self,
        interactive_prefix: str = (
            "银狼lv23> "
        ),
        proactive_prefix: str = (
            "银狼lv23（主动）> "
        ),
        printer: Callable[[str], None] = print,
    ) -> None:
        self.interactive_prefix = (
            interactive_prefix
        )
        self.proactive_prefix = (
            proactive_prefix
        )
        self.printer = printer
        self._lock = asyncio.Lock()

    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        prefix = (
            self.proactive_prefix
            if message.source
            == "proactive"
            else self.interactive_prefix
        )
        async with self._lock:
            self.printer(
                "\n"
                + prefix
                + message.content
            )


class CallbackMessageSink(MessageSink):
    def __init__(
        self,
        callback: Callable[
            [OutboundMessage],
            Any,
        ],
    ) -> None:
        self.callback = callback

    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        result = self.callback(
            message
        )
        if asyncio.iscoroutine(result):
            await result


class CollectingMessageSink(MessageSink):
    def __init__(self) -> None:
        self.messages: list[
            OutboundMessage
        ] = []

    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        self.messages.append(
            message
        )


class MessageDispatcher:
    def __init__(
        self,
        default_gap_seconds: float = 0.9,
    ) -> None:
        self.default_gap_seconds = max(
            0.0,
            default_gap_seconds,
        )

    async def dispatch(
        self,
        bundle: ReplyBundle,
        sink: MessageSink,
    ) -> None:
        messages = (
            bundle.selected_messages()
        )
        for index, message in enumerate(
            messages
        ):
            await sink.send(message)
            if index >= len(messages) - 1:
                continue

            delay = (
                message.delay_seconds
                or self.default_gap_seconds
            )
            if delay > 0:
                await asyncio.sleep(delay)
