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

from silverwolf_agent.delivery import (
    CollectingMessageSink,
    MessageDispatcher,
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
                "schema_version": 14,
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


def make_components(
    root: Path,
):
    profile = make_profile(root)
    memory = ShortTermMemory(
        path=root / "memory.json",
        max_recent_turns=30,
    )
    state = ProactiveStateStore(
        path=root / "state.json"
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
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        state=state,
        message_gap_seconds=0.0,
        template_history_limit=6,
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
        now_provider=lambda: datetime.now(
            ZONE
        ),
        poll_seconds=1.0,
        follow_up_enabled=True,
        follow_up_seconds=120,
        follow_up_expiry_seconds=900,
    )
    return (
        profile,
        memory,
        state,
        time_manager,
        plan_manager,
        planner,
        scheduler,
    )


async def routine_variation_case(
    root: Path,
) -> None:
    (
        _profile,
        _memory,
        state,
        _time_manager,
        _plan_manager,
        _planner,
        scheduler,
    ) = make_components(root)

    sink = CollectingMessageSink()
    contents: list[str] = []
    template_ids: list[str] = []

    start = datetime(
        2026,
        8,
        4,
        19,
        2,
        tzinfo=ZONE,
    )
    for offset in range(8):
        now = start + timedelta(
            days=offset
        )
        bundle = await scheduler.run_once(
            sink=sink,
            now=now,
        )
        assert bundle is not None
        message = (
            bundle.selected_messages()[0]
        )
        contents.append(
            message.content
        )
        template_ids.append(
            str(
                message.metadata[
                    "template_id"
                ]
            )
        )

        # User replies immediately, preventing follow-up state
        # from influencing the next day's variation check.
        scheduler.note_user_activity(
            now
            + timedelta(seconds=1)
        )

    assert all(
        left != right
        for left, right in zip(
            template_ids,
            template_ids[1:],
        )
    )
    assert len(
        set(template_ids)
    ) >= 7
    assert len(
        set(contents)
    ) >= 7

    history = state.snapshot()[
        "proactive_template_history"
    ]
    assert len(history) == 8
    assert all(
        item["template_group"]
        == "evening_unfed"
        for item in history
    )


def context_group_case(
    root: Path,
) -> None:
    (
        _profile,
        memory,
        state,
        _time_manager,
        _plan_manager,
        planner,
        _scheduler,
    ) = make_components(root)
    now = datetime(
        2026,
        8,
        4,
        19,
        2,
        tzinfo=ZONE,
    )

    memory.add_turn(
        "今天一直在开发项目，忙了一天",
        "先休息一下。",
        at=now
        - timedelta(minutes=30),
    )
    plan = json.loads(
        planner.plan_json(
            now=now,
            routines=[
                type(
                    "Routine",
                    (),
                    {
                        "key": "evening",
                        "weight": 72,
                    },
                )()
            ],
            due_plans=[],
        )
    )
    metadata = plan[
        "planned_messages"
    ][0]["metadata"]
    assert metadata[
        "template_group"
    ] == "evening_busy"

    # Explicitly saying dinner was eaten must outrank
    # simultaneous busy/tired context.
    memory.add_turn(
        "我已经吃过晚饭了，不过今天很累",
        "那就歇会儿。",
        at=now
        - timedelta(minutes=5),
    )
    plan = json.loads(
        planner.plan_json(
            now=now,
            routines=[
                type(
                    "Routine",
                    (),
                    {
                        "key": "evening",
                        "weight": 72,
                    },
                )()
            ],
            due_plans=[],
        )
    )
    message = plan[
        "planned_messages"
    ][0]
    assert message[
        "metadata"
    ]["template_group"] == (
        "evening_fed"
    )
    assert "晚饭吃了吗" not in (
        message["content"]
    )


async def follow_up_variation_case(
    root: Path,
) -> None:
    (
        _profile,
        _memory,
        state,
        _time_manager,
        _plan_manager,
        planner,
        _scheduler,
    ) = make_components(root)

    contents: list[str] = []
    ids: list[str] = []
    start = datetime(
        2026,
        8,
        4,
        19,
        4,
        tzinfo=ZONE,
    )

    for offset in range(6):
        now = start + timedelta(
            days=offset
        )
        plan = json.loads(
            planner.plan_json(
                now=now,
                routines=[],
                due_plans=[],
                follow_up={
                    "routine_key": (
                        "evening"
                    ),
                    "original_content": (
                        "晚饭吃了吗？"
                    ),
                    "original_message_id": (
                        f"m-{offset}"
                    ),
                },
            )
        )
        message = plan[
            "planned_messages"
        ][0]
        contents.append(
            message["content"]
        )
        template_id = message[
            "metadata"
        ]["template_id"]
        ids.append(template_id)
        state.record_template_use(
            template_id=template_id,
            template_group=(
                message["metadata"][
                    "template_group"
                ]
            ),
            content=message[
                "content"
            ],
            sent_at=now,
            category=(
                message["category"]
            ),
        )

    assert len(set(ids)) == 6
    assert len(set(contents)) == 6


def review_observability_case() -> None:
    app_source = (
        PROJECT_ROOT
        / "silverwolf_agent"
        / "webapp"
        / "app.py"
    ).read_text(
        encoding="utf-8"
    )
    js_source = (
        PROJECT_ROOT
        / "silverwolf_agent"
        / "webapp"
        / "static"
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/api/debug/proactive"'
        in app_source
    )
    assert "proactive_state" in (
        app_source
    )
    assert "last_planner_json" in (
        app_source
    )
    assert "templateGroup" in js_source
    assert "templateId" in js_source


def template_inventory_case() -> None:
    from silverwolf_agent.proactive import (
        ProactiveMessageLibrary,
    )

    library = (
        ProactiveMessageLibrary()
    )
    routine_count = sum(
        len(values)
        for values in (
            library.ROUTINE_TEMPLATES
            .values()
        )
    )
    follow_up_count = sum(
        len(values)
        for values in (
            library.FOLLOW_UP_TEMPLATES
            .values()
        )
    )

    assert routine_count >= 70
    assert follow_up_count >= 20
    assert (
        "evening_unfed"
        in library.ROUTINE_TEMPLATES
    )
    assert len(
        library.ROUTINE_TEMPLATES[
            "evening_unfed"
        ]
    ) >= 16


def run() -> None:
    template_inventory_case()
    review_observability_case()

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            routine_variation_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        context_group_case(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            follow_up_variation_case(
                Path(value)
            )
        )

    print(
        "lv14_message_variation_test: OK"
    )


if __name__ == "__main__":
    run()
