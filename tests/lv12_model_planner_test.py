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
from silverwolf_agent.llm.base import (
    BaseLLMClient,
)
from silverwolf_agent.llm.echo import (
    EchoLLMClient,
)
from silverwolf_agent.memory import (
    AgentIdentityManager,
    JsonlRAGStore,
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.models import (
    ChatMessage,
    LLMResponse,
)
from silverwolf_agent.pae import (
    ConversationExecutor,
    ConversationPlanner,
    ModelScheduleJudge,
)
from silverwolf_agent.prompts import (
    PromptBuilder,
)
from silverwolf_agent.proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    TimeManager,
)
from silverwolf_agent.tools import (
    PlanCreateTool,
    TimePreferencesSetTool,
    ToolRegistry,
)


ZONE = ZoneInfo("Asia/Shanghai")


class ScheduleJudgeLLM(
    BaseLLMClient
):
    def __init__(self) -> None:
        self.calls: list[
            dict
        ] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[
            ChatMessage
        ],
        tools=None,
    ) -> LLMResponse:
        assert "日程语义裁决器" in system
        context = json.loads(
            messages[-1].content
        )
        self.calls.append(context)

        text = context[
            "user_input"
        ]

        if (
            "吃晚饭" in text
            and (
                "5点40" in text
                or "17:40" in text
            )
        ):
            payload = {
                "action": (
                    "update_time_preference"
                ),
                "confidence": 0.99,
                "reason": (
                    "用户要直接修改晚饭提醒时间"
                ),
                "plan": {
                    "title": "",
                    "relative_seconds": 0,
                    "due_at": "",
                    "recurrence": "none",
                    "importance": 0,
                },
                "time_preference": {
                    "slot": "evening",
                    "time": "17:40",
                    "purpose": "吃晚饭",
                },
                "clarification": "",
            }
        elif (
            "你自己能更新吗"
            in text
        ):
            payload = {
                "action": (
                    "update_time_preference"
                ),
                "confidence": 0.94,
                "reason": (
                    "结合上一轮，用户要求执行修改"
                ),
                "plan": {
                    "title": "",
                    "relative_seconds": 0,
                    "due_at": "",
                    "recurrence": "none",
                    "importance": 0,
                },
                "time_preference": {
                    "slot": "evening",
                    "time": "17:40",
                    "purpose": "吃晚饭",
                },
                "clarification": "",
            }
        elif (
            "一分钟后叫我一下"
            in text
        ):
            payload = {
                "action": "create_plan",
                "confidence": 0.99,
                "reason": (
                    "用户明确要求一分钟后结束休息"
                ),
                "plan": {
                    "title": "结束休息",
                    "relative_seconds": 60,
                    "due_at": "",
                    "recurrence": "none",
                    "importance": 96,
                },
                "time_preference": {
                    "slot": "",
                    "time": "",
                    "purpose": "",
                },
                "clarification": "",
            }
        elif (
            "以后提醒我吃晚饭"
            in text
        ):
            payload = {
                "action": "clarify",
                "confidence": 0.91,
                "reason": (
                    "用户未提供具体晚饭时间"
                ),
                "plan": {
                    "title": "",
                    "relative_seconds": 0,
                    "due_at": "",
                    "recurrence": "none",
                    "importance": 0,
                },
                "time_preference": {
                    "slot": "",
                    "time": "",
                    "purpose": "",
                },
                "clarification": (
                    "你希望我每天几点提醒你吃晚饭？"
                ),
            }
        else:
            payload = {
                "action": "none",
                "confidence": 0.95,
                "reason": "不是日程动作",
                "plan": {
                    "title": "",
                    "relative_seconds": 0,
                    "due_at": "",
                    "recurrence": "none",
                    "importance": 0,
                },
                "time_preference": {
                    "slot": "",
                    "time": "",
                    "purpose": "",
                },
                "clarification": "",
            }

        return LLMResponse(
            text=json.dumps(
                payload,
                ensure_ascii=False,
            )
        )


def make_profile(
    root: Path,
) -> UserProfileManager:
    default_path = root / "default.json"
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 12,
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


def make_stack(
    root: Path,
    *,
    judge_llm: BaseLLMClient,
):
    identity = AgentIdentityManager(
        path=(
            PROJECT_ROOT
            / "config"
            / "default_agent_profile.json"
        )
    )
    profile = make_profile(root)
    memory = ShortTermMemory(
        path=root / "memory.json",
        max_recent_turns=30,
    )
    rag = JsonlRAGStore(
        path=root / "rag.jsonl"
    )
    time_manager = TimeManager(
        path=root / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=root / "plans.json"
    )

    registry = ToolRegistry()
    registry.register(
        PlanCreateTool(
            plan_manager
        )
    )
    registry.register(
        TimePreferencesSetTool(
            time_manager
        )
    )

    prompt_builder = PromptBuilder(
        agent_identity=identity
    )
    judge = ModelScheduleJudge(
        llm=judge_llm,
        enabled=True,
        minimum_confidence=0.72,
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
        agent_identity=identity,
        schedule_judge=judge,
    )
    executor = ConversationExecutor(
        llm=EchoLLMClient(),
        tool_registry=registry,
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=prompt_builder,
        agent_identity=identity,
    )
    return (
        profile,
        memory,
        time_manager,
        plan_manager,
        planner,
        executor,
    )


