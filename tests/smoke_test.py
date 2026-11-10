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
from silverwolf_agent.config import (
    AppConfig,
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
from silverwolf_agent.memory.profile import (
    UserProfileManager,
)
from silverwolf_agent.models import (
    ChatMessage,
    LLMResponse,
)
from silverwolf_agent.memory.rag import (
    JsonlRAGStore,
)
from silverwolf_agent.memory.short_term import (
    ShortTermMemory,
)
from silverwolf_agent.pae import (
    ConversationExecutor,
    ConversationPlan,
    ConversationPlanner,
    ExecutionPacket,
)
from silverwolf_agent.proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    ScheduleIntentAnalyzer,
    TimeManager,
)
from silverwolf_agent.prompts import (
    PromptBuilder,
)
from silverwolf_agent.tools import (
    CurrentTimeTool,
    PlanCancelTool,
    PlanCreateTool,
    PlanListTool,
    PreferredNameTool,
    ProfileUpdateTool,
    TimePreferencesGetTool,
    TimePreferencesSetTool,
    ToolRegistry,
)


def make_profile(
    temp: Path,
) -> UserProfileManager:
    default_path = temp / "default.json"
    profile_path = temp / "profile.json"

    default_path.write_text(
        json.dumps(
            {
                "schema_version": 7,
                "stable": {
                    "identity": "中国双一流大学在读大学生",
                    "birthday": "2000-01-01",
                    "skills": [
                        "自学计算机",
                        "具备一定网络安全技术能力",
                    ],
                },
                "dynamic": {
                    "preferred_name": "星",
                    "casual_aliases": ["宝"],
                    "address_style": {
                        "default": "星",
                        "casual": "宝",
                        "casual_usage": (
                            "仅在轻松、亲密、不严肃的"
                            "场景偶尔使用"
                        ),
                    },
                },
                "metadata": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return UserProfileManager(
        path=profile_path,
        default_path=default_path,
    )


def make_registry(
    *,
    profile: UserProfileManager,
    plan_manager: PlanManager,
    time_manager: TimeManager,
    now: datetime,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        CurrentTimeTool(
            "Asia/Shanghai",
            now_provider=lambda: now,
        )
    )
    registry.register(
        ProfileUpdateTool(profile)
    )
    registry.register(
        PreferredNameTool(profile)
    )
    registry.register(
        PlanCreateTool(plan_manager)
    )
    registry.register(
        PlanListTool(plan_manager)
    )
    registry.register(
        PlanCancelTool(plan_manager)
    )
    registry.register(
        TimePreferencesGetTool(
            time_manager
        )
    )
    registry.register(
        TimePreferencesSetTool(
            time_manager
        )
    )
    return registry


def test_config_and_imports() -> None:
    config = AppConfig(
        api_key=None,
        base_url="https://example.invalid",
        model="deepseek-v4-flash",
        timezone="Asia/Shanghai",
        max_tokens=500,
        temperature=0.8,
        max_retries=3,
        retry_base_seconds=0.01,
        scheduler_poll_seconds=1.0,
        message_gap_seconds=0.0,
    )
    assert (
        config.zoneinfo().key
        == "Asia/Shanghai"
    )
    assert callable(
        getattr(
            SilverWolfAgent,
            "chat",
            None,
        )
    )
    assert callable(
        getattr(
            SilverWolfAgent,
            "handle_user_message",
            None,
        )
    )
    assert callable(
        getattr(
            SilverWolfAgent,
            "start",
            None,
        )
    )


def test_mixed_goal_and_split_messages(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        13,
        55,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
        max_recent_turns=8,
    )
    rag = JsonlRAGStore(
        path=temp / "rag.jsonl"
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=temp / "plans.json"
    )

    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
    )

    text = (
        "你看看几点了，"
        "我已经吃过了，"
        "都睡好午觉啦"
    )
    plan_json = planner.plan_json(
        text,
        now,
    )
    plan = ConversationPlan.from_json(
        plan_json
    )

    goal_map = {
        goal.kind: goal
        for goal in plan.response_goals
    }
    assert (
        "acknowledge_context"
        in goal_map
    )
    assert (
        "answer_current_time"
        in goal_map
    )
    assert (
        goal_map[
            "acknowledge_context"
        ].weight
        > goal_map[
            "answer_current_time"
        ].weight
    )
    assert plan.intent == "mixed"
    assert json.loads(
        plan_json
    )["plan_id"] == plan.plan_id

    registry = make_registry(
        profile=profile,
        plan_manager=plan_manager,
        time_manager=time_manager,
        now=now,
    )
    executor = ConversationExecutor(
        llm=EchoLLMClient(),
        tool_registry=registry,
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(),
    )
    bundle, packet_json = (
        executor.execute_json(
            plan_json,
            now,
        )
    )

    messages = (
        bundle.selected_messages()
    )
    assert len(messages) == 2
    assert "吃过饭" in messages[0].content
    assert "午觉" in messages[0].content
    assert "13:55" in messages[1].content
    assert (
        messages[0].weight
        > messages[1].weight
    )

    packet = ExecutionPacket.from_json(
        packet_json
    )
    assert (
        packet.plan["plan_id"]
        == plan.plan_id
    )
    assert (
        packet.tool_results[0].name
        == "time_now"
    )


def test_schedule_importance_and_creation(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
    )
    rag = JsonlRAGStore(
        path=temp / "rag.jsonl"
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=temp / "plans.json"
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
    )

    important_text = (
        "我明天要学习pandas，"
        "你记得提醒我"
    )
    plan = planner.plan(
        important_text,
        now,
    )
    decision = plan.metadata[
        "schedule_decision"
    ]

    assert decision[
        "should_persist"
    ]
    assert decision[
        "importance"
    ] >= 65
    assert decision["title"] == (
        "学习pandas"
    )
    assert any(
        request.name == "plan_create"
        for request
        in plan.tool_requests
    )
    assert any(
        goal.kind == "confirm_schedule"
        and goal.weight >= 85
        for goal
        in plan.response_goals
    )

    registry = make_registry(
        profile=profile,
        plan_manager=plan_manager,
        time_manager=time_manager,
        now=now,
    )
    executor = ConversationExecutor(
        llm=EchoLLMClient(),
        tool_registry=registry,
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(),
    )

    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    assert "我来喊你学习pandas" in (
        bundle.joined_text()
    )
    assert "明天早上" in (
        bundle.joined_text()
    )

    active = plan_manager.list_plans(
        active_only=True
    )
    assert len(active) == 1
    assert active[0].title == (
        "学习pandas"
    )
    due = datetime.fromisoformat(
        active[0].due_at
    )
    assert due.date() == (
        now.date()
        + timedelta(days=1)
    )
    assert due.strftime(
        "%H:%M"
    ) == time_manager.slot_time(
        "morning"
    )


def test_low_importance_is_not_persisted(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=temp / "plans.json"
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
    )

    plan = planner.plan(
        "我明天可能学pandas",
        now,
    )
    decision = plan.metadata[
        "schedule_decision"
    ]

    assert not decision[
        "should_persist"
    ]
    assert not any(
        request.name == "plan_create"
        for request
        in plan.tool_requests
    )
    assert not plan_manager.list_plans(
        active_only=True
    )


def test_time_preference_edit(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
    )
    rag = JsonlRAGStore(
        path=temp / "rag.jsonl"
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=temp / "plans.json"
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
    )

    plan = planner.plan(
        "以后早上九点叫我起床",
        now,
    )
    assert any(
        request.name
        == "time_preferences_set"
        and request.arguments[
            "slot"
        ] == "morning"
        and request.arguments[
            "time"
        ] == "09:00"
        for request
        in plan.tool_requests
    )

    registry = make_registry(
        profile=profile,
        plan_manager=plan_manager,
        time_manager=time_manager,
        now=now,
    )
    executor = ConversationExecutor(
        llm=EchoLLMClient(),
        tool_registry=registry,
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(),
    )
    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )

    assert (
        time_manager.slot_time(
            "morning"
        )
        == "09:00"
    )
    assert "09:00" in (
        bundle.joined_text()
    )


async def test_async_proactive_scheduler(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        5,
        8,
        5,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    time_manager.set_slot(
        "morning",
        "08:00",
        window_minutes=45,
    )

    plan_manager = PlanManager(
        path=temp / "plans.json"
    )
    scheduled = plan_manager.create(
        title="学习pandas",
        details=(
            "明天要学习pandas"
        ),
        due_at=(
            now
            - timedelta(minutes=1)
        ).isoformat(
            timespec="seconds"
        ),
        importance=95,
        source_text=(
            "明天要学习pandas，"
            "记得提醒我"
        ),
    )

    state = ProactiveStateStore(
        path=temp / "state.json"
    )
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        message_gap_seconds=0.0,
    )
    executor = ProactiveExecutor()
    sink = CollectingMessageSink()
    dispatcher = MessageDispatcher(
        default_gap_seconds=0.0,
    )

    scheduler = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=plan_manager,
        state=state,
        planner=planner,
        executor=executor,
        memory=memory,
        dispatcher=dispatcher,
        now_provider=lambda: now,
        poll_seconds=1.0,
    )

    bundle = await scheduler.run_once(
        sink=sink,
        now=now,
    )
    assert bundle is not None
    assert len(sink.messages) >= 2
    contents = "\n".join(
        message.content
        for message
        in sink.messages
    )
    assert sink.messages
    morning_message = sink.messages[0]
    assert (
        morning_message.category
        == "routine_morning"
    )
    assert (
        morning_message.metadata[
            "template_group"
        ]
        in {
            "morning_general",
            "morning_busy",
        }
    )
    assert morning_message.content
    assert "学习pandas" in (
        contents
    )
    assert any(
        message.weight >= 95
        for message
        in sink.messages
        if "学习pandas"
        in message.content
    )
    assert state.routine_sent(
        "morning",
        now.date().isoformat(),
    )
    assert (
        plan_manager
        .list_plans(
            active_only=True
        )
        == []
    )
    assert scheduler.last_plan_json
    assert scheduler.last_execution_json
    assert json.loads(
        scheduler.last_plan_json
    )["scheduled_plan_ids"] == [
        scheduled.plan_id
    ]

    before = len(
        sink.messages
    )
    second = await scheduler.run_once(
        sink=sink,
        now=now,
    )
    assert second is None
    assert len(
        sink.messages
    ) == before



