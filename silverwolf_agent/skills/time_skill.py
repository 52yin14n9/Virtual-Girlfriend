from __future__ import annotations

from datetime import date, datetime

from .base import BaseSkill, SkillContext, SkillResult
from ..memory.profile import UserProfileManager
from ..memory.short_term import ShortTermMemory
from ..temporal import TemporalQueryAnalyzer, WEEKDAY_CN


class TimeSkill(BaseSkill):
    """Compatibility skill for deterministic clock and calendar questions."""

    name = "time_skill"
    priority = 10

    def __init__(
        self,
        memory: ShortTermMemory,
        profile: UserProfileManager,
        recent_turn_limit: int = 5,
    ) -> None:
        self.memory = memory
        self.profile = profile
        self.recent_turn_limit = recent_turn_limit

    @classmethod
    def is_time_question(cls, text: str) -> bool:
        return TemporalQueryAnalyzer.is_temporal_question(text)

    def _recent_clock_count(self) -> int:
        turns = self.memory.snapshot().get("recent_turns", [])
        count = 0
        for turn in turns[-self.recent_turn_limit:]:
            query = TemporalQueryAnalyzer.analyze(
                str(turn.get("user", "")),
                # Only the query kind matters here; use a stable aware timestamp.
                datetime.now().astimezone(),
            )
            if query is not None and query.kind == "time":
                count += 1
        return count

    def can_handle(self, context: SkillContext) -> bool:
        return TemporalQueryAnalyzer.analyze(
            context.user_input,
            context.now,
        ) is not None

    def execute(self, context: SkillContext) -> SkillResult:
        query = TemporalQueryAnalyzer.analyze(
            context.user_input,
            context.now,
        )
        if query is None:
            return SkillResult(handled=False)

        if query.kind == "time":
            previous = self._recent_clock_count()
            value = context.now.strftime("%H:%M")
            if previous == 0:
                response = f"现在 {value}。"
            elif previous == 1:
                response = f"还是 {value}，{self.profile.casual_alias()}。"
            else:
                response = f"时间没跑那么快，还是 {value}。"
            return SkillResult(
                handled=True,
                response=response,
                metadata={"previous_time_questions": previous},
            )

        target = date.fromisoformat(query.target_date)
        weekday = WEEKDAY_CN[target.weekday()]
        relation = query.relation_label.strip()
        natural_subject = relation if relation and not any(ch.isdigit() for ch in relation) else ""
        date_text = (
            f"{target.year}年{target.month}月{target.day}日"
            if query.include_year
            else f"{target.month}月{target.day}日"
        )

        if query.kind == "weekday":
            response = (
                f"{natural_subject}是{weekday}。"
                if natural_subject
                else f"{date_text}是{weekday}。"
            )
        elif query.kind == "date":
            response = (
                f"{natural_subject}是{date_text}。"
                if natural_subject
                else f"是{date_text}。"
            )
        else:
            response = (
                f"{natural_subject}是{date_text}，{weekday}。"
                if natural_subject
                else f"{date_text}是{weekday}。"
            )

        return SkillResult(
            handled=True,
            response=response,
            metadata={"temporal_query": query.to_dict()},
        )
