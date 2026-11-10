from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
from typing import (
    Any,
    Callable,
)

from ..paths import (
    SHORT_MEMORY_PATH,
    ensure_directories,
)


class ShortTermMemory:
    def __init__(
        self,
        path: Path = SHORT_MEMORY_PATH,
        max_recent_turns: int = 30,
    ) -> None:
        ensure_directories()
        self.path = path
        self.max_recent_turns = (
            max_recent_turns
        )
        self._lock = threading.RLock()

        if not self.path.exists():
            self._write(
                {
                    "summary": "",
                    "recent_turns": [],
                    "updated_at": None,
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
                json.JSONDecodeError,
                FileNotFoundError,
            ):
                return {
                    "summary": "",
                    "recent_turns": [],
                    "updated_at": None,
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

    @staticmethod
    def _timestamp(
        value: datetime | None,
    ) -> str:
        current = (
            value
            or datetime.now().astimezone()
        )
        if current.tzinfo is None:
            current = current.astimezone()
        return current.isoformat(
            timespec="seconds"
        )

    def add_turn(
        self,
        user: str,
        assistant: str,
        *,
        source: str = "interactive",
        at: datetime | None = None,
        assistant_at: datetime | None = None,
    ) -> None:
        with self._lock:
            data = self._read()
            user_at = self._timestamp(at)
            response_at = self._timestamp(
                assistant_at
                or at
            )
            data.setdefault(
                "recent_turns",
                [],
            ).append(
                {
                    # `at` is retained for old code.
                    "at": user_at,
                    "user_at": user_at,
                    "assistant_at": (
                        response_at
                    ),
                    "source": source,
                    "user": user,
                    "assistant": assistant,
                }
            )
            data["updated_at"] = (
                response_at
            )
            self._write(data)

    def add_user_message(
        self,
        user: str,
        *,
        at: datetime | None = None,
        source: str = "interactive_silent",
    ) -> None:
        """Record a user turn when the reply gate intentionally stays silent."""
        self.add_turn(
            user,
            "",
            source=source,
            at=at,
            assistant_at=at,
        )

    def add_proactive_message(
        self,
        assistant: str,
        *,
        at: datetime | None = None,
    ) -> None:
        self.add_turn(
            "",
            assistant,
            source="proactive",
            at=at,
            assistant_at=at,
        )

    def latest_user_turn(
        self,
        *,
        keyword: str | None = None,
    ) -> dict[str, Any] | None:
        turns = self._read().get(
            "recent_turns",
            [],
        )
        normalized = (
            keyword.strip()
            if keyword
            else ""
        )

        for turn in reversed(turns):
            user_text = str(
                turn.get(
                    "user",
                    "",
                )
            ).strip()
            if not user_text:
                continue
            if (
                normalized
                and normalized
                not in user_text
            ):
                continue
            return dict(turn)

        return None

    def find_user_turn(
        self,
        *,
        mode: str,
        keyword: str = "",
    ) -> dict[str, Any] | None:
        if mode == "latest":
            return self.latest_user_turn()
        if mode == "keyword":
            return self.latest_user_turn(
                keyword=keyword
            )
        raise ValueError(
            "mode 必须是 latest 或 keyword"
        )

    def needs_compaction(self) -> bool:
        return (
            len(
                self._read().get(
                    "recent_turns",
                    [],
                )
            )
            > self.max_recent_turns
        )

    def compact(
        self,
        summarizer: Callable[
            [str],
            str,
        ],
    ) -> None:
        with self._lock:
            data = self._read()
            turns = data.get(
                "recent_turns",
                [],
            )

            if (
                len(turns)
                <= self.max_recent_turns
            ):
                return

            keep_count = max(
                1,
                self.max_recent_turns,
            )
            old_turns = turns[
                :-keep_count
            ]
            recent_turns = turns[
                -keep_count:
            ]

            source = {
                "previous_summary": (
                    data.get(
                        "summary",
                        "",
                    )
                ),
                "old_turns": old_turns,
            }

            try:
                summary = summarizer(
                    json.dumps(
                        source,
                        ensure_ascii=False,
                    )
                )
            except Exception:
                snippets = []
                if data.get("summary"):
                    snippets.append(
                        data["summary"]
                    )

                for turn in old_turns[-4:]:
                    timestamp = str(
                        turn.get(
                            "user_at",
                            turn.get(
                                "at",
                                "",
                            ),
                        )
                    )
                    if (
                        turn.get("source")
                        == "proactive"
                    ):
                        snippets.append(
                            f"[{timestamp}] "
                            "银狼主动消息："
                            + str(
                                turn.get(
                                    "assistant",
                                    "",
                                )
                            )
                        )
                    else:
                        snippets.append(
                            f"[{timestamp}] "
                            "用户："
                            + str(
                                turn.get(
                                    "user",
                                    "",
                                )
                            )
                            + "；银狼："
                            + str(
                                turn.get(
                                    "assistant",
                                    "",
                                )
                            )
                        )

                summary = " | ".join(
                    snippets
                )[-1800:]

            data["summary"] = (
                summary.strip()
            )
            data["recent_turns"] = (
                recent_turns
            )
            data["updated_at"] = (
                self._timestamp(None)
            )
            self._write(data)

    def context_text(self) -> str:
        data = self._read()
        parts: list[str] = []

        summary = str(
            data.get(
                "summary",
                "",
            )
        ).strip()
        if summary:
            parts.append(
                "短期记忆摘要：\n"
                + summary
            )

        turns = data.get(
            "recent_turns",
            [],
        )
        if turns:
            formatted = []
            for turn in turns:
                user_at = str(
                    turn.get(
                        "user_at",
                        turn.get(
                            "at",
                            "",
                        ),
                    )
                )
                assistant_at = str(
                    turn.get(
                        "assistant_at",
                        user_at,
                    )
                )
                assistant = str(
                    turn.get(
                        "assistant",
                        "",
                    )
                )

                if (
                    turn.get("source")
                    == "proactive"
                ):
                    formatted.append(
                        f"[{assistant_at}] "
                        "银狼（主动）："
                        + assistant
                    )
                else:
                    user_line = (
                        f"[{user_at}] 用户："
                        + str(
                            turn.get(
                                "user",
                                "",
                            )
                        )
                    )
                    if assistant:
                        user_line += (
                            "\n"
                            + f"[{assistant_at}] 银狼："
                            + assistant
                        )
                    formatted.append(user_line)

            parts.append(
                "最近对话（时间戳为事实，"
                "回答历史时间问题时不得猜测）：\n"
                + "\n\n".join(
                    formatted
                )
            )

        return (
            "\n\n".join(parts)
            or "暂无短期记忆。"
        )

    def recent_chat_messages(
        self,
        limit: int = 30,
    ) -> list[dict[str, str]]:
        """
        返回最近若干轮的真实 user/assistant 消息序列。

        每个 recent_turn 代表一轮对话；主动消息只产生
        assistant 消息。该结构用于直接传给模型，而不是
        只把历史埋在系统提示文本中。
        """
        turns = self._read().get(
            "recent_turns",
            [],
        )
        selected = turns[
            -max(1, int(limit)):
        ]
        messages: list[
            dict[str, str]
        ] = []

        for turn in selected:
            source = str(
                turn.get(
                    "source",
                    "interactive",
                )
            )
            user_text = str(
                turn.get(
                    "user",
                    "",
                )
            ).strip()
            assistant_text = str(
                turn.get(
                    "assistant",
                    "",
                )
            ).strip()

            if (
                source != "proactive"
                and user_text
            ):
                messages.append(
                    {
                        "role": "user",
                        "content": user_text,
                    }
                )

            if assistant_text:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text,
                    }
                )

        normalized: list[
            dict[str, str]
        ] = []
        for message in messages:
            role = message["role"]
            content = message[
                "content"
            ]

            # Anthropic-compatible APIs expect
            # a usable alternating conversation.
            # Leading proactive assistant messages
            # remain available in context_text(),
            # but are not used as the first API role.
            if (
                not normalized
                and role == "assistant"
            ):
                continue

            if (
                normalized
                and normalized[-1][
                    "role"
                ] == role
            ):
                normalized[-1][
                    "content"
                ] += (
                    "\n\n"
                    + content
                )
            else:
                normalized.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

        return normalized

    def recent_user_text(
        self,
        limit: int = 8,
    ) -> str:
        turns = self._read().get(
            "recent_turns",
            [],
        )
        values = [
            str(
                turn.get(
                    "user",
                    "",
                )
            )
            for turn in turns[-limit:]
            if str(
                turn.get(
                    "user",
                    "",
                )
            ).strip()
        ]
        return "\n".join(values)

    def snapshot(
        self,
    ) -> dict[str, Any]:
        return self._read()
