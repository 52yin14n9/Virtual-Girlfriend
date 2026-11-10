from __future__ import annotations

import asyncio
from datetime import (
    datetime,
    timedelta,
)
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from silverwolf_agent.agent import (
    SilverWolfAgent,
)
from silverwolf_agent.delivery import (
    CollectingMessageSink,
    MessageDispatcher,
    OutboundMessage,
    ReplyBundle,
)
from silverwolf_agent.memory import (
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    TimeManager,
)


ZONE = ZoneInfo("Asia/Shanghai")


def make_profile(
    root: Path,
) -> UserProfileManager:
    default_path = root / "default.json"
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 13,
                "stable": {
                    "birthday": "2000-01-01",
                },
                "dynamic": {
                    "preferred_name": "星",
                    "casual_aliases": ["宝"],
                    "address_style": {
                        "default": "星",
                        "casual": "宝",
                    },
                },
                "metadata": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return UserProfileManager(
        path=root / "profile.json",
        default_path=default_path,
    )


def make_scheduler(
    root: Path,
    *,
    now_provider,
    follow_up_seconds: int = 120,
    expiry_seconds: int = 900,
):
    profile = make_profile(root)
    memory = ShortTermMemory(
        path=root / "memory.json",
        max_recent_turns=30,
    )
    time_manager = TimeManager(
        path=root / "time.json",
        timezone="Asia/Shanghai",
    )
    time_manager.set_slot(
        "morning",
        "08:00",
        enabled=False,
    )
    time_manager.set_slot(
        "noon",
        "12:00",
        enabled=False,
    )
    time_manager.set_slot(
        "evening",
        "19:00",
        enabled=True,
        window_minutes=30,
    )
    plan_manager = PlanManager(
        path=root / "plans.json"
    )
    state = ProactiveStateStore(
        path=root / "state.json"
    )
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        message_gap_seconds=0.0,
    )
    scheduler = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=plan_manager,
        state=state,
        planner=planner,
        executor=ProactiveExecutor(),
        memory=memory,
        dispatcher=MessageDispatcher(
            default_gap_seconds=0.0,
        ),
        now_provider=now_provider,
        poll_seconds=1.0,
        follow_up_enabled=True,
        follow_up_seconds=(
            follow_up_seconds
        ),
        follow_up_expiry_seconds=(
            expiry_seconds
        ),
    )
    return (
        profile,
        memory,
        time_manager,
        plan_manager,
        state,
        planner,
        scheduler,
    )


async def no_reply_follow_up_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    current = {
        "value": start
    }
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        state,
        _planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: (
            current["value"]
        ),
    )
    sink = CollectingMessageSink()

    first = await scheduler.run_once(
        sink=sink,
        now=start,
    )
    assert first is not None
    assert sink.messages
    assert (
        sink.messages[-1].category
        == "routine_evening"
    )
    assert (
        sink.messages[-1].metadata[
            "template_group"
        ]
        in {
            "evening_unfed",
            "evening_busy",
            "evening_tired",
        }
    )
    assert bool(
        sink.messages[-1].metadata[
            "expects_reply"
        ]
    )

    snapshot = state.snapshot()
    pending = snapshot[
        "pending_follow_up"
    ]
    assert pending is not None
    assert pending[
        "routine_key"
    ] == "evening"
    assert (
        datetime.fromisoformat(
            pending["due_at"]
        )
        == start
        + timedelta(minutes=2)
    )

    before_count = len(
        sink.messages
    )
    not_yet = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=119
            )
        ),
    )
    assert not_yet is None
    assert len(
        sink.messages
    ) == before_count

    follow_up = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=121
            )
        ),
    )
    assert follow_up is not None
    assert len(
        sink.messages
    ) == before_count + 1
    assert (
        sink.messages[-1].category
        == "relationship_follow_up"
    )
    assert (
        sink.messages[-1].metadata[
            "template_group"
        ]
        == "follow_up_evening"
    )
    assert len(
        sink.messages[-1].content
    ) >= 12

    after = state.snapshot()
    assert (
        after["pending_follow_up"]
        is None
    )
    assert (
        after["last_follow_up"][
            "status"
        ]
        == "sent"
    )

    # A single proactive message only gets one follow-up.
    count_after = len(
        sink.messages
    )
    third = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=180
            )
        ),
    )
    assert third is None
    assert len(
        sink.messages
    ) == count_after


