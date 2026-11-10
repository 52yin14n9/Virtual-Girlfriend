from __future__ import annotations

import re

from .base import (
    BaseSkill,
    SkillContext,
    SkillResult,
)
from ..memory.profile import (
    UserProfileManager,
)


class AddressRecallSkill(BaseSkill):
    name = "address_recall"
    priority = 8

    PATTERN = re.compile(
        (
            r"(你平常会叫我什么|"
            r"你平时叫我什么|"
            r"你会怎么叫我|"
            r"你一般叫我什么|"
            r"你叫我什么)"
        )
    )

    def __init__(
        self,
        profile: UserProfileManager,
    ) -> None:
        self.profile = profile

    def can_handle(
        self,
        context: SkillContext,
    ) -> bool:
        return bool(
            self.PATTERN.search(
                context.user_input
            )
        )

    def execute(
        self,
        context: SkillContext,
    ) -> SkillResult:
        name = self.profile.preferred_name()
        casual = self.profile.casual_alias()
        return SkillResult(
            handled=True,
            response=(
                f"平时叫你{name}。"
                f"想亲近一点的时候，就叫你{casual}。"
            ),
        )
