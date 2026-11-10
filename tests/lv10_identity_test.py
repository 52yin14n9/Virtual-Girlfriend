from __future__ import annotations

from datetime import datetime
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

from silverwolf_agent.llm.echo import (
    EchoLLMClient,
)
from silverwolf_agent.memory import (
    AgentIdentityManager,
    JsonlRAGStore,
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.pae import (
    ConversationExecutor,
    ConversationPlanner,
)
from silverwolf_agent.prompts import (
    PromptBuilder,
)
from silverwolf_agent.proactive import (
    PlanManager,
    TimeManager,
)
from silverwolf_agent.tools import (
    ToolRegistry,
)


def make_user_profile(
    root: Path,
) -> UserProfileManager:
    default_path = (
        root / "default_user.json"
    )
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 10,
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
        path=root / "user.json",
        default_path=default_path,
    )


def make_stack(
    root: Path,
):
    identity = AgentIdentityManager(
        path=(
            PROJECT_ROOT
            / "config"
            / "default_agent_profile.json"
        )
    )
    profile = make_user_profile(
        root
    )
    memory = ShortTermMemory(
        path=root / "memory.json",
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
        llm=EchoLLMClient(),
        tool_registry=ToolRegistry(),
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=prompt_builder,
        agent_identity=identity,
    )
    return (
        identity,
        prompt_builder,
        planner,
        executor,
    )


def test_dynamic_age_boundary(
    identity: AgentIdentityManager,
) -> None:
    assert (
        identity.birthday()
        .isoformat()
        == "2008-06-07"
    )
    assert (
        identity.birthday_display()
        == "6月7日"
    )

    assert identity.age_on(
        datetime.fromisoformat(
            "2026-08-04T12:00:00+08:00"
        )
    ) == 18

    assert identity.age_on(
        datetime.fromisoformat(
            "2027-06-06T23:59:59+08:00"
        )
    ) == 18

    assert identity.age_on(
        datetime.fromisoformat(
            "2027-06-07T00:00:00+08:00"
        )
    ) == 19

    assert identity.age_on(
        datetime.fromisoformat(
            "2028-06-07T00:00:00+08:00"
        )
    ) == 20


def test_prompt_dynamic_age(
    prompt_builder: PromptBuilder,
) -> None:
    before = prompt_builder.pae_executor_prompt(
        now=datetime(
            2027,
            6,
            6,
            23,
            59,
            tzinfo=ZoneInfo(
                "Asia/Shanghai"
            ),
        ),
        execution_packet_json="{}",
    )
    birthday = prompt_builder.pae_executor_prompt(
        now=datetime(
            2027,
            6,
            7,
            0,
            0,
            tzinfo=ZoneInfo(
                "Asia/Shanghai"
            ),
        ),
        execution_packet_json="{}",
    )

    assert '"current_age": 18' in before
    assert (
        '"current_age": 19'
        in birthday
    )
    assert (
        '"birthday": "2008-06-07"'
        in birthday
    )
    assert (
        "禁止把当前年龄写死"
        in birthday
    )


def answer(
    *,
    planner: ConversationPlanner,
    executor: ConversationExecutor,
    text: str,
    now: datetime,
) -> str:
    plan = planner.plan(
        text,
        now,
    )
    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    return bundle.joined_text()


def test_local_self_identity_answers(
    planner: ConversationPlanner,
    executor: ConversationExecutor,
) -> None:
    current = datetime(
        2026,
        8,
        4,
        12,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )
    before_birthday = datetime(
        2027,
        6,
        6,
        23,
        59,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )
    birthday = datetime(
        2027,
        6,
        7,
        0,
        0,
        tzinfo=ZoneInfo(
            "Asia/Shanghai"
        ),
    )

    current_answer = answer(
        planner=planner,
        executor=executor,
        text="你现在多大了",
        now=current,
    )
    assert "我现在18岁" in (
        current_answer
    )
    assert "2027年6月7日" in (
        current_answer
    )
    assert "19岁" in (
        current_answer
    )

    before_answer = answer(
        planner=planner,
        executor=executor,
        text="你几岁",
        now=before_birthday,
    )
    assert "我现在18岁" in (
        before_answer
    )

    birthday_answer = answer(
        planner=planner,
        executor=executor,
        text="你现在多大",
        now=birthday,
    )
    assert (
        "今天刚好是我生日"
        in birthday_answer
    )
    assert "已经19岁" in (
        birthday_answer
    )

    birthday_date_answer = answer(
        planner=planner,
        executor=executor,
        text="你生日什么时候",
        now=current,
    )
    assert (
        birthday_date_answer
        == "我的生日是6月7日"
    )

    next_age_answer = answer(
        planner=planner,
        executor=executor,
        text="明年过生日的时候你几岁",
        now=current,
    )
    assert "2027年6月7日" in (
        next_age_answer
    )
    assert "19岁" in (
        next_age_answer
    )


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        (
            identity,
            prompt_builder,
            planner,
            executor,
        ) = make_stack(
            Path(value)
        )

        test_dynamic_age_boundary(
            identity
        )
        test_prompt_dynamic_age(
            prompt_builder
        )
        test_local_self_identity_answers(
            planner,
            executor,
        )

    print(
        "lv10_identity_test: OK"
    )


if __name__ == "__main__":
    run()
