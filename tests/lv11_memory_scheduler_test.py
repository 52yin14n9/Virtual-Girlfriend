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
    ToolRegistry,
)


ZONE = ZoneInfo("Asia/Shanghai")


def make_profile(
    root: Path,
) -> UserProfileManager:
    default_path = root / "default.json"
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 11,
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
    llm: BaseLLMClient,
    now: datetime,
    memory_limit: int = 30,
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
        max_recent_turns=memory_limit,
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
    prompt_builder = PromptBuilder(
        agent_identity=identity
    )
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
        agent_identity=identity,
    )
    executor = ConversationExecutor(
        llm=llm,
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


def test_exact_two_minute_message_request(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        16,
        1,
        8,
        tzinfo=ZONE,
    )
    (
        _profile,
        _memory,
        _time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        llm=EchoLLMClient(),
        now=now,
    )

    text = (
        "两分钟后给我发个消息，"
        "我看看你还记不记得"
    )
    plan = planner.plan(
        text,
        now,
    )
    decision = plan.metadata[
        "schedule_decision"
    ]

    assert decision[
        "should_persist"
    ]
    assert decision[
        "title"
    ] == "主动联系星"
    assert (
        datetime.fromisoformat(
            decision["due_at"]
        )
        == now
        + timedelta(minutes=2)
    )
    assert any(
        request.name == "plan_create"
        for request
        in plan.tool_requests
    )

    bundle, packet_json = (
        executor.execute_json(
            plan.to_json(),
            now,
        )
    )
    assert (
        "我会主动来找你"
        in bundle.joined_text()
    )

    active = plan_manager.list_plans(
        active_only=True
    )
    assert len(active) == 1
    assert active[0].title == (
        "主动联系星"
    )

    packet = json.loads(
        packet_json
    )
    tool_results = packet[
        "tool_results"
    ]
    assert tool_results[0][
        "name"
    ] == "plan_create"
    assert tool_results[0]["ok"]


def test_no_fake_promise_without_due_time(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        16,
        1,
        8,
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
        llm=EchoLLMClient(),
        now=now,
    )

    plan = planner.plan(
        "以后记得来找我",
        now,
    )
    assert any(
        goal.kind
        == "cannot_confirm_future_message"
        for goal
        in plan.response_goals
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
    answer = bundle.joined_text()
    assert "没有真正设好" in answer
    assert "掐着点" not in answer


class CaptureHistoryLLM(BaseLLMClient):
    def __init__(self) -> None:
        self.messages: list[
            ChatMessage
        ] = []
        self.system = ""

    def complete(
        self,
        *,
        system: str,
        messages: list[
            ChatMessage
        ],
        tools=None,
    ) -> LLMResponse:
        self.system = system
        self.messages = list(
            messages
        )
        return LLMResponse(
            text=json.dumps(
                {
                    "messages": [
                        {
                            "content": (
                                "喵。刚才的事我也记着，"
                                "不是只看你这一句。"
                            ),
                            "weight": 80,
                            "category": (
                                "continue_conversation"
                            ),
                            "goal_kinds": [
                                "continue_conversation"
                            ],
                            "sequence": 0,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )


def test_thirty_turn_real_history(
    root: Path,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        16,
        15,
        1,
        tzinfo=ZONE,
    )
    fake = CaptureHistoryLLM()
    (
        _profile,
        memory,
        _time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        llm=fake,
        now=now,
        memory_limit=30,
    )

    for index in range(35):
        turn_at = (
            now
            - timedelta(
                minutes=35 - index
            )
        )
        memory.add_turn(
            f"第{index}轮用户消息",
            f"第{index}轮银狼回复",
            at=turn_at,
            assistant_at=(
                turn_at
                + timedelta(seconds=1)
            ),
        )

    memory.compact(
        lambda source: (
            "更早对话摘要"
        )
    )
    snapshot = memory.snapshot()
    recent = snapshot[
        "recent_turns"
    ]
    assert len(recent) == 30
    assert recent[0]["user"] == (
        "第5轮用户消息"
    )
    assert recent[-1]["user"] == (
        "第34轮用户消息"
    )

    plan_manager.create(
        title="主动联系星",
        details="两分钟后给我发个消息",
        due_at=(
            now
            + timedelta(minutes=1)
        ).isoformat(
            timespec="seconds"
        ),
        importance=95,
        source_text=(
            "两分钟后给我发个消息"
        ),
    )

    plan = planner.plan(
        "喵喵喵？",
        now,
    )
    assert len(
        plan.metadata[
            "active_plans"
        ]
    ) == 1

    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    assert "不是只看你这一句" in (
        bundle.joined_text()
    )

    # 30 full turns = 60 role messages,
    # followed by the current user input.
    assert len(fake.messages) == 61
    assert fake.messages[0].role == (
        "user"
    )
    assert fake.messages[0].content == (
        "第5轮用户消息"
    )
    assert fake.messages[1].role == (
        "assistant"
    )
    assert fake.messages[-1].content == (
        "喵喵喵？"
    )
    assert "最近30轮" in fake.system
    assert "主动联系星" in fake.system


async def background_delivery_case(
    root: Path,
) -> None:
    now = datetime.now(
        ZONE
    )
    (
        profile,
        memory,
        time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(
        root,
        llm=EchoLLMClient(),
        now=now,
    )
    time_manager.set_proactive_enabled(
        False
    )

    plan = planner.plan(
        "两秒后给我发个消息",
        now,
    )
    executor.execute_json(
        plan.to_json(),
        now,
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
            datetime.now(
                ZONE
            )
        ),
        poll_seconds=1.0,
    )

    await scheduler.start(sink)
    try:
        await asyncio.sleep(4.2)
    finally:
        await scheduler.stop()

    matching = [
        message
        for message in sink.messages
        if "我没忘，来找你了"
        in message.content
    ]
    assert len(matching) == 1
    assert not plan_manager.list_plans(
        active_only=True
    )


def test_background_delivery(
    root: Path,
) -> None:
    asyncio.run(
        background_delivery_case(
            root
        )
    )


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_exact_two_minute_message_request(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_no_fake_promise_without_due_time(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_thirty_turn_real_history(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_background_delivery(
            Path(value)
        )

    print(
        "lv11_memory_scheduler_test: OK"
    )


if __name__ == "__main__":
    run()
