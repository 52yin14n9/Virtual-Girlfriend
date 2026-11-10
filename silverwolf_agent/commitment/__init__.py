"""Lv27: 长期任务承诺（多周课程 / 习惯类任务）。

一句话入口：

    service = CommitmentService(plan_manager=plan_manager)
    turn = service.handle("我以后每周的周末打算完成创新创业基础的视频学习", now)

`turn.mode == "question"` 表示需要先问清参数；`turn.mode == "confirm"`
表示已经落库并物化了到期计划。
"""

from .contracts import (
    SLOT_CLOCK,
    SLOT_LABELS,
    SLOT_ORDER,
    SLOT_START,
    SLOT_WEEKDAYS,
    SLOT_WEEKS,
    WEEKDAY_NAMES,
    ClarificationSession,
    Commitment,
    CommitmentSeed,
    CommitmentTurn,
    weekday_label,
    weekday_list_label,
)
from .intent import CommitmentIntentAnalyzer, chinese_number, resolve_start_date
from .service import (
    GOAL_CLARIFY,
    GOAL_CONFIRM,
    GOAL_FINISH,
    GOAL_STATUS,
    GOAL_UPDATE,
    PLAN_KIND,
    SCENE_CONFIRM,
    SCENE_DUE,
    SCENE_FINISH,
    SCENE_QUESTION,
    SCENE_UPDATE,
    CommitmentService,
)
from .store import ClarificationStore, CommitmentStore

__all__ = [
    "SLOT_CLOCK",
    "SLOT_LABELS",
    "SLOT_ORDER",
    "SLOT_START",
    "SLOT_WEEKDAYS",
    "SLOT_WEEKS",
    "WEEKDAY_NAMES",
    "ClarificationSession",
    "ClarificationStore",
    "Commitment",
    "CommitmentIntentAnalyzer",
    "CommitmentSeed",
    "CommitmentService",
    "CommitmentStore",
    "CommitmentTurn",
    "GOAL_CLARIFY",
    "GOAL_CONFIRM",
    "GOAL_FINISH",
    "GOAL_STATUS",
    "GOAL_UPDATE",
    "PLAN_KIND",
    "SCENE_CONFIRM",
    "SCENE_DUE",
    "SCENE_FINISH",
    "SCENE_QUESTION",
    "SCENE_UPDATE",
    "chinese_number",
    "resolve_start_date",
    "weekday_label",
    "weekday_list_label",
]
