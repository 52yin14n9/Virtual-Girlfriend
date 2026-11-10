from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _as_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def extract_message_text(
    event: dict[str, Any],
) -> str:
    """
    把 OneBot 11 字符串或消息段数组转换为可读文本。

    只把文本段原样交给 Agent；图片、语音等转换为占位符，
    避免把不可信文件路径或 CQ 数据误当作指令。
    """
    message = event.get(
        "message"
    )
    raw = str(
        event.get(
            "raw_message",
            "",
        )
        or ""
    )

    if isinstance(
        message,
        str,
    ):
        return (
            message.strip()
            or raw.strip()
        )

    if not isinstance(
        message,
        list,
    ):
        return raw.strip()

    parts: list[str] = []
    placeholder = {
        "image": "[图片]",
        "record": "[语音]",
        "video": "[视频]",
        "file": "[文件]",
        "face": "[表情]",
        "json": "[卡片消息]",
        "xml": "[卡片消息]",
    }

    for segment in message:
        if not isinstance(
            segment,
            dict,
        ):
            continue
        segment_type = str(
            segment.get(
                "type",
                "",
            )
        )
        data = segment.get(
            "data",
            {},
        )
        if not isinstance(
            data,
            dict,
        ):
            data = {}

        if segment_type == "text":
            parts.append(
                str(
                    data.get(
                        "text",
                        "",
                    )
                )
            )
        elif segment_type == "at":
            target = str(
                data.get(
                    "qq",
                    "",
                )
            )
            parts.append(
                f"[@{target}]"
                if target
                else "[@]"
            )
        elif segment_type == "reply":
            continue
        elif segment_type in placeholder:
            parts.append(
                placeholder[
                    segment_type
                ]
            )
        else:
            parts.append(
                f"[{segment_type or '消息'}]"
            )

    text = "".join(
        parts
    ).strip()
    return text or raw.strip()


@dataclass(frozen=True)
class QQMessageEvent:
    time: int
    self_id: int
    message_type: str
    sub_type: str
    message_id: int
    user_id: int
    group_id: int | None
    nickname: str
    text: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "QQMessageEvent":
        sender = data.get(
            "sender",
            {},
        )
        if not isinstance(
            sender,
            dict,
        ):
            sender = {}

        group_raw = data.get(
            "group_id"
        )
        group_id = (
            _as_int(group_raw)
            if group_raw
            is not None
            else None
        )

        return cls(
            time=_as_int(
                data.get(
                    "time"
                )
            ),
            self_id=_as_int(
                data.get(
                    "self_id"
                )
            ),
            message_type=str(
                data.get(
                    "message_type",
                    "",
                )
            ),
            sub_type=str(
                data.get(
                    "sub_type",
                    "",
                )
            ),
            message_id=_as_int(
                data.get(
                    "message_id"
                )
            ),
            user_id=_as_int(
                data.get(
                    "user_id"
                )
            ),
            group_id=group_id,
            nickname=str(
                sender.get(
                    "nickname",
                    "",
                )
                or sender.get(
                    "card",
                    "",
                )
                or ""
            ),
            text=extract_message_text(
                data
            ),
            raw=dict(data),
        )

    def occurred_at(
        self,
        timezone,
    ) -> datetime:
        if self.time > 0:
            return datetime.fromtimestamp(
                self.time,
                tz=timezone,
            )
        return datetime.now(
            timezone
        )


@dataclass(frozen=True)
class QQFriendRequestEvent:
    time: int
    self_id: int
    user_id: int
    comment: str
    flag: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "QQFriendRequestEvent":
        return cls(
            time=_as_int(
                data.get(
                    "time"
                )
            ),
            self_id=_as_int(
                data.get(
                    "self_id"
                )
            ),
            user_id=_as_int(
                data.get(
                    "user_id"
                )
            ),
            comment=str(
                data.get(
                    "comment",
                    "",
                )
            ),
            flag=str(
                data.get(
                    "flag",
                    "",
                )
            ),
            raw=dict(data),
        )