async def prompt_reply_cancels_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        state,
        _planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
    )
    sink = CollectingMessageSink()

    await scheduler.run_once(
        sink=sink,
        now=start,
    )
    assert (
        state.snapshot()[
            "pending_follow_up"
        ]
        is not None
    )

    # Mirrors the user's example: reply two seconds later.
    cancelled = (
        scheduler.note_user_activity(
            start
            + timedelta(seconds=2)
        )
    )
    assert cancelled
    assert (
        state.snapshot()[
            "pending_follow_up"
        ]
        is None
    )

    count = len(sink.messages)
    result = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=121
            )
        ),
    )
    assert result is None
    assert len(sink.messages) == count
    assert (
        state.snapshot()[
            "last_follow_up"
        ]["status"]
        == "cancelled_by_user_reply"
    )


async def exact_boundary_reply_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        state,
        _planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
    )
    sink = CollectingMessageSink()

    await scheduler.run_once(
        sink=sink,
        now=start,
    )

    boundary = (
        start
        + timedelta(minutes=2)
    )

    # The agent calls this before scheduler.run_once.
    scheduler.note_user_activity(
        boundary
    )
    result = await scheduler.run_once(
        sink=sink,
        now=boundary,
    )

    assert result is None
    assert len(sink.messages) == 1
    assert (
        state.snapshot()[
            "last_follow_up"
        ]["status"]
        == "cancelled_by_user_reply"
    )


async def expiry_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        state,
        _planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
        follow_up_seconds=120,
        expiry_seconds=300,
    )
    sink = CollectingMessageSink()

    await scheduler.run_once(
        sink=sink,
        now=start,
    )
    count = len(sink.messages)

    result = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=301
            )
        ),
    )
    assert result is None
    assert len(sink.messages) == count
    assert (
        state.snapshot()[
            "last_follow_up"
        ]["status"]
        == "expired"
    )


async def restart_persistence_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    (
        profile,
        memory,
        time_manager,
        plan_manager,
        state,
        planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
    )
    sink = CollectingMessageSink()

    await scheduler.run_once(
        sink=sink,
        now=start,
    )
    assert (
        state.snapshot()[
            "pending_follow_up"
        ]
        is not None
    )

    # Simulate process restart by reopening the same state file.
    reloaded_state = ProactiveStateStore(
        path=root / "state.json"
    )
    restarted = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=plan_manager,
        state=reloaded_state,
        planner=planner,
        executor=ProactiveExecutor(),
        memory=memory,
        dispatcher=MessageDispatcher(
            default_gap_seconds=0.0,
        ),
        now_provider=lambda: (
            start
            + timedelta(
                seconds=121
            )
        ),
        poll_seconds=1.0,
        follow_up_enabled=True,
        follow_up_seconds=120,
        follow_up_expiry_seconds=900,
    )

    result = await restarted.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=121
            )
        ),
    )
    assert result is not None
    assert (
        sink.messages[-1].metadata[
            "template_group"
        ]
        == "follow_up_evening"
    )


async def cancellation_during_planning_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        state,
        planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
    )
    sink = CollectingMessageSink()

    await scheduler.run_once(
        sink=sink,
        now=start,
    )
    count = len(sink.messages)

    original_plan_json = (
        planner.plan_json
    )

    def cancelling_plan_json(
        *,
        now,
        routines,
        due_plans,
        follow_up=None,
    ):
        # Simulate a user reply arriving after the scheduler
        # has read the pending follow-up but before dispatch.
        if follow_up is not None:
            state.note_user_activity(
                now
            )
        return original_plan_json(
            now=now,
            routines=routines,
            due_plans=due_plans,
            follow_up=follow_up,
        )

    planner.plan_json = (
        cancelling_plan_json
    )

    result = await scheduler.run_once(
        sink=sink,
        now=(
            start
            + timedelta(
                seconds=121
            )
        ),
    )
    assert result is None
    assert len(sink.messages) == count
    assert (
        state.snapshot()[
            "last_follow_up"
        ]["status"]
        == "cancelled_by_user_reply"
    )


