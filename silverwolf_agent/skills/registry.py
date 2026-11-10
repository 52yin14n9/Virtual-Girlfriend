from __future__ import annotations

from .base import BaseSkill, SkillContext, SkillResult


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: list[BaseSkill] = []

    def register(self, skill: BaseSkill) -> None:
        self._skills.append(skill)
        self._skills.sort(key=lambda item: item.priority)

    def dispatch(self, context: SkillContext) -> SkillResult:
        for skill in self._skills:
            if skill.can_handle(context):
                result = skill.execute(context)
                if result.handled:
                    return result
        return SkillResult(handled=False)
