from __future__ import annotations

import re

from .base import (
    BaseSkill,
    SkillContext,
    SkillResult,
)
from ..memory.rag import (
    JsonlRAGStore,
)
from ..memory.short_term import (
    ShortTermMemory,
)


class MemoryRecallSkill(BaseSkill):
    name = "memory_recall"
    priority = 20

    PATTERN = re.compile(
        (
            r"(我们之前|以前发生|过去发生|"
            r"上次|前几天|之前聊过|回忆一下|"
            r"你记得我哪些|你还记得我什么|"
            r"你对我了解多少|说说你记得的我)"
        )
    )

    def __init__(
        self,
        memory: ShortTermMemory,
        rag: JsonlRAGStore,
    ) -> None:
        self.memory = memory
        self.rag = rag

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
        short_context = (
            self.memory.context_text()
        )
        docs = self.rag.search(
            context.user_input,
            top_k=4,
        )
        rag_text = "\n\n".join(
            (
                f"[{doc.metadata.get('date', doc.created_at)}] "
                f"{doc.text}"
            )
            for doc in docs
        )

        detail_request = bool(
            re.search(
                (
                    r"(你记得我哪些|"
                    r"你还记得我什么|"
                    r"你对我了解多少|"
                    r"说说你记得的我)"
                ),
                context.user_input,
            )
        )

        return SkillResult(
            handled=False,
            metadata={
                "recall_requested": True,
                "recall_kind": (
                    "profile_details"
                    if detail_request
                    else "past_event"
                ),
                "short_context": short_context,
                "rag_context": (
                    rag_text
                    or (
                        "长期记忆中没有"
                        "检索到匹配记录。"
                    )
                ),
            },
        )