async def agent_orders_reply_before_due_check() -> None:
    order: list[str] = []

    class FakeScheduler:
        def note_user_activity(
            self,
            at,
        ):
            order.append("note_user")
            return True

        async def run_once(
            self,
            *,
            sink,
            now,
        ):
            assert order == [
                "note_user"
            ]
            order.append("run_scheduler")
            return None

    class FakeDispatcher:
        async def dispatch(
            self,
            bundle,
            sink,
        ):
            order.append("dispatch_reply")
            for message in (
                bundle.selected_messages()
            ):
                await sink.send(
                    message
                )

    class FakeAgent:
        scheduler = FakeScheduler()
        dispatcher = FakeDispatcher()

        def chat_bundle(
            self,
            user_input,
            *,
            received_at=None,
        ):
            assert order == [
                "note_user",
                "run_scheduler",
            ]
            order.append("chat")
            return ReplyBundle(
                messages=[
                    OutboundMessage(
                        content="收到。",
                        weight=80,
                        category="conversation",
                        source="interactive",
                    )
                ]
            )

    sink = CollectingMessageSink()
    fake = FakeAgent()
    at = datetime(
        2026,
        8,
        4,
        19,
        4,
        46,
        tzinfo=ZONE,
    )

    await SilverWolfAgent.handle_user_message(
        fake,
        "吃过了呢",
        sink,
        received_at=at,
    )
    assert order == [
        "note_user",
        "run_scheduler",
        "chat",
        "dispatch_reply",
    ]
    assert (
        sink.messages[-1].content
        == "收到"
    )


def arm_after_user_reply_is_suppressed(
    root: Path,
) -> None:
    state = ProactiveStateStore(
        path=root / "state.json"
    )
    sent_at = datetime(
        2026,
        8,
        4,
        19,
        2,
        46,
        tzinfo=ZONE,
    )
    state.note_user_activity(
        sent_at
        + timedelta(seconds=1)
    )
    armed = state.arm_follow_up(
        sent_at=sent_at,
        due_at=(
            sent_at
            + timedelta(minutes=2)
        ),
        expires_at=(
            sent_at
            + timedelta(minutes=15)
        ),
        routine_key="evening",
        original_content=(
            "晚饭吃了吗？"
        ),
        original_message_id="msg-1",
    )
    assert not armed
    snapshot = state.snapshot()
    assert (
        snapshot[
            "pending_follow_up"
        ]
        is None
    )
    assert (
        snapshot[
            "last_follow_up"
        ]["status"]
        == "suppressed_by_user_reply"
    )


async def scheduled_reminder_does_not_nag_case(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        16,
        0,
        0,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        time_manager,
        plan_manager,
        state,
        _planner,
        scheduler,
    ) = make_scheduler(
        root,
        now_provider=lambda: start,
    )
    time_manager.set_proactive_enabled(
        False
    )

    plan_manager.create(
        title="结束休息",
        details="休息一分钟",
        due_at=start.isoformat(
            timespec="seconds"
        ),
        importance=95,
        source_text=(
            "一分钟后叫我"
        ),
    )
    sink = CollectingMessageSink()

    result = await scheduler.run_once(
        sink=sink,
        now=start,
    )
    assert result is not None
    assert any(
        "休息结束" in (
            message.content
        )
        for message in sink.messages
    )
    assert (
        state.snapshot()[
            "pending_follow_up"
        ]
        is None
    )


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            no_reply_follow_up_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            prompt_reply_cancels_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            exact_boundary_reply_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            expiry_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            restart_persistence_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            scheduled_reminder_does_not_nag_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        arm_after_user_reply_is_suppressed(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            cancellation_during_planning_case(
                Path(value)
            )
        )

    asyncio.run(
        agent_orders_reply_before_due_check()
    )

    print(
        "lv13_follow_up_test: OK"
    )


if __name__ == "__main__":
    run()
