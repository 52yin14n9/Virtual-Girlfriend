from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.delivery import (
    CollectingMessageSink,
    MessageDispatcher,
    OutboundMessage,
)
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager
from silverwolf_agent.proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    TimeManager,
)
from silverwolf_agent.proactive.contracts import ScheduledPlan


ZONE = ZoneInfo("Asia/Shanghai")


def build_profile(root: Path) -> UserProfileManager:
    default_profile = root / "default_user_profile.json"
    shutil.copy2(PROJECT_ROOT / "config" / "default_user_profile.json", default_profile)
    return UserProfileManager(
        path=root / "user_profile.json",
        default_path=default_profile,
    )


def build_scheduler(root: Path) -> tuple[AsyncProactiveScheduler, PlanManager, CollectingMessageSink]:
    profile = build_profile(root)
    memory = ShortTermMemory(path=root / "short_term.json")
    manager = PlanManager(path=root / "plans.json")
    time_manager = TimeManager(path=root / "time_preferences.json", timezone="Asia/Shanghai")
    state = ProactiveStateStore(path=root / "proactive_state.json")
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        message_gap_seconds=0.0,
        state=state,
    )
    sink = CollectingMessageSink()
    scheduler = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=manager,
        state=state,
        planner=planner,
        executor=ProactiveExecutor(),
        memory=memory,
        dispatcher=MessageDispatcher(default_gap_seconds=0.0),
        now_provider=lambda: datetime.now(ZONE),
        poll_seconds=30,
        follow_up_enabled=True,
        follow_up_seconds=120,
        follow_up_expiry_seconds=900,
    )
    return scheduler, manager, sink


def test_bedtime_due_message_is_human() -> None:
    now = datetime(2026, 8, 7, 23, 30, tzinfo=ZONE)
    plan = ScheduledPlan.create(
        title="提醒睡觉",
        details="",
        due_at=now.isoformat(timespec="seconds"),
        importance=90,
        recurrence="daily",
    )
    content = ProactivePlanner._plan_content(
        plan=plan,
        now=now,
        casual_alias="宝",
    )
    assert content == "宝，该睡觉啦"
    assert "提醒" not in content
    assert not content.endswith("。")


def test_user_arrival_resolves_trip_followup(root: Path) -> None:
    manager = PlanManager(path=root / "plans.json")
    due = datetime(2026, 8, 8, 1, 3, tzinfo=ZONE)
    plan = manager.create(
        title="问问行程怎么样",
        details="",
        due_at=due.isoformat(timespec="seconds"),
        importance=74,
        metadata={
            "kind": "relationship_event_follow_up",
            "event_label": "行程",
            "expects_reply": True,
            "no_secondary_follow_up": True,
        },
    )
    resolved = manager.resolve_relationship_followups(
        "我到咯",
        datetime(2026, 8, 7, 21, 21, tzinfo=ZONE),
    )
    assert resolved == [plan.plan_id]
    saved = next(item for item in manager.list_plans() if item.plan_id == plan.plan_id)
    assert saved.status == "completed"
    assert saved.metadata["resolved_by_user"] is True
    assert manager.due(due) == []


async def quiet_followup_case(root: Path) -> None:
    scheduler, manager, sink = build_scheduler(root)
    due = datetime(2026, 8, 8, 1, 3, tzinfo=ZONE)
    plan = manager.create(
        title="问问行程怎么样",
        details="",
        due_at=due.isoformat(timespec="seconds"),
        importance=74,
        metadata={
            "kind": "relationship_event_follow_up",
            "event_label": "行程",
            "expects_reply": True,
            "no_secondary_follow_up": True,
            "no_late_delivery": True,
            "max_lateness_minutes": 90,
        },
    )
    bundle = await scheduler.run_once(sink=sink, now=due)
    assert bundle is None
    assert sink.messages == []
    saved = next(item for item in manager.list_plans() if item.plan_id == plan.plan_id)
    assert saved.status == "cancelled"
    assert saved.metadata["expiry_reason"] == "quiet_hours"


async def formal_bedtime_still_fires_in_quiet_hours(root: Path) -> None:
    scheduler, manager, sink = build_scheduler(root)
    due = datetime(2026, 8, 7, 23, 30, tzinfo=ZONE)
    plan = manager.create(
        title="提醒睡觉",
        details="",
        due_at=due.isoformat(timespec="seconds"),
        importance=90,
        recurrence="daily",
        source_text="以后你11点半叫我睡觉",
    )
    bundle = await scheduler.run_once(sink=sink, now=due)
    assert bundle is not None
    assert [m.content for m in sink.messages] == ["宝，该睡觉啦"]
    saved = next(item for item in manager.list_plans(active_only=True) if item.plan_id == plan.plan_id)
    assert datetime.fromisoformat(saved.due_at).date() == (due + timedelta(days=1)).date()


def test_terminal_period_is_removed_only_at_message_end() -> None:
    one = OutboundMessage(
        content="今天天气挺不错的。",
        weight=80,
        category="conversation",
        source="interactive",
    )
    assert one.content == "今天天气挺不错的"

    multi = OutboundMessage(
        content="到啦，那就好。洗漱完就可以放松一下了。",
        weight=80,
        category="conversation",
        source="interactive",
    )
    assert multi.content == "到啦，那就好。洗漱完就可以放松一下了"

    question = OutboundMessage(
        content="今天感觉怎么样？",
        weight=80,
        category="conversation",
        source="interactive",
    )
    assert question.content == "今天感觉怎么样？"


def run() -> None:
    test_bedtime_due_message_is_human()
    with tempfile.TemporaryDirectory() as value:
        test_user_arrival_resolves_trip_followup(Path(value))
    with tempfile.TemporaryDirectory() as value:
        asyncio.run(quiet_followup_case(Path(value)))
    with tempfile.TemporaryDirectory() as value:
        asyncio.run(formal_bedtime_still_fires_in_quiet_hours(Path(value)))
    test_terminal_period_is_removed_only_at_message_end()
    print("lv22_reminder_followup_punctuation_test: OK")


if __name__ == "__main__":
    run()
