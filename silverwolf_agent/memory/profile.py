from __future__ import annotations

import copy
from datetime import date, datetime
import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..paths import (
    DEFAULT_PROFILE_PATH,
    USER_PROFILE_PATH,
    ensure_directories,
)


class UserProfileManager:
    CURRENT_SCHEMA_VERSION = 19
    DEFAULT_PREFERRED_NAME = "星"
    DEFAULT_CASUAL_ALIAS = "宝"

    def __init__(
        self,
        path: Path = USER_PROFILE_PATH,
        default_path: Path = DEFAULT_PROFILE_PATH,
    ) -> None:
        ensure_directories()
        self.path = path
        self.default_path = default_path

        if not self.path.exists():
            shutil.copyfile(
                self.default_path,
                self.path,
            )

        self._migrate_profile()

    def _read_raw(self) -> dict[str, Any]:
        return json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )

    def _migrate_profile(self) -> None:
        """
        将旧版档案兼容升级到当前稳定用户档案结构。

        即使用户直接复制旧版 data 文件夹，
        也会自动补上“星”和“宝”的称呼规则。
        """
        profile = self._read_raw()
        changed = False

        if (
            profile.get("schema_version", 0)
            < self.CURRENT_SCHEMA_VERSION
        ):
            profile["schema_version"] = (
                self.CURRENT_SCHEMA_VERSION
            )
            changed = True

        dynamic = profile.setdefault(
            "dynamic",
            {},
        )

        preferred_name = dynamic.get(
            "preferred_name"
        )
        if (
            not isinstance(
                preferred_name,
                str,
            )
            or not preferred_name.strip()
        ):
            dynamic["preferred_name"] = (
                self.DEFAULT_PREFERRED_NAME
            )
            changed = True

        aliases = dynamic.get(
            "casual_aliases"
        )
        if not isinstance(aliases, list):
            aliases = []
            dynamic["casual_aliases"] = aliases
            changed = True

        if (
            self.DEFAULT_CASUAL_ALIAS
            not in aliases
        ):
            aliases.append(
                self.DEFAULT_CASUAL_ALIAS
            )
            changed = True

        style = dynamic.get(
            "address_style"
        )
        expected_style = {
            "default": dynamic[
                "preferred_name"
            ],
            "casual": (
                self.DEFAULT_CASUAL_ALIAS
            ),
            "casual_usage": (
                "仅在轻松、亲密、不严肃的"
                "场景偶尔使用"
            ),
        }
        if not isinstance(style, dict):
            dynamic["address_style"] = (
                expected_style
            )
            changed = True
        else:
            for key, value in (
                expected_style.items()
            ):
                if style.get(key) != value:
                    style[key] = value
                    changed = True

        if changed:
            self.save(
                profile,
                reason="automatic_lv18_migration",
            )

    def load(self) -> dict[str, Any]:
        return self._read_raw()

    def save(
        self,
        profile: dict[str, Any],
        reason: str,
    ) -> None:
        profile = copy.deepcopy(profile)
        profile.setdefault("metadata", {})
        profile["metadata"][
            "last_updated_at"
        ] = datetime.now().isoformat(
            timespec="seconds"
        )
        profile["metadata"][
            "last_update_reason"
        ] = reason
        self.path.write_text(
            json.dumps(
                profile,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def age_on(
        self,
        today: date,
    ) -> int | None:
        birthday = (
            self.load()
            .get("stable", {})
            .get("birthday")
        )
        if not birthday:
            return None

        try:
            born = date.fromisoformat(
                birthday
            )
        except ValueError:
            return None

        return today.year - born.year - (
            (today.month, today.day)
            < (born.month, born.day)
        )

    def set_path(
        self,
        dotted_path: str,
        value: Any,
        reason: str = "manual_update",
    ) -> None:
        allowed_roots = {
            "stable",
            "dynamic",
        }
        parts = [
            part
            for part in dotted_path.split(".")
            if part
        ]
        if (
            not parts
            or parts[0]
            not in allowed_roots
        ):
            raise ValueError(
                "档案路径必须从 stable "
                "或 dynamic 开始"
            )

        profile = self.load()
        cursor: dict[str, Any] = profile

        for part in parts[:-1]:
            next_value = cursor.get(part)
            if not isinstance(
                next_value,
                dict,
            ):
                next_value = {}
                cursor[part] = next_value
            cursor = next_value

        cursor[parts[-1]] = value
        self.save(
            profile,
            reason=reason,
        )

    def preferred_name(self) -> str:
        value = (
            self.load()
            .get("dynamic", {})
            .get("preferred_name")
        )
        if (
            isinstance(value, str)
            and value.strip()
        ):
            return value.strip()
        return self.DEFAULT_PREFERRED_NAME

    def casual_alias(self) -> str:
        aliases = (
            self.load()
            .get("dynamic", {})
            .get("casual_aliases", [])
        )
        if isinstance(aliases, list):
            for value in aliases:
                if (
                    isinstance(value, str)
                    and value.strip()
                ):
                    return value.strip()
        return self.DEFAULT_CASUAL_ALIAS

    def set_preferred_name(
        self,
        name: str,
        reason: str = (
            "explicit_name_preference"
        ),
    ) -> None:
        cleaned = name.strip().strip(
            "。！？!?，, "
        )
        if not cleaned:
            raise ValueError("称呼不能为空")
        if len(cleaned) > 20:
            raise ValueError("称呼过长")

        profile = self.load()
        dynamic = profile.setdefault(
            "dynamic",
            {},
        )
        dynamic["preferred_name"] = cleaned
        style = dynamic.setdefault(
            "address_style",
            {},
        )
        style["default"] = cleaned
        style.setdefault(
            "casual",
            self.DEFAULT_CASUAL_ALIAS,
        )
        style.setdefault(
            "casual_usage",
            (
                "仅在轻松、亲密、不严肃的"
                "场景偶尔使用"
            ),
        )
        self.save(
            profile,
            reason=reason,
        )

    def infer_explicit_updates(
        self,
        user_text: str,
    ) -> list[str]:
        """
        仅提取少量明确事实，避免过度推断。
        """
        updates: list[str] = []
        profile = self.load()

        birthday_match = re.search(
            (
                r"(?:我的)?生日(?:是|为)\s*"
                r"(\d{4})[年/-](\d{1,2})"
                r"[月/-](\d{1,2})日?"
            ),
            user_text,
        )
        if birthday_match:
            year, month, day = map(
                int,
                birthday_match.groups(),
            )
            birthday = (
                f"{year:04d}-"
                f"{month:02d}-"
                f"{day:02d}"
            )
            if (
                profile.get("stable", {})
                .get("birthday")
                != birthday
            ):
                profile.setdefault(
                    "stable",
                    {},
                )["birthday"] = birthday
                updates.append(
                    f"birthday={birthday}"
                )

        focus_match = re.search(
            (
                r"(?:我现在|我最近)(?:主要)?"
                r"(?:在|正?在)?"
                r"(?:学习|研究|做|准备)\s*"
                r"([^。！？\n]{2,40})"
            ),
            user_text,
        )
        if focus_match:
            focus = (
                focus_match.group(1)
                .strip(" ，,")
            )
            items = (
                profile.setdefault(
                    "dynamic",
                    {},
                )
                .setdefault(
                    "current_focus",
                    [],
                )
            )
            if (
                focus
                and focus not in items
            ):
                items.append(focus)
                updates.append(
                    f"current_focus+={focus}"
                )

        game_match = re.search(
            (
                r"(?:我最近在玩|"
                r"最近主要玩)\s*"
                r"([^。！？\n]{1,80})"
            ),
            user_text,
        )
        if game_match:
            games = [
                item.strip()
                for item in re.split(
                    r"[、,，/和与]",
                    game_match.group(1),
                )
                if item.strip()
            ]
            recent = (
                profile.setdefault(
                    "dynamic",
                    {},
                )
                .setdefault(
                    "recent_games",
                    [],
                )
            )
            for game in games:
                if game not in recent:
                    recent.append(game)
                    updates.append(
                        f"recent_games+={game}"
                    )

        if updates:
            self.save(
                profile,
                reason=(
                    "explicit_user_statement"
                ),
            )

        return updates

    def prompt_view(
        self,
        today: date,
    ) -> dict[str, Any]:
        """
        将关系称呼和背景资料分区。

        背景资料仍可用于理解用户，但明确标记为
        reference_only，降低模型在闲聊中主动念档案
        的概率。
        """
        profile = self.load()
        dynamic = profile.get(
            "dynamic",
            {},
        )

        relationship = {
            "preferred_name": (
                self.preferred_name()
            ),
            "casual_alias": (
                self.casual_alias()
            ),
            "address_rule": (
                "平时称呼为“星”；"
                "轻松亲密且不严肃时，"
                "可以偶尔叫“宝”；"
                "不要每句话都带称呼。"
            ),
        }

        current = {
            key: value
            for key, value in dynamic.items()
            if key not in {
                "preferred_name",
                "casual_aliases",
                "address_style",
            }
        }

        return {
            "relationship": relationship,
            "current_context": current,
            "background_reference_only": (
                profile.get(
                    "stable",
                    {},
                )
            ),
            "computed": {
                "age": self.age_on(today),
                "date": today.isoformat(),
            },
        }