class RegressionJsonLLM(BaseLLMClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools=None,
    ) -> LLMResponse:
        assert "PAE Executor 输出规则" in system
        assert callable(
            getattr(
                PromptBuilder,
                "pae_executor_prompt",
                None,
            )
        )

        user_text = messages[-1].content
        self.calls.append(user_text)

        if "睡得很不错" in user_text:
            payload = {
                "messages": [
                    {
                        "content": (
                            "听起来这次午觉"
                            "睡得挺舒服的。"
                        ),
                        "weight": 84,
                        "category": (
                            "acknowledge_user_state"
                        ),
                        "goal_kinds": [
                            "acknowledge_user_state"
                        ],
                        "sequence": 0,
                    },
                    {
                        "content": (
                            "还是 14:15，宝。"
                        ),
                        "weight": 62,
                        "category": (
                            "answer_current_time"
                        ),
                        "goal_kinds": [
                            "answer_current_time"
                        ],
                        "sequence": 1,
                    },
                ]
            }
        elif "一直在开发东西" in user_text:
            payload = {
                "messages": [
                    {
                        "content": (
                            "一直盯着开发确实"
                            "容易把脑子绕晕。"
                            "先缓一下，别硬撑。"
                        ),
                        "weight": 84,
                        "category": (
                            "acknowledge_user_state"
                        ),
                        "goal_kinds": [
                            "acknowledge_user_state"
                        ],
                        "sequence": 0,
                    }
                ]
            }
        else:
            payload = {
                "messages": [
                    {
                        "content": "在，星",
                        "weight": 72,
                        "category": (
                            "continue_conversation"
                        ),
                        "goal_kinds": [
                            "continue_conversation"
                        ],
                        "sequence": 0,
                    }
                ]
            }

        return LLMResponse(
            text=json.dumps(
                payload,
                ensure_ascii=False,
            )
        )


