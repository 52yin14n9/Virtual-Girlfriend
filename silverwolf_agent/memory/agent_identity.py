from __future__ import annotations

from datetime import (
    date,
    datetime,
)
import json
from pathlib import Path
from typing import Any

from ..paths import (
    DEFAULT_AGENT_PROFILE_PATH,
)


class AgentIdentityManager:
    """
    银狼自身的稳定身份资料。

    当前年龄不写入配置文件，而是根据生日和
    当前日期实时计算，避免跨生日后仍然回答旧年龄。
    """

    def __init__(
        self,
        path: Path = DEFAULT_AGENT_PROFILE_PATH,
    ) -> None:
        self.path = path
        self._data = self._load()

    def _load(
        self,
    ) -> dict[str, Any]:
        data = json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )
        identity = data.get(
            "identity",
            {},
        )
        birthday = str(
            identity.get(
                "birthday",
                "",
            )
        )
        try:
            date.fromisoformat(
                birthday
            )
        except ValueError as exc:
            raise ValueError(
                "Agent birthday 必须是 "
                "YYYY-MM-DD"
            ) from exc
        return data

    def name(self) -> str:
        return str(
            self._data[
                "identity"
            ].get(
                "name",
                "银狼",
            )
        )

    def qq_profile(
        self,
    ) -> dict[str, Any]:
        value = (
            self._data
            .get("identity", {})
            .get("qq", {})
        )
        if not isinstance(value, dict):
            value = {}
        return {
            "has_account": bool(
                value.get("has_account", True)
            ),
            "nickname": str(
                value.get(
                    "nickname",
                    "正在等你说早安",
                )
            ),
            "signature": str(
                value.get(
                    "signature",
                    "正在改写现实，先给你开个后门。本账号不支持注销，终身绑定你",
                )
            ),
            "account_number": value.get(
                "account_number"
            ),
            "account_number_note": str(
                value.get(
                    "account_number_note",
                    "未在人设中配置具体QQ号码，不得猜测或编造。",
                )
            ),
        }

    def birthday(self) -> date:
        return date.fromisoformat(
            str(
                self._data[
                    "identity"
                ]["birthday"]
            )
        )

    def birthday_display(
        self,
    ) -> str:
        value = str(
            self._data[
                "identity"
            ].get(
                "birthday_display",
                "",
            )
        ).strip()
        if value:
            return value

        birthday = self.birthday()
        return (
            f"{birthday.month}月"
            f"{birthday.day}日"
        )

    def age_on(
        self,
        target: (
            date
            | datetime
        ),
    ) -> int:
        current = (
            target.date()
            if isinstance(
                target,
                datetime,
            )
            else target
        )
        birthday = self.birthday()

        age = (
            current.year
            - birthday.year
        )
        if (
            current.month,
            current.day,
        ) < (
            birthday.month,
            birthday.day,
        ):
            age -= 1
        return age

    def birthday_in_year(
        self,
        year: int,
    ) -> date:
        birthday = self.birthday()
        return date(
            year,
            birthday.month,
            birthday.day,
        )

    def next_birthday(
        self,
        target: (
            date
            | datetime
        ),
    ) -> date:
        current = (
            target.date()
            if isinstance(
                target,
                datetime,
            )
            else target
        )
        candidate = (
            self.birthday_in_year(
                current.year
            )
        )
        if candidate < current:
            candidate = (
                self.birthday_in_year(
                    current.year + 1
                )
            )
        return candidate

    def age_after_next_birthday(
        self,
        target: (
            date
            | datetime
        ),
    ) -> int:
        next_date = (
            self.next_birthday(
                target
            )
        )
        return self.age_on(
            next_date
        )

    def prompt_view(
        self,
        target: (
            date
            | datetime
        ),
    ) -> dict[str, Any]:
        current = (
            target.date()
            if isinstance(
                target,
                datetime,
            )
            else target
        )
        next_date = (
            self.next_birthday(
                current
            )
        )
        return {
            "name": self.name(),
            "birthday": (
                self.birthday()
                .isoformat()
            ),
            "birthday_display": (
                self.birthday_display()
            ),
            "current_date": (
                current.isoformat()
            ),
            "current_age": (
                self.age_on(
                    current
                )
            ),
            "next_birthday": (
                next_date
                .isoformat()
            ),
            "age_after_next_birthday": (
                self.age_after_next_birthday(
                    current
                )
            ),
            "qq": self.qq_profile(),
            "age_rule": (
                "年龄由生日和当前日期动态计算，"
                "禁止把当前年龄写死。"
            ),
        }