def test_dinner_time_update(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        16,
        47,
        58,
        tzinfo=ZONE,
    )
    judge_llm = ScheduleJudgeLLM()
    (
        _profile,
        memory,
        time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        judge_llm=judge_llm,
    )

    text = (
        "更新一下提醒我吃晚饭的时间，"
        "我差不多是5点40左右就该"
        "提醒我吃晚饭了"
    )
    plan = planner.plan(
        text,
        now,
    )

    judgement = plan.metadata[
        "model_schedule_judgement"
    ]
    assert judgement[
        "accepted"
    ]
    assert judgement[
        "action"
    ] == "update_time_preference"
    assert plan.metadata[
        "schedule_resolution_source"
    ] == "model"

    assert any(
        request.name
        == "time_preferences_set"
        and request.arguments == {
            "slot": "evening",
            "time": "17:40",
        }
        for request
        in plan.tool_requests
    )
    assert not any(
        request.name == "plan_create"
        for request
        in plan.tool_requests
    )

    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    assert (
        time_manager.slot_time(
            "evening"
        )
        == "17:40"
    )
    assert "17:40" in (
        bundle.joined_text()
    )
    assert not plan_manager.list_plans(
        active_only=True
    )

    memory.add_turn(
        text,
        bundle.joined_text(),
        at=now,
        assistant_at=(
            now
            + timedelta(seconds=1)
        ),
    )

    # A follow-up can be resolved from the preceding conversation.
    follow_up = planner.plan(
        "你自己能更新吗",
        now + timedelta(
            seconds=13
        ),
    )
    assert follow_up.metadata[
        "model_schedule_judgement"
    ]["action"] == (
        "update_time_preference"
    )
    assert (
        judge_llm.calls[-1][
            "recent_messages"
        ][-1]["content"]
        == bundle.joined_text()
    )


async def reminder_delivery_case(
    root: Path,
) -> None:
    now = datetime.now(
        ZONE
    )
    judge_llm = ScheduleJudgeLLM()
    (
        profile,
        memory,
        time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        judge_llm=judge_llm,
    )

    # Disable routine morning/noon/evening messages;
    # the one-minute plan remains active.
    time_manager.set_proactive_enabled(
        False
    )

    text = (
        "行，对了你一分钟后叫我一下，"
        "我休息一分钟"
    )
    plan = planner.plan(
        text,
        now,
    )
    judgement = plan.metadata[
        "model_schedule_judgement"
    ]
    assert judgement[
        "action"
    ] == "create_plan"
    assert judgement[
        "title"
    ] == "结束休息"

    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    assert "我叫你起来" in (
        bundle.joined_text()
    )

    active = plan_manager.list_plans(
        active_only=True
    )
    assert len(active) == 1
    due = datetime.fromisoformat(
        active[0].due_at
    )
    assert due == (
        now
        + timedelta(seconds=60)
    )

    sink = CollectingMessageSink()
    scheduler = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=plan_manager,
        state=ProactiveStateStore(
            path=root / "state.json"
        ),
        planner=ProactivePlanner(
            profile=profile,
            memory=memory,
            message_gap_seconds=0.0,
        ),
        executor=ProactiveExecutor(),
        memory=memory,
        dispatcher=MessageDispatcher(
            default_gap_seconds=0.0,
        ),
        now_provider=lambda: (
            due
            + timedelta(
                seconds=1
            )
        ),
        poll_seconds=1.0,
    )

    result = await scheduler.run_once(
        sink=sink,
        now=(
            due
            + timedelta(
                seconds=1
            )
        ),
    )
    assert result is not None
    assert any(
        "休息结束" in (
            message.content
        )
        for message in sink.messages
    )
    assert not plan_manager.list_plans(
        active_only=True
    )


def test_one_minute_reminder(
    root: Path,
) -> None:
    asyncio.run(
        reminder_delivery_case(
            root
        )
    )


def test_clarification(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        17,
        0,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        judge_llm=(
            ScheduleJudgeLLM()
        ),
    )

    plan = planner.plan(
        "以后提醒我吃晚饭",
        now,
    )
    assert any(
        goal.kind
        == "clarify_schedule"
        for goal in (
            plan.response_goals
        )
    )
    assert not plan.tool_requests

    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    assert bundle.joined_text() == (
        "你希望我每天几点提醒你吃晚饭？"
    )


class InvalidJudgeLLM(
    BaseLLMClient
):
    def complete(
        self,
        *,
        system: str,
        messages: list[
            ChatMessage
        ],
        tools=None,
    ) -> LLMResponse:
        return LLMResponse(
            text=json.dumps(
                {
                    "action": (
                        "update_time_preference"
                    ),
                    "confidence": 0.99,
                    "reason": "非法时间测试",
                    "time_preference": {
                        "slot": "evening",
                        "time": "25:70",
                        "purpose": "吃晚饭",
                    },
                },
                ensure_ascii=False,
            )
        )


def test_invalid_model_output_falls_back(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        16,
        47,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        _plan_manager,
        planner,
        _executor,
    ) = make_stack(
        root,
        judge_llm=InvalidJudgeLLM(),
    )

    plan = planner.plan(
        (
            "更新一下提醒我吃晚饭的时间，"
            "我差不多是5点40左右就该"
            "提醒我吃晚饭了"
        ),
        now,
    )
    judgement = plan.metadata[
        "model_schedule_judgement"
    ]
    assert judgement[
        "consulted"
    ]
    assert not judgement[
        "accepted"
    ]
    assert plan.metadata[
        "schedule_resolution_source"
    ] == "rule_fallback"


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_dinner_time_update(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_one_minute_reminder(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_clarification(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_invalid_model_output_falls_back(
            Path(value)
        )

    print(
        "lv12_model_planner_test: OK"
    )


if __name__ == "__main__":
    run()
