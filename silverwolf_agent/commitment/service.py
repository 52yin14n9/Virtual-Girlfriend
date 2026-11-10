"""Lv27: 长期承诺的编排层。

职责边界：

* `intent.py`   只负责"这句话里有什么"；
* `store.py`    只负责持久化；
* `language.py` 只负责确定性措辞；
* 本文件负责把三者串成一个可靠的事务：
  检测 → 追问 → 补全 → 落库 → 物化到期计划 → 更新进度。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import uuid

from ..proactive.plan_manager import PlanManager
from .contracts import (
    SLOT_CLOCK,
    SLOT_WEEKDAYS,
    SLOT_WEEKS,
    ClarificationSession,
    Commitment,
    CommitmentSeed,
    CommitmentTurn,
)
from .intent import CommitmentIntentAnalyzer, resolve_start_date
from .language import (
    clock_human,
    date_human,
    render_cancel_ack,
    render_confirmation,
    render_edit_ack,
    render_finish,
    render_occurrence_start,
    render_progress,
    render_question,
    render_question_multi,
    render_skip_ack,
    render_week_done,
)
from .store import ClarificationStore, CommitmentStore

GOAL_CLARIFY = "commitment_clarify_question"
GOAL_CONFIRM = "confirm_commitment"
GOAL_STATUS = "commitment_status"
GOAL_FINISH = "commitment_finish"
GOAL_UPDATE = "commitment_update_result"

SCENE_QUESTION = "commitment_question"
SCENE_CONFIRM = "commitment_confirm"
SCENE_DUE = "commitment_due"
SCENE_FINISH = "commitment_finish"
SCENE_UPDATE = "commitment_update"

PLAN_KIND = "commitment_occurrence"


class CommitmentService:
    def __init__(
        self,
        *,
        plan_manager: PlanManager,
        store: CommitmentStore | None = None,
        clarify_store: ClarificationStore | None = None,
        analyzer: CommitmentIntentAnalyzer | None = None,
        enabled: bool = True,
        default_clock: str = "10:00",
        max_weeks: int = 52,
        soft_weekend: bool = True,
        clarify_expiry_hours: int = 24,
        max_questions: int = 2,
        horizon: int = 6,
    ) -> None:
        self.plan_manager = plan_manager
        self.store = store or CommitmentStore()
        self.clarify_store = clarify_store or ClarificationStore()
        self.analyzer = analyzer or CommitmentIntentAnalyzer()
        self.enabled = bool(enabled)
        self.default_clock = default_clock or "10:00"
        self.max_weeks = max(1, int(max_weeks))
        self.soft_weekend = bool(soft_weekend)
        self.clarify_expiry_hours = max(1, int(clarify_expiry_hours))
        self.max_questions = max(1, min(3, int(max_questions)))
        self.horizon = max(1, int(horizon))

    # ------------------------------------------------------------------
    # 澄清会话
    # ------------------------------------------------------------------

    def pending_session(self, now: datetime) -> ClarificationSession | None:
        session = self.clarify_store.get()
        if session is None or not session.is_open():
            return None
        if session.expired(now):
            session.status = "expired"
            self.clarify_store.save(session)
            return None
        return session

    def has_pending_clarification(self, now: datetime) -> bool:
        """Reply Gate 用：正在等用户补全参数时，不能被判成静默。"""
        if not self.enabled:
            return False
        return self.pending_session(now) is not None

    def _open_session(
        self,
        seed: CommitmentSeed,
        now: datetime,
    ) -> ClarificationSession:
        session = ClarificationSession(
            session_id=uuid.uuid4().hex[:12],
            seed=seed,
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
            expires_at=(
                now + timedelta(hours=self.clarify_expiry_hours)
            ).isoformat(timespec="seconds"),
            status="collecting",
        )
        self.clarify_store.save(session)
        return session

    def _next_slot(self, session: ClarificationSession) -> str:
        """优先问还没问过的缺失项，避免盯着同一个问题连问。"""
        slots = self._next_slots(session)
        return slots[0] if slots else ""

    def _next_slots(
        self,
        session: ClarificationSession,
    ) -> list[str]:
        """返回这一轮要问的槽位（最多 max_questions 个）。"""
        missing = session.seed.missing_slots()
        if not missing:
            return []
        unasked = [slot for slot in missing if slot not in session.asked_slots]
        ordered = unasked + [slot for slot in missing if slot in session.asked_slots]
        limit = max(1, min(3, int(self.max_questions)))
        return ordered[:limit]

    def _question_turn(
        self,
        session: ClarificationSession,
        *,
        alias: str,
    ) -> CommitmentTurn:
        slots = self._next_slots(session)
        if not slots:
            return CommitmentTurn.nothing()
        for slot in slots:
            if slot not in session.asked_slots:
                session.asked_slots.append(slot)
        session.turns += 1
        self.clarify_store.save(session)
        text = render_question_multi(
            slots=tuple(slots),
            seed=session.seed,
            alias=alias,
            variant_key=f"{session.session_id}:{slots[0]}",
            turn_index=session.turns,
        )
        return CommitmentTurn(
            mode="question",
            goal_kind=GOAL_CLARIFY,
            fallback_text=text,
            scene=SCENE_QUESTION,
            facts={
                "slot": slots[0],
                "slots": list(slots),
                "title": session.seed.title,
                "asked_slots": list(session.asked_slots),
                "known_slots": sorted(session.seed.known_slots()),
            },
            seeds=[session.seed.to_dict()],
        )

    # ------------------------------------------------------------------
    # 一轮处理
    # ------------------------------------------------------------------

    def handle(
        self,
        text: str,
        now: datetime,
        *,
        alias: str = "宝",
    ) -> CommitmentTurn:
        if not self.enabled:
            return CommitmentTurn.nothing()

        cleaned = text.strip()
        if not cleaned:
            return CommitmentTurn.nothing()

        session = self.pending_session(now)

        if session is not None:
            return self._handle_pending(
                session=session,
                text=cleaned,
                now=now,
                alias=alias,
            )

        seed = self.analyzer.detect(cleaned, now)
        if seed is not None:
            if seed.is_complete():
                commitment = self._create_commitment(seed, now)
                return self._confirm_turn(commitment, alias=alias, now=now)
            session = self._open_session(seed, now)
            return self._question_turn(session, alias=alias)

        return self._handle_operations(cleaned, now, alias=alias)

    def _handle_pending(
        self,
        *,
        session: ClarificationSession,
        text: str,
        now: datetime,
        alias: str,
    ) -> CommitmentTurn:
        if self.analyzer.wants_cancel(text):
            session.status = "cancelled"
            self.clarify_store.save(session)
            self.clarify_store.clear()
            return CommitmentTurn(
                mode="update",
                goal_kind=GOAL_UPDATE,
                fallback_text="好，那这项先不排了。想弄的时候再说。",
                scene=SCENE_UPDATE,
                facts={"action": "cancel_clarification"},
            )

        has_slots = self.analyzer.looks_like_slot_answer(text, now)
        if not has_slots:
            # 用户岔开话题：先正常聊天，会话保留到过期，不连环追问。
            return CommitmentTurn.nothing()

        session.seed = self.analyzer.apply_slots(session.seed, text, now)
        session.updated_at = now.isoformat(timespec="seconds")

        if session.seed.is_complete():
            commitment = self._create_commitment(session.seed, now)
            session.status = "confirmed"
            self.clarify_store.save(session)
            self.clarify_store.clear()
            return self._confirm_turn(commitment, alias=alias, now=now)

        self.clarify_store.save(session)
        return self._question_turn(session, alias=alias)

    def _confirm_turn(
        self,
        commitment: Commitment,
        *,
        alias: str,
        now: datetime | None = None,
    ) -> CommitmentTurn:
        created = self.materialize(commitment, now=now)
        first_due = commitment.occurrences(limit=1)
        return CommitmentTurn(
            mode="confirm",
            goal_kind=GOAL_CONFIRM,
            fallback_text=render_confirmation(commitment, alias=alias),
            scene=SCENE_CONFIRM,
            facts={
                "title": commitment.title,
                "clock_human": clock_human(commitment.clock),
                "weekdays": list(commitment.weekdays),
                "total_weeks": commitment.total_weeks,
                "starts_on": commitment.starts_on,
                "start_human": date_human(commitment.starts_on),
                "soft_weekend": commitment.soft_weekend,
                "first_due": first_due[0]["date"] if first_due else "",
                "materialized": len(created),
            },
            commitment=commitment,
        )

    # ------------------------------------------------------------------
    # 创建与物化
    # ------------------------------------------------------------------

    def _create_commitment(
        self,
        seed: CommitmentSeed,
        now: datetime,
    ) -> Commitment:
        weekdays = seed.weekdays or (5, 6)
        clock = seed.clock or self.default_clock
        weeks = seed.weeks if seed.weeks > 0 else 8
        weeks = min(weeks, self.max_weeks)
        starts_on = resolve_start_date(
            seed.starts_on or "this_week",
            weekdays=weekdays,
            clock=clock,
            now=now,
        )
        commitment = Commitment(
            commitment_id=uuid.uuid4().hex[:12],
            title=seed.title or "那件事",
            clock=clock,
            weekdays=tuple(weekdays),
            total_weeks=weeks,
            starts_on=starts_on.isoformat(),
            created_at=now.isoformat(timespec="seconds"),
            source_text=seed.source_text,
            status="active",
            soft_weekend=bool(seed.soft_weekend and self.soft_weekend),
            metadata={"created_from": seed.source_text},
        )
        self.store.create(commitment)
        return commitment

    def materialize(
        self,
        commitment: Commitment,
        *,
        now: datetime | None = None,
        horizon: int | None = None,
    ) -> list[str]:
        """把接下来几周的 occurrence 写成普通 ScheduledPlan。

        使用 PlanManager 现有能力，不改动 `mark_triggered` 的推进逻辑：
        每次到期只会完成一条一次性计划，再由本服务补下一条。
        """
        limit = horizon or self.horizon
        created: list[str] = []
        existing = {
            str(plan.metadata.get("occurrence_key", ""))
            for plan in self.plan_manager.list_plans(active_only=True)
            if plan.metadata.get("kind") == PLAN_KIND
        }

        for item in commitment.occurrences(limit=limit):
            key = (
                f"{item['commitment_id']}:{item['week_index']}:{item['date']}"
            )
            if key in existing:
                continue
            due_at = self._due_at(
                str(item["date"]),
                commitment.clock,
                reference=now,
            )
            if due_at is None:
                continue
            plan = self.plan_manager.create(
                title=commitment.title,
                details=(
                    f"{commitment.title}第 {item['week_index']}/"
                    f"{commitment.total_weeks} 周"
                ),
                due_at=due_at,
                importance=88,
                recurrence="none",
                source_text=commitment.source_text,
                metadata={
                    "kind": PLAN_KIND,
                    "occurrence_key": key,
                    "commitment_id": commitment.commitment_id,
                    "week_index": item["week_index"],
                    "total_weeks": commitment.total_weeks,
                    "occurrence_date": item["date"],
                    "is_primary": item["is_primary"],
                    "soft": item["soft"],
                },
            )
            created.append(plan.plan_id)
        return created

    def _due_at(
        self,
        date_text: str,
        clock: str,
        *,
        reference: datetime | None,
    ) -> str | None:
        try:
            day = date.fromisoformat(date_text)
            hour, minute = (int(part) for part in clock.split(":", 1))
        except (ValueError, TypeError):
            return None
        base = reference or datetime.now()
        tz = base.tzinfo
        moment = datetime(
            day.year,
            day.month,
            day.day,
            hour,
            minute,
            tzinfo=tz,
        )
        return moment.isoformat(timespec="seconds")

    def sync_schedule(
        self,
        now: datetime,
    ) -> list[str]:
        """每次调度轮询前补齐接下来的 occurrence，代价很低。"""
        created: list[str] = []
        for commitment in self.store.active():
            created.extend(
                self.materialize(commitment, now=now)
            )
        return created

    # ------------------------------------------------------------------
    # 承诺状态操作
    # ------------------------------------------------------------------

    def _handle_operations(
        self,
        text: str,
        now: datetime,
        *,
        alias: str,
    ) -> CommitmentTurn:
        active = self.store.active()
        if not active:
            return CommitmentTurn.nothing()

        if self.analyzer.wants_cancel(text):
            target = self.store.find_by_hint(text)
            if target is None:
                return CommitmentTurn.nothing()
            self._cancel_pending_plans(target)
            cancelled = self.store.cancel(target.commitment_id, now)
            if cancelled is None:
                return CommitmentTurn.nothing()
            return CommitmentTurn(
                mode="update",
                goal_kind=GOAL_UPDATE,
                fallback_text=render_cancel_ack(cancelled, alias=alias),
                scene=SCENE_UPDATE,
                facts={"action": "cancel", "title": cancelled.title},
            )

        if self.analyzer.wants_finish(text):
            target = self._match_current(now)
            if target is None:
                return CommitmentTurn.nothing()
            return self._mark_done(target, now, alias=alias)

        if self.analyzer.wants_skip(text):
            target = self._match_current(now)
            if target is None:
                return CommitmentTurn.nothing()
            week = target.current_week()
            self.store.mark_week(target.commitment_id, week, skipped=True)
            self._cancel_plans_for_week(target, week)
            refreshed = self.store.get(target.commitment_id) or target
            self.materialize(refreshed, now=now)
            return CommitmentTurn(
                mode="update",
                goal_kind=GOAL_UPDATE,
                fallback_text=render_skip_ack(refreshed, week_index=week, alias=alias),
                scene=SCENE_UPDATE,
                facts={
                    "action": "skip",
                    "title": refreshed.title,
                    "week_index": week,
                    "remaining": refreshed.remaining_weeks(),
                },
            )

        if self.analyzer.wants_edit(text):
            target = self.store.find_by_hint(text)
            if target is None:
                return CommitmentTurn.nothing()
            slots = self.analyzer.extract_slots(text, now)
            changed = False
            clock = str(slots.get(SLOT_CLOCK, "") or "")
            if clock:
                target.clock = clock
                changed = True
            if SLOT_WEEKDAYS in slots:
                weekdays = tuple(slots[SLOT_WEEKDAYS])  # type: ignore[arg-type]
                if weekdays:
                    target.weekdays = weekdays
                    target.soft_weekend = bool(
                        slots.get("soft_weekend", False) and self.soft_weekend
                    )
                    changed = True
            weeks = int(slots.get(SLOT_WEEKS, 0) or 0)
            if weeks > 0:
                target.total_weeks = min(max(weeks, 1), self.max_weeks)
                changed = True
            if not changed:
                return CommitmentTurn.nothing()
            target.starts_on = resolve_start_date(
                "this_week",
                weekdays=target.weekdays,
                clock=target.clock,
                now=now,
            ).isoformat()
            self.store.save(target)
            self._cancel_pending_plans(target)
            self.materialize(target, now=now)
            return CommitmentTurn(
                mode="update",
                goal_kind=GOAL_UPDATE,
                fallback_text=render_edit_ack(target, alias=alias),
                scene=SCENE_UPDATE,
                facts={
                    "action": "edit",
                    "title": target.title,
                    "clock_human": clock_human(target.clock),
                    "weekdays": list(target.weekdays),
                    "total_weeks": target.total_weeks,
                },
            )

        return CommitmentTurn.nothing()

    def _mark_done(
        self,
        commitment: Commitment,
        now: datetime,
        *,
        alias: str,
    ) -> CommitmentTurn:
        week = commitment.current_week()
        self.store.mark_week(commitment.commitment_id, week, skipped=False)
        self._cancel_plans_for_week(commitment, week)
        refreshed = self.store.get(commitment.commitment_id) or commitment

        if refreshed.remaining_weeks() <= 0:
            finished = self.store.finish(refreshed.commitment_id, now) or refreshed
            self._cancel_pending_plans(finished)
            return CommitmentTurn(
                mode="status",
                goal_kind=GOAL_FINISH,
                fallback_text=render_finish(finished, alias=alias),
                scene=SCENE_FINISH,
                facts={
                    "title": finished.title,
                    "total_weeks": finished.total_weeks,
                    "done": True,
                },
                commitment=finished,
            )

        self.materialize(refreshed, now=now)
        return CommitmentTurn(
            mode="status",
            goal_kind=GOAL_STATUS,
            fallback_text=render_week_done(refreshed, week_index=week, alias=alias),
            scene=SCENE_UPDATE,
            facts={
                "action": "week_done",
                "title": refreshed.title,
                "week_index": week,
                "total_weeks": refreshed.total_weeks,
                "remaining": refreshed.remaining_weeks(),
            },
            commitment=refreshed,
        )

    def _match_current(self, now: datetime) -> Commitment | None:
        """完成/跳过默认指向"当前正在进行的那一项"。"""
        active = self.store.active()
        if not active:
            return None
        today = now.date()

        def distance(item: Commitment) -> tuple[int, int]:
            week = item.current_week()
            first = item.week_date(week)
            span = [
                first + timedelta(days=offset)
                for offset in range(0, 7)
            ]
            if today in span:
                return (0, week)
            return (abs((today - first).days), week)

        return sorted(active, key=distance)[0]

    # ------------------------------------------------------------------
    # 计划清理
    # ------------------------------------------------------------------

    def _cancel_pending_plans(self, commitment: Commitment) -> None:
        for plan in self.plan_manager.list_plans(active_only=True):
            if plan.metadata.get("commitment_id") != commitment.commitment_id:
                continue
            self.plan_manager.cancel(plan.plan_id)

    def _cancel_plans_for_week(self, commitment: Commitment, week: int) -> None:
        for plan in self.plan_manager.list_plans(active_only=True):
            if plan.metadata.get("commitment_id") != commitment.commitment_id:
                continue
            if int(plan.metadata.get("week_index", 0) or 0) != week:
                continue
            self.plan_manager.cancel(plan.plan_id)

    # ------------------------------------------------------------------
    # 供调度器与快照使用
    # ------------------------------------------------------------------

    def plan_wording(
        self,
        plan_metadata: dict[str, object],
        *,
        title: str,
        alias: str = "宝",
    ) -> str:
        commitment = self.store.get(
            str(plan_metadata.get("commitment_id", ""))
        )
        week_index = int(plan_metadata.get("week_index", 1) or 1)
        if commitment is None:
            return render_occurrence_start(
                Commitment(
                    commitment_id="",
                    title=title,
                    clock=self.default_clock,
                    weekdays=(5, 6),
                    total_weeks=max(1, int(plan_metadata.get("total_weeks", 1) or 1)),
                    starts_on="",
                    created_at="",
                ),
                week_index=week_index,
                alias=alias,
            )
        is_primary = bool(plan_metadata.get("is_primary", True))
        soft = bool(plan_metadata.get("soft", False))
        if soft and not is_primary:
            from .language import render_soft_nudge

            return render_soft_nudge(
                commitment,
                week_index=week_index,
                alias=alias,
            )
        return render_occurrence_start(
            commitment,
            week_index=week_index,
            is_primary=is_primary,
            alias=alias,
        )

    def snapshot(self) -> dict[str, object]:
        session = self.clarify_store.get()
        return {
            "enabled": self.enabled,
            "commitments": self.store.snapshot(),
            "clarification": session.to_dict() if session is not None else None,
        }

    def describe_current(self, alias: str = "宝") -> str:
        active = self.store.active()
        if not active:
            return "现在没有正在进行的长期安排。"
        if len(active) == 1:
            return render_progress(active[0], alias=alias)
        return "；".join(
            f"{item.title} 第 {item.current_week()}/{item.total_weeks} 周"
            for item in active[:3]
        )
