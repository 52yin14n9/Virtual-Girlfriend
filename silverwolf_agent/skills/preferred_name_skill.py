from __future__ import annotations

import re

from .base import (
    BaseSkill,
    SkillContext,
    SkillResult,
)
from ..memory.profile import UserProfileManager


class PreferredNameSkill(BaseSkill):
    name = "preferred_name"
    priority = 5

    PATTERNS = (
        re.compile(
            (
                r"^(?:以后|之后)(?:你)?(?:就)?"
                r"叫我(?P<name>"
                r"[^。！？!?，,\n]{1,20})"
                r"[。！？!?]?$"
            )
        ),
        re.compile(
            (
                r"^(?:你可以|可以)(?:以后)?"
                r"叫我(?P<name>"
                r"[^。！？!?，,\n]{1,20})"
                r"[。！？!?]?$"
            )
        ),
        re.compile(
            (
                r"^(?:我想让你|我希望你)(?:以后)?"
                r"叫我(?P<name>"
                r"[^。！？!?，,\n]{1,20})"
                r"[。！？!?]?$"
            )
        ),
    )

    def __init__(
        self,
        profile: UserProfileManager,
    ) -> None:
        self.profile = profile

    def _extract_name(
        self,
        text: str,
    ) -> str | None:
        value = text.strip()
        for pattern in self.PATTERNS:
            match = pattern.fullmatch(value)
            if match:
                name = match.group(
                    "name"
                ).strip()
                return name or None
        return None

    def can_handle(
        self,
        context: SkillContext,
    ) -> bool:
        return (
            self._extract_name(
                context.user_input
            )
            is not None
        )

    def execute(
        self,
        context: SkillContext,
    ) -> SkillResult:
        name = self._extract_name(
            context.user_input
        )
        if name is None:
            return SkillResult(handled=False)

        self.profile.set_preferred_name(name)
        return SkillResult(
            handled=True,
            response=(
                f"嗯，我记下了。以后叫你{name}。"
            ),
            metadata={
                "preferred_name": name,
            },
        )
