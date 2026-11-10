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
from ..memory.short_term import (
    ShortTermMemory,
)


class IdentityRecallSkill(BaseSkill):
    """
    处理简单身份确认。

    这类问题是在确认关系和记忆，不是在要求
    Agent 背诵用户简历，因此禁止输出学历、
    技术能力、兴趣列表等背景资料。
    """

    name = "identity_recall"
    priority = 10

    SIMPLE_PATTERN = re.compile(
        (
            r"^(?:那|那么|所以)?"
            r"(?:你)?(?:还)?记得我"
            r"(?:吗|不|么)?"
            r"[？?。！!]*$"
            r"|^(?:那|那么|所以)?"
            r"(?:你知道)?我是谁"
            r"(?:吗)?"
            r"[？?。！!]*$"
        )
    )

    def __init__(
        self,
        profile: UserProfileManager,
        memory: ShortTermMemory,
        recent_turn_limit: int = 6,
    ) -> None:
        self.profile = profile
        self.memory = memory
        self.recent_turn_limit = (
            recent_turn_limit
        )

    @classmethod
    def is_identity_check(
        cls,
        text: str,
    ) -> bool:
        return bool(
            cls.SIMPLE_PATTERN.fullmatch(
                text.strip()
            )
        )

    def _recent_check_count(
        self,
    ) -> int:
        turns = (
            self.memory.snapshot()
            .get("recent_turns", [])
        )
        return sum(
            1
            for turn in turns[
                -self.recent_turn_limit:
            ]
            if self.is_identity_check(
                str(
                    turn.get(
                        "user",
                        "",
                    )
                )
            )
        )

    def can_handle(
        self,
        context: SkillContext,
    ) -> bool:
        return self.is_identity_check(
            context.user_input
        )

    def execute(
        self,
        context: SkillContext,
    ) -> SkillResult:
        name = self.profile.preferred_name()
        casual = self.profile.casual_alias()
        previous = self._recent_check_count()

        if previous == 0:
            response = (
                f"当然记得你，{name}。"
                "我怎么会忘。"
            )
        elif previous == 1:
            response = (
                f"刚问过呀，{casual}。"
                "我当然记得。"
            )
        else:
            response = (
                f"还在确认啊，{name}？"
                "我没忘。"
                "怎么突然这么不放心？"
            )

        return SkillResult(
            handled=True,
            response=response,
            metadata={
                "recall_kind": "identity",
                "previous_identity_checks": (
                    previous
                ),
            },
        )