def test_lv6_failure_regression(
    temp: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        14,
        15,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    # The original lv6 crash was caused by this method
    # being written outside the PromptBuilder class.
    assert "pae_executor_prompt" in (
        PromptBuilder.__dict__
    )
    assert callable(
        PromptBuilder.__dict__[
            "pae_executor_prompt"
        ]
    )

    profile = make_profile(temp)
    memory = ShortTermMemory(
        path=temp / "memory.json",
        max_recent_turns=12,
    )
    rag = JsonlRAGStore(
        path=temp / "rag.jsonl"
    )
    time_manager = TimeManager(
        path=temp / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(
        path=temp / "plans.json"
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
    )
    registry = make_registry(
        profile=profile,
        plan_manager=plan_manager,
        time_manager=time_manager,
        now=now,
    )
    fake_llm = RegressionJsonLLM()
    executor = ConversationExecutor(
        llm=fake_llm,
        tool_registry=registry,
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(),
    )

    # 1. Pure time: local path.
    first_plan = planner.plan(
        "现在几点了",
        now,
    )
    assert first_plan.render_mode == "local"
    first_bundle, _ = (
        executor.execute_json(
            first_plan.to_json(),
            now,
        )
    )
    assert "14:15" in (
        first_bundle.joined_text()
    )
    memory.add_turn(
        "现在几点了",
        first_bundle.joined_text(),
    )

    # 2. Ordinary state sharing + time question:
    # both meanings must survive planning.
    second_text = (
        "今天中午睡得很不错，"
        "对了现在几点了"
    )
    second_plan = planner.plan(
        second_text,
        now,
    )
    second_goals = {
        goal.kind: goal
        for goal in (
            second_plan.response_goals
        )
    }
    assert (
        "acknowledge_user_state"
        in second_goals
    )
    assert (
        "answer_current_time"
        in second_goals
    )
    assert (
        second_goals[
            "acknowledge_user_state"
        ].source_text
        == "今天中午睡得很不错"
    )
    assert second_plan.render_mode == "llm"

    second_bundle, _ = (
        executor.execute_json(
            second_plan.to_json(),
            now,
        )
    )
    second_messages = (
        second_bundle
        .selected_messages()
    )
    assert len(second_messages) == 2
    assert "午觉" in (
        second_messages[0].content
    )
    assert "14:15" in (
        second_messages[1].content
    )
    memory.add_turn(
        second_text,
        second_bundle.joined_text(),
    )

    # 3. State-only message must use the model branch
    # without raising PromptBuilder AttributeError.
    third_text = (
        "一直在开发东西，"
        "感觉自己总是忘记一些事，"
        "晕晕的"
    )
    third_plan = planner.plan(
        third_text,
        now,
    )
    assert third_plan.render_mode == "llm"
    assert any(
        goal.kind
        == "acknowledge_user_state"
        for goal in (
            third_plan.response_goals
        )
    )
    assert third_plan.metadata[
        "user_state_facts"
    ] == [
        "一直在开发东西",
        "感觉自己总是忘记一些事",
        "晕晕的",
    ]

    third_bundle, _ = (
        executor.execute_json(
            third_plan.to_json(),
            now,
        )
    )
    assert "别硬撑" in (
        third_bundle.joined_text()
    )
    memory.add_turn(
        third_text,
        third_bundle.joined_text(),
    )

    # 4. A following normal message must still work.
    fourth_plan = planner.plan(
        "在吗",
        now,
    )
    assert fourth_plan.render_mode == "llm"
    fourth_bundle, _ = (
        executor.execute_json(
            fourth_plan.to_json(),
            now,
        )
    )
    assert fourth_bundle.joined_text() == (
        "在，星"
    )

    assert fake_llm.calls == [
        second_text,
        third_text,
        "在吗",
    ]


def run() -> None:
    test_config_and_imports()

    with tempfile.TemporaryDirectory() as value:
        test_mixed_goal_and_split_messages(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_schedule_importance_and_creation(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_low_importance_is_not_persisted(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_time_preference_edit(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            test_async_proactive_scheduler(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        test_lv6_failure_regression(
            Path(value)
        )

    print("smoke_test: OK")


if __name__ == "__main__":
    run()
