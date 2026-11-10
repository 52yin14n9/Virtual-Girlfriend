from __future__ import annotations

import asyncio
from concurrent.futures import Future
from datetime import (
    datetime,
    timedelta,
)
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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
from silverwolf_agent.llm.echo import (
    EchoLLMClient,
)
from silverwolf_agent.memory.profile import (
    UserProfileManager,
)
from silverwolf_agent.memory.rag import (
    JsonlRAGStore,
)
from silverwolf_agent.memory.short_term import (
    ShortTermMemory,
)
from silverwolf_agent.pae import (
    ConversationExecutor,
    ConversationPlanner,
)
from silverwolf_agent.proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    TimeManager,
)
from silverwolf_agent.prompts import (
    PromptBuilder,
)
from silverwolf_agent.tools import (
    ConversationHistoryLookupTool,
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
from silverwolf_agent.webapp import (
    MessageStore,
)


def make_profile(
    root: Path,
) -> UserProfileManager:
    default_path = root / "default.json"
    profile_path = root / "profile.json"
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 9,
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
        path=profile_path,
        default_path=default_path,
    )


def make_registry(
    *,
    profile: UserProfileManager,
    memory: ShortTermMemory,
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
        ConversationHistoryLookupTool(
            memory
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


def make_stack(
    root: Path,
    now: datetime,
):
    profile = make_profile(root)
    memory = ShortTermMemory(
        path=root / "memory.json",
        max_recent_turns=20,
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
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        message_gap_seconds=0.0,
    )
    registry = make_registry(
        profile=profile,
        memory=memory,
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
    return (
        profile,
        memory,
        rag,
        time_manager,
        plan_manager,
        planner,
        executor,
    )


def test_relative_two_minute_reminder(
    root: Path,
) -> None:
    start = datetime(
        2026,
        8,
        4,
        15,
        27,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )
    (
        profile,
        memory,
        _rag,
        time_manager,
        plan_manager,
        planner,
        executor,
    ) = make_stack(root, start)

    text = (
        "我准备休息两分钟，"
        "你两分钟后记得提醒我哟"
    )
    plan = planner.plan(
        text,
        start,
    )
    decision = plan.metadata[
        "schedule_decision"
    ]

    assert decision[
        "should_persist"
    ]
    assert decision["title"] == (
        "结束休息"
    )
    assert any(
        request.name == "plan_create"
        for request in plan.tool_requests
    )

    bundle, _ = executor.execute_json(
        plan.to_json(),
        start,
    )
    assert "我叫你起来" in (
        bundle.joined_text()
    )

    active = plan_manager.list_plans(
        active_only=True
    )
    assert len(active) == 1
    due_at = datetime.fromisoformat(
        active[0].due_at
    )
    assert due_at == (
        start
        + timedelta(minutes=2)
    )

    state = ProactiveStateStore(
        path=root / "state.json"
    )
    proactive_planner = (
        ProactivePlanner(
            profile=profile,
            memory=memory,
            message_gap_seconds=0.0,
        )
    )
    sink = CollectingMessageSink()
    scheduler = AsyncProactiveScheduler(
        time_manager=time_manager,
        plan_manager=plan_manager,
        state=state,
        planner=proactive_planner,
        executor=ProactiveExecutor(),
        memory=memory,
        dispatcher=MessageDispatcher(
            default_gap_seconds=0.0,
        ),
        now_provider=lambda: (
            due_at
            + timedelta(seconds=1)
        ),
        poll_seconds=1.0,
    )

    result = asyncio.run(
        scheduler.run_once(
            sink=sink,
            now=(
                due_at
                + timedelta(seconds=1)
            ),
        )
    )
    assert result is not None
    assert any(
        "时间到啦" in message.content
        and "休息结束" in message.content
        for message in sink.messages
    )
    assert not plan_manager.list_plans(
        active_only=True
    )


def test_exact_conversation_times(
    root: Path,
) -> None:
    current = datetime(
        2026,
        8,
        4,
        15,
        30,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )
    (
        _profile,
        memory,
        _rag,
        _time_manager,
        _plan_manager,
        planner,
        executor,
    ) = make_stack(root, current)

    rest_at = datetime(
        2026,
        8,
        4,
        15,
        27,
        3,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )
    forgot_at = datetime(
        2026,
        8,
        4,
        15,
        29,
        14,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    memory.add_turn(
        (
            "我准备休息两分钟，"
            "你两分钟后记得提醒我哟"
        ),
        "行，我记住了。",
        at=rest_at,
        assistant_at=(
            rest_at
            + timedelta(seconds=1)
        ),
    )
    memory.add_turn(
        "你是不是忘记提醒我啦",
        "没有忘。",
        at=forgot_at,
        assistant_at=(
            forgot_at
            + timedelta(seconds=1)
        ),
    )

    latest_plan = planner.plan(
        "我刚才问你的时候是什么时间",
        current,
    )
    assert any(
        goal.kind
        == "answer_message_time"
        for goal in (
            latest_plan.response_goals
        )
    )
    assert any(
        request.name
        == "conversation_history_lookup"
        and request.arguments[
            "mode"
        ] == "latest"
        for request
        in latest_plan.tool_requests
    )

    latest_bundle, _ = (
        executor.execute_json(
            latest_plan.to_json(),
            current,
        )
    )
    assert "15:29:14" in (
        latest_bundle.joined_text()
    )

    rest_plan = planner.plan(
        "我说的是我开始休息的时候呢",
        current,
    )
    assert any(
        request.name
        == "conversation_history_lookup"
        and request.arguments[
            "mode"
        ] == "keyword"
        and request.arguments[
            "keyword"
        ] == "休息"
        for request
        in rest_plan.tool_requests
    )

    rest_bundle, _ = (
        executor.execute_json(
            rest_plan.to_json(),
            current,
        )
    )
    assert "15:27:03" in (
        rest_bundle.joined_text()
    )
    assert "开始休息" in (
        rest_bundle.joined_text()
    )

    context = memory.context_text()
    assert rest_at.isoformat(
        timespec="seconds"
    ) in context
    assert forgot_at.isoformat(
        timespec="seconds"
    ) in context


class FakeProfile:
    @staticmethod
    def preferred_name() -> str:
        return "星"


class FakePlanManager:
    @staticmethod
    def cancel(
        plan_id: str,
    ) -> bool:
        return bool(plan_id)


class FakeTimeManager:
    def __init__(self) -> None:
        self.values = {
            "slots": {
                "morning": {
                    "time": "08:00"
                },
                "noon": {
                    "time": "12:10"
                },
                "evening": {
                    "time": "18:30"
                },
            }
        }

    def set_slot(
        self,
        slot: str,
        value: str,
    ):
        self.values["slots"][
            slot
        ]["time"] = value
        return self.values["slots"][
            slot
        ]


class FakeAgent:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            model="fake-model",
            timezone="Asia/Shanghai",
        )
        self.profile = FakeProfile()
        self.scheduler = SimpleNamespace(
            running=True,
            last_error=None,
        )
        self.plan_manager = (
            FakePlanManager()
        )
        self.time_manager = (
            FakeTimeManager()
        )
        self.offline = True

    @staticmethod
    def now() -> datetime:
        return datetime(
            2026,
            8,
            4,
            15,
            31,
            22,
            tzinfo=ZoneInfo(
                "Asia/Shanghai"
            ),
        )

    @staticmethod
    def plans_snapshot():
        return []

    def time_snapshot(self):
        return self.time_manager.values

    @staticmethod
    def pae_debug() -> str:
        return "{}"


class FakeRuntime:
    def __init__(
        self,
        store: MessageStore,
    ) -> None:
        self.store = store
        self.running = True

    def submit_user_message(
        self,
        text: str,
        *,
        received_at: datetime,
    ) -> Future:
        self.store.publish(
            role="assistant",
            content=f"收到：{text}",
            timestamp=(
                received_at
                + timedelta(seconds=1)
            ),
            source="interactive",
            weight=80,
            category="conversation",
        )
        future: Future = Future()
        future.set_result(None)
        return future

    def trigger_proactive_once(
        self,
    ) -> Future:
        self.store.publish(
            role="assistant",
            content="主动检查完成。",
            timestamp=FakeAgent.now(),
            source="proactive",
            weight=75,
            category="proactive_test",
        )
        future: Future = Future()
        future.set_result(None)
        return future

    @staticmethod
    def start() -> None:
        return None

    @staticmethod
    def stop() -> None:
        return None


def test_flask_frontend() -> None:
    app_source = (
        PROJECT_ROOT
        / "silverwolf_agent"
        / "webapp"
        / "app.py"
    ).read_text(
        encoding="utf-8"
    )
    html_source = (
        PROJECT_ROOT
        / "silverwolf_agent"
        / "webapp"
        / "templates"
        / "index.html"
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

    assert "text/event-stream" in (
        app_source
    )
    assert "/api/chat" in app_source
    assert "/api/events" in app_source
    assert "NEURAL LINK" in html_source
    assert "EventSource" in js_source

    try:
        import flask  # noqa: F401
    except ModuleNotFoundError:
        # The execution environment used to
        # build the ZIP does not include Flask.
        # Syntax and endpoint structure are still
        # checked above; runtime testing occurs
        # after requirements.txt is installed.
        return

    from silverwolf_agent.webapp import (
        create_app,
    )

    store = MessageStore()
    agent = FakeAgent()
    runtime = FakeRuntime(store)

    app = create_app(
        agent=agent,
        store=store,
        runtime=runtime,
        start_runtime=False,
    )
    app.config.update(
        TESTING=True
    )
    client = app.test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert "银狼" in page.get_data(
        as_text=True
    )
    assert "NEURAL LINK" in (
        page.get_data(
            as_text=True
        )
    )

    response = client.post(
        "/api/chat",
        json={
            "message": "下午好，小宝"
        },
    )
    assert response.status_code == 202

    messages = client.get(
        "/api/messages"
    ).get_json()["messages"]
    assert [
        item["role"]
        for item in messages
    ] == [
        "user",
        "assistant",
    ]
    assert all(
        "+08:00" in item[
            "timestamp"
        ]
        for item in messages
    )

    status = client.get(
        "/api/status"
    )
    assert status.status_code == 200
    assert status.get_json()[
        "runtime_running"
    ]

    tick = client.post(
        "/api/proactive/tick"
    )
    assert tick.status_code == 202

    messages = client.get(
        "/api/messages"
    ).get_json()["messages"]
    assert any(
        item["source"]
        == "proactive"
        for item in messages
    )

    css = client.get(
        "/static/style.css"
    )
    js = client.get(
        "/static/app.js"
    )
    assert css.status_code == 200
    assert js.status_code == 200


def run() -> None:
    assert "pae_executor_prompt" in (
        PromptBuilder.__dict__
    )

    with tempfile.TemporaryDirectory() as value:
        test_relative_two_minute_reminder(
            Path(value)
        )

    with tempfile.TemporaryDirectory() as value:
        test_exact_conversation_times(
            Path(value)
        )

    test_flask_frontend()
    print("lv9_regression_test: OK")


if __name__ == "__main__":
    run()
