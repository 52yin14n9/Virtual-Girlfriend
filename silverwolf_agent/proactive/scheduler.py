from __future__ import annotations

import asyncio
from datetime import (
    datetime,
    timedelta,
)
from typing import Callable

from .executor import (
    ProactiveExecutor,
)
from .plan_manager import PlanManager
from .planner import ProactivePlanner
from .state import ProactiveStateStore
from .time_manager import TimeManager
from ..delivery import (
    MessageDispatcher,
    MessageSink,
    ReplyBundle,
)
from ..memory.short_term import (
    ShortTermMemory,
)


class AsyncProactiveScheduler:
    def __init__(
        self,
        *,
        time_manager: TimeManager,
        plan_manager: PlanManager,
        state: ProactiveStateStore,
        planner: ProactivePlanner,
        executor: ProactiveExecutor,
        memory: ShortTermMemory,
        dispatcher: MessageDispatcher,
        now_provider: Callable[
            [],
            datetime,
        ],
        poll_seconds: float = 30.0,
        follow_up_enabled: bool = False,
        follow_up_seconds: int = 900,
        follow_up_expiry_seconds: int = 3600,
        commitment_service: object | None = None,
    ) -> None:
        self.time_manager = (
            time_manager
        )
        self.plan_manager = (
            plan_manager
        )
        self.state = state
        self.planner = planner
        self.executor = executor
        self.memory = memory
        self.dispatcher = dispatcher
        self.now_provider = now_provider
        self.commitment_service = commitment_service
        self.poll_seconds = max(
            1.0,
            poll_seconds,
        )

        self.follow_up_enabled = bool(
            follow_up_enabled
        )
        self.follow_up_seconds = max(
            10,
            int(
                follow_up_seconds
            ),
        )
        self.follow_up_expiry_seconds = max(
            self.follow_up_seconds,
            int(
                follow_up_expiry_seconds
            ),
        )

        self._task: (
            asyncio.Task[None]
            | None
        ) = None
        self._stop_event = (
            asyncio.Event()
        )
        self._run_lock = (
            asyncio.Lock()
        )
        self._sink: (
            MessageSink
            | None
        ) = None

        self.last_plan_json = ""
        self.last_execution_json = ""
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return (
            self._task is not None
            and not self._task.done()
        )

    def note_user_activity(
        self,
        at: datetime,
    ) -> bool:
        """
        用户一发言就先取消等待中的追问。

        这个方法必须在 run_once 之前调用，避免用户恰好在
        追问临界点回复时，追问与用户消息同时发送。
        """
        return self.state.note_user_activity(
            at
        )

    async def start(
        self,
        sink: MessageSink,
    ) -> None:
        if self.running:
            return

        self._sink = sink
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_forever(),
            name=(
                "silverwolf-proactive-"
                "scheduler"
            ),
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(
        self,
        *,
        sink: MessageSink | None = None,
        now: datetime | None = None,
    ) -> ReplyBundle | None:
        async with self._run_lock:
            return await (
                self._run_once_unlocked(
                    sink=sink,
                    now=now,
                )
            )

    async def _run_once_unlocked(
        self,
        *,
        sink: MessageSink | None = None,
        now: datetime | None = None,
    ) -> ReplyBundle | None:
        target_sink = (
            sink
            or self._sink
        )
        if target_sink is None:
            raise RuntimeError(
                "Scheduler 没有 MessageSink"
            )

        current = (
            now
            or self.now_provider()
        )
        current = current.astimezone(
            self.time_manager.timezone()
        )

        # Delivery circuit breaker: when the outbound channel is down, do not
        # retry the same proactive content on every scheduler poll. Two bounded
        # backoff retries are allowed; a third failure suspends proactive sends
        # until user activity proves the channel is alive again.
        if not self.state.proactive_delivery_allowed(current):
            self.state.set_last_run(
                current.isoformat(timespec="seconds")
            )
            return None

        # Lv27: 把长期承诺接下来的 occurrence 物化成普通计划。
        # 到期检查仍然只有 PlanManager 一条路径，不新增第二套定时器。
        if self.commitment_service is not None:
            try:
                self.commitment_service.sync_schedule(current)
            except Exception as exc:  # noqa: BLE001 - 调度不能因此中断
                self.last_error = f"commitment schedule sync failed: {exc}"

        if not self.follow_up_enabled:
            self.state.clear_follow_up(
                reason="disabled",
                at=current,
            )
            pending_follow_up = None
        else:
            pending_follow_up = (
                self.state.due_follow_up(
                    current
                )
            )

        routines = (
            self.time_manager
            .due_routines(
                current,
                self.state,
            )
        )
        due_plans = (
            self.plan_manager.due(
                current
            )
        )

        # 关系型 event follow-up 是“顺手关心”，不是正式提醒。
        # 进入睡眠静默时段或已经明显过期时直接作废，避免凌晨补发
        # “事情结束了吗”之类消息。正式闹钟/提醒不经过这条过滤。
        filtered_due_plans = []
        for scheduled_plan in due_plans:
            if scheduled_plan.metadata.get("kind") != "relationship_event_follow_up":
                filtered_due_plans.append(scheduled_plan)
                continue
            due_at = datetime.fromisoformat(scheduled_plan.due_at)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=current.tzinfo)
            due_at = due_at.astimezone(current.tzinfo)
            max_lateness_minutes = int(
                scheduled_plan.metadata.get("max_lateness_minutes", 90) or 90
            )
            too_late = current > due_at + timedelta(minutes=max(15, max_lateness_minutes))
            in_quiet_time = self.time_manager.is_quiet_time(current)
            if in_quiet_time or too_late:
                self.plan_manager.expire_relationship_followup(
                    scheduled_plan.plan_id,
                    current,
                    reason=("quiet_hours" if in_quiet_time else "stale_follow_up"),
                )
                continue
            filtered_due_plans.append(scheduled_plan)
        due_plans = filtered_due_plans

        plan_json = (
            self.planner.plan_json(
                now=current,
                routines=routines,
                due_plans=due_plans,
                follow_up=(
                    pending_follow_up
                ),
            )
        )
        self.last_plan_json = plan_json

        bundle, execution_json = (
            self.executor.execute_json(
                plan_json
            )
        )
        self.last_execution_json = (
            execution_json
        )

        # 用户可能在 Planner 生成追问期间刚好回复。
        # 真正投递前再次核对 pending token，若已取消，
        # 就从本轮 bundle 中移除追问。
        if pending_follow_up is not None:
            pending_id = str(
                pending_follow_up.get(
                    "original_message_id",
                    "",
                )
            )
            if not self.state.is_follow_up_pending(
                pending_id
            ):
                bundle.messages = [
                    message
                    for message
                    in bundle.messages
                    if not bool(
                        message.metadata.get(
                            "is_follow_up"
                        )
                    )
                ]

        selected = (
            bundle.selected_messages()
        )
        if not selected:
            # 这一时段可能因为静默模式或自适应降频被有意跳过。
            # 将例行时段标记为已评估，避免每个轮询周期重复规划。
            for event in routines:
                self.state.mark_routine_sent(
                    event.key,
                    current.date().isoformat(),
                )
            self.state.set_last_run(
                current.isoformat(
                    timespec="seconds"
                )
            )
            return None

        try:
            await self.dispatcher.dispatch(
                bundle,
                target_sink,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            guard = self.state.record_proactive_delivery_failure(
                at=current,
                error=str(exc),
                max_failures=3,
            )
            self.last_error = (
                "proactive delivery failed; "
                f"attempt={guard.get('failure_count', 0)}; "
                f"suspended={guard.get('suspended', False)}; "
                f"error={exc}"
            )
            self.state.set_last_run(
                current.isoformat(timespec="seconds")
            )
            return None

        self.state.reset_proactive_delivery_guard(reason="delivery_success")
        self.last_error = None

        # 只记录真正投递给用户的模板，避免被权重过滤掉的
        # 候选污染去重历史。
        for message in selected:
            template_id = str(
                message.metadata.get(
                    "template_id",
                    "",
                )
            )
            template_group = str(
                message.metadata.get(
                    "template_group",
                    "",
                )
            )
            if (
                template_id
                and template_group
            ):
                self.state.record_template_use(
                    template_id=(
                        template_id
                    ),
                    template_group=(
                        template_group
                    ),
                    content=(
                        message.content
                    ),
                    sent_at=current,
                    category=(
                        message.category
                    ),
                    semantic_tags=(
                        message.metadata.get(
                            "semantic_tags",
                            [],
                        )
                    ),
                    # Lv31: 记录这句是语料生成还是确定性兜底
                    source=str(
                        message.metadata.get(
                            "speech_source",
                            "",
                        )
                        or ""
                    ),
                )

        for message in selected:
            if bool(
                message.metadata.get(
                    "weather_context_included"
                )
            ):
                self.state.mark_weather_sent(
                    current.date().isoformat()
                )
            if message.metadata.get("memory_callback"):
                self.state.mark_memory_callback_sent(
                    current.date().isoformat()
                )
            if message.metadata.get("weekend_suggestion"):
                self.state.mark_weekend_suggestion_sent(
                    current.date().isoformat()
                )
            if (
                message.category.startswith("routine_")
                or message.category
                == "relationship_event_follow_up"
            ):
                self.state.record_relationship_sent(
                    sent_at=current,
                    expects_reply=bool(
                        message.metadata.get(
                            "expects_reply",
                            False,
                        )
                    ),
                )

        follow_up_sent = any(
            bool(
                message.metadata.get(
                    "is_follow_up"
                )
            )
            for message in selected
        )
        if follow_up_sent:
            self.state.mark_follow_up_sent(
                sent_at=current
            )

        selected_routine_keys = {
            str(message.metadata.get("routine_key", ""))
            for message in selected
            if message.category.startswith("routine_")
        }
        for event in routines:
            if event.key in selected_routine_keys:
                self.state.mark_routine_sent(
                    event.key,
                    current.date().isoformat(),
                )

        selected_plan_ids = {
            str(message.metadata.get("plan_id", ""))
            for message in selected
            if message.metadata.get("plan_id")
        }
        for plan in due_plans:
            if plan.plan_id in selected_plan_ids:
                self.plan_manager.mark_triggered(
                    plan.plan_id,
                    current,
                )

        # 一条关系型主动消息只允许追加一次追问。
        # 若本轮已经在发送追问，则不再为同一轮继续套娃。
        if (
            self.follow_up_enabled
            and not follow_up_sent
        ):
            candidate = next(
                (
                    message
                    for message
                    in reversed(selected)
                    if (
                        message.source
                        == "proactive"
                        and bool(
                            message.metadata.get(
                                "expects_reply"
                            )
                        )
                        and not bool(
                            message.metadata.get(
                                "is_follow_up"
                            )
                        )
                        and not bool(
                            message.metadata.get(
                                "no_secondary_follow_up"
                            )
                        )
                    )
                ),
                None,
            )
            if candidate is not None:
                self.state.arm_follow_up(
                    sent_at=current,
                    due_at=(
                        current
                        + timedelta(
                            seconds=(
                                self.follow_up_seconds
                            )
                        )
                    ),
                    expires_at=(
                        current
                        + timedelta(
                            seconds=(
                                self.follow_up_expiry_seconds
                            )
                        )
                    ),
                    routine_key=str(
                        candidate.metadata.get(
                            "routine_key",
                            "",
                        )
                    ),
                    original_content=(
                        candidate.content
                    ),
                    original_message_id=(
                        candidate.message_id
                    ),
                )

        self.memory.add_proactive_message(
            "\n".join(message.content for message in selected),
            at=current,
        )
        self.state.set_last_run(
            current.isoformat(
                timespec="seconds"
            )
        )
        return bundle

    async def _run_forever(
        self,
    ) -> None:
        while not (
            self._stop_event.is_set()
        ):
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=(
                        self.poll_seconds
                    ),
                )
            except asyncio.TimeoutError:
                pass
