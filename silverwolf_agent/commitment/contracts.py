"""Lv27: 长期任务承诺的数据契约。

用户不会把一项长期任务说全，例如：

    "我以后每周的周末打算完成创新创业基础的视频学习"

这句话缺 `几点开始`、`从哪天算起`、`持续几周`。Lv27 用
`CommitmentSeed` 表示"还没补全的承诺"，用 `Commitment` 表示
"已经补全并落库的承诺"，用 `ClarificationSession` 表示
"正在追问中的会话"，并在 `CommitmentTurn` 里把一轮结果交回 PAE。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import uuid

WEEKDAY_NAMES: tuple[str, ...] = (
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
)

WEEKDAY_FULL_NAMES: tuple[str, ...] = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)

# 槽位顺序即追问优先级：先问什么时候开始，再问钟点、周几、几周。
SLOT_START = "start"
SLOT_CLOCK = "clock"
SLOT_WEEKDAYS = "weekdays"
SLOT_WEEKS = "weeks"

SLOT_ORDER: tuple[str, ...] = (
    SLOT_START,
    SLOT_CLOCK,
    SLOT_WEEKDAYS,
    SLOT_WEEKS,
)

SLOT_LABELS: dict[str, str] = {
    SLOT_START: "开始时间",
    SLOT_CLOCK: "当天几点开始",
    SLOT_WEEKDAYS: "每周哪几天",
    SLOT_WEEKS: "一共持续几周",
}


def weekday_label(index: int, *, full: bool = False) -> str:
    if not 0 <= int(index) <= 6:
        return ""
    table = WEEKDAY_FULL_NAMES if full else WEEKDAY_NAMES
    return table[int(index)]


def weekday_list_label(indexes: tuple[int, ...] | list[int]) -> str:
    """把 (5, 6) 渲染成“周六、周日”，把 (0..4) 渲染成“周一到周五”。"""
    values = sorted({int(item) for item in indexes if 0 <= int(item) <= 6})
    if not values:
        return ""
    if values == [5, 6]:
        return "周六、周日"
    if values == [0, 1, 2, 3, 4]:
        return "周一到周五"
    if len(values) == 1:
        return weekday_label(values[0])
    return "、".join(weekday_label(item) for item in values)


@dataclass
class CommitmentSeed:
    """还没补全的承诺：只包含用户这句话里能确定的部分。"""

    title: str
    source_text: str
    weekdays: tuple[int, ...] = ()
    clock: str = ""
    weeks: int = 0
    starts_on: str = ""
    soft_weekend: bool = False

    def known_slots(self) -> set[str]:
        known: set[str] = set()
        if self.starts_on:
            known.add(SLOT_START)
        if self.clock:
            known.add(SLOT_CLOCK)
        if self.weekdays:
            known.add(SLOT_WEEKDAYS)
        if self.weeks > 0:
            known.add(SLOT_WEEKS)
        return known

    def missing_slots(self) -> list[str]:
        known = self.known_slots()
        return [slot for slot in SLOT_ORDER if slot not in known]

    def is_complete(self) -> bool:
        return not self.missing_slots()

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "source_text": self.source_text,
            "weekdays": list(self.weekdays),
            "clock": self.clock,
            "weeks": self.weeks,
            "starts_on": self.starts_on,
            "soft_weekend": self.soft_weekend,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, object],
    ) -> "CommitmentSeed":
        raw_weekdays = data.get("weekdays", [])
        weekdays: tuple[int, ...] = ()
        if isinstance(raw_weekdays, (list, tuple)):
            weekdays = tuple(
                sorted(
                    {
                        int(item)
                        for item in raw_weekdays
                        if isinstance(item, (int, str))
                        and str(item).isdigit()
                        and 0 <= int(item) <= 6
                    }
                )
            )
        return cls(
            title=str(data.get("title", "")).strip(),
            source_text=str(data.get("source_text", "")).strip(),
            weekdays=weekdays,
            clock=str(data.get("clock", "")).strip(),
            weeks=int(data.get("weeks", 0) or 0),
            starts_on=str(data.get("starts_on", "")).strip(),
            soft_weekend=bool(data.get("soft_weekend", False)),
        )


@dataclass
class Commitment:
    """已经补全的长期承诺。"""

    commitment_id: str
    title: str
    clock: str
    weekdays: tuple[int, ...]
    total_weeks: int
    starts_on: str
    created_at: str
    source_text: str = ""
    status: str = "active"
    soft_weekend: bool = True
    completed_weeks: list[int] = field(default_factory=list)
    skipped_weeks: list[int] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    # ---------- 生成与统计 ----------

    def start_date(self) -> date:
        try:
            return date.fromisoformat(self.starts_on)
        except ValueError:
            return date.today()

    def week_date(self, week_index: int) -> date:
        """第 week_index 周（1 基）的第一个提醒日。"""
        base = self.start_date()
        offset = max(0, int(week_index) - 1) * 7
        return base + timedelta(days=offset)

    def occurrences(self, limit: int = 8, *, from_week: int = 1) -> list[dict[str, object]]:
        """把剩余周次展开成可物化的 occurrence 列表。"""
        items: list[dict[str, object]] = []
        week = max(1, int(from_week))
        while week <= self.total_weeks and len(items) < limit:
            if week in self.completed_weeks or week in self.skipped_weeks:
                week += 1
                continue
            for day_index, weekday in enumerate(self.weekdays):
                occurrence_date = (
                    self._date_in_week(week, weekday)
                )
                items.append(
                    {
                        "commitment_id": self.commitment_id,
                        "week_index": week,
                        "total_weeks": self.total_weeks,
                        "date": occurrence_date.isoformat(),
                        "weekday": weekday,
                        "is_primary": day_index == 0,
                        "soft": bool(self.soft_weekend and day_index > 0),
                    }
                )
                if len(items) >= limit:
                    break
            week += 1
        return items

    def _date_in_week(self, week_index: int, weekday: int) -> date:
        base = self.week_date(week_index)
        delta = int(weekday) - base.weekday()
        return base + timedelta(days=delta)

    def current_week(self) -> int:
        for week in range(1, self.total_weeks + 1):
            if week in self.completed_weeks or week in self.skipped_weeks:
                continue
            return week
        return self.total_weeks

    def remaining_weeks(self) -> int:
        done = len(set(self.completed_weeks) | set(self.skipped_weeks))
        return max(0, self.total_weeks - done)

    def is_finished(self) -> bool:
        return self.status != "active"

    def summary(self) -> str:
        return (
            f"{self.title}｜每周{weekday_list_label(self.weekdays)} "
            f"{self.clock}｜共 {self.total_weeks} 周｜"
            f"已完成 {len(self.completed_weeks)} 周"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "commitment_id": self.commitment_id,
            "title": self.title,
            "clock": self.clock,
            "weekdays": list(self.weekdays),
            "total_weeks": self.total_weeks,
            "starts_on": self.starts_on,
            "created_at": self.created_at,
            "source_text": self.source_text,
            "status": self.status,
            "soft_weekend": self.soft_weekend,
            "completed_weeks": list(self.completed_weeks),
            "skipped_weeks": list(self.skipped_weeks),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Commitment":
        raw_weekdays = data.get("weekdays", [])
        weekdays: tuple[int, ...] = ()
        if isinstance(raw_weekdays, (list, tuple)):
            weekdays = tuple(
                sorted(
                    {
                        int(item)
                        for item in raw_weekdays
                        if str(item).isdigit() and 0 <= int(item) <= 6
                    }
                )
            )
        completed = data.get("completed_weeks", [])
        skipped = data.get("skipped_weeks", [])
        return cls(
            commitment_id=str(data.get("commitment_id", "") or uuid.uuid4().hex[:12]),
            title=str(data.get("title", "")).strip() or "那件事",
            clock=str(data.get("clock", "")).strip() or "10:00",
            weekdays=weekdays or (5, 6),
            total_weeks=max(1, int(data.get("total_weeks", 1) or 1)),
            starts_on=str(data.get("starts_on", "")).strip(),
            created_at=str(data.get("created_at", "")).strip(),
            source_text=str(data.get("source_text", "")).strip(),
            status=str(data.get("status", "active")).strip() or "active",
            soft_weekend=bool(data.get("soft_weekend", True)),
            completed_weeks=[
                int(item) for item in completed if str(item).isdigit()
            ]
            if isinstance(completed, (list, tuple))
            else [],
            skipped_weeks=[
                int(item) for item in skipped if str(item).isdigit()
            ]
            if isinstance(skipped, (list, tuple))
            else [],
            metadata=dict(data.get("metadata", {}))
            if isinstance(data.get("metadata"), dict)
            else {},
        )


@dataclass
class ClarificationSession:
    """正在追问中的补全会话。

    用户随时可能只回答一半、改口、打断或直接取消，所以会话必须
    持久化，重启后仍能接着问，并且 24 小时后自然过期。
    """

    session_id: str
    seed: CommitmentSeed
    asked_slots: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    status: str = "collecting"
    turns: int = 0

    def is_open(self) -> bool:
        return self.status == "collecting"

    def expired(self, now: datetime) -> bool:
        if not self.expires_at:
            return False
        try:
            deadline = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return True
        if deadline.tzinfo is None and now.tzinfo is not None:
            deadline = deadline.replace(tzinfo=now.tzinfo)
        return now >= deadline

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "seed": self.seed.to_dict(),
            "asked_slots": list(self.asked_slots),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "turns": self.turns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ClarificationSession":
        raw_seed = data.get("seed", {})
        asked = data.get("asked_slots", [])
        return cls(
            session_id=str(data.get("session_id", "") or uuid.uuid4().hex[:12]),
            seed=CommitmentSeed.from_dict(
                raw_seed if isinstance(raw_seed, dict) else {}
            ),
            asked_slots=[str(item) for item in asked]
            if isinstance(asked, (list, tuple))
            else [],
            created_at=str(data.get("created_at", "")).strip(),
            updated_at=str(data.get("updated_at", "")).strip(),
            expires_at=str(data.get("expires_at", "")).strip(),
            status=str(data.get("status", "collecting")).strip() or "collecting",
            turns=int(data.get("turns", 0) or 0),
        )


@dataclass
class CommitmentTurn:
    """一轮承诺处理结果，供 Planner 生成 goal、Executor 渲染措辞。"""

    mode: str  # none | question | confirm | status | update
    goal_kind: str = ""
    fallback_text: str = ""
    scene: str = ""
    facts: dict[str, object] = field(default_factory=dict)
    commitment: Commitment | None = None
    seeds: list[dict[str, object]] = field(default_factory=list)

    @staticmethod
    def nothing() -> "CommitmentTurn":
        return CommitmentTurn(mode="none")
