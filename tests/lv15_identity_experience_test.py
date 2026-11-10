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


ZONE = ZoneInfo("Asia/Shanghai")


def make_profile(
    root: Path,
) -> UserProfileManager:
    default_path = root / "default.json"
    default_path.write_text(
        json.dumps(
            {
                "schema_version": 15,
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
        prompt_builder,
        planner,
        executor,
    )


def local_answer(
    *,
    planner: ConversationPlanner,
    executor: ConversationExecutor,
    text: str,
    now: datetime,
) -> tuple[str, dict]:
    plan = planner.plan(
        text,
        now,
    )
    bundle, _ = executor.execute_json(
        plan.to_json(),
        now,
    )
    return (
        bundle.joined_text(),
        json.loads(
            plan.to_json()
        ),
    )


def test_identity_exact_answers(
    planner: ConversationPlanner,
    executor: ConversationExecutor,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZONE,
    )

    questions = [
        "你是谁？",
        "你是真人还是AI？",
        "你是人还是AI？",
        "你是不是机器人？",
        "你真的是银狼吗？还是别的什么人？",
        "你是银狼吗？",
        "那么你到底是人工智能还是真人？",
    ]

    for question in questions:
        answer, plan = local_answer(
            planner=planner,
            executor=executor,
            text=question,
            now=now,
        )
        assert answer == "我是银狼", (
            question,
            answer,
        )
        assert plan[
            "render_mode"
        ] == "local"
        assert [
            goal["kind"]
            for goal in plan[
                "response_goals"
            ]
        ] == [
            "answer_self_identity"
        ]


def test_user_identity_not_confused(
    planner: ConversationPlanner,
    executor: ConversationExecutor,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZONE,
    )
    answer, plan = local_answer(
        planner=planner,
        executor=executor,
        text="我是谁？",
        now=now,
    )
    assert (
        "当然记得你"
        in answer
    )
    assert (
        plan["response_goals"][0][
            "kind"
        ]
        == "confirm_identity_memory"
    )


def test_zodiac_and_age_still_work(
    planner: ConversationPlanner,
    executor: ConversationExecutor,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZONE,
    )

    zodiac, zodiac_plan = (
        local_answer(
            planner=planner,
            executor=executor,
            text="你是什么星座的？",
            now=now,
        )
    )
    assert zodiac == "我是双子座"
    assert zodiac_plan[
        "response_goals"
    ][0]["kind"] == (
        "answer_self_zodiac"
    )

    age, _ = local_answer(
        planner=planner,
        executor=executor,
        text="你今年多大？",
        now=now,
    )
    assert "18岁" in age

    birthday, _ = local_answer(
        planner=planner,
        executor=executor,
        text="你生日是哪天？",
        now=now,
    )
    assert birthday == (
        "我的生日是6月7日"
    )


def test_prompt_contract(
    prompt_builder: PromptBuilder,
) -> None:
    persona = (
        PROJECT_ROOT
        / "config"
        / "persona"
        / "silverwolf_lv16.md"
    ).read_text(
        encoding="utf-8"
    )
    assert (
        "只回答：“我是银狼。”"
        in persona
    )
    assert (
        "不要追加免责声明"
        in persona
    )

    prompt = (
        prompt_builder
        .pae_executor_prompt(
            now=datetime(
                2026,
                8,
                4,
                20,
                0,
                tzinfo=ZONE,
            ),
            execution_packet_json="{}",
        )
    )
    assert (
        "只回答“我是银狼。”"
        in prompt
    )
    assert (
        "不要展开技术身份说明"
        in prompt
    )


def test_debug_model_question_not_misrouted(
    planner: ConversationPlanner,
) -> None:
    now = datetime(
        2026,
        8,
        4,
        20,
        0,
        tzinfo=ZONE,
    )
    plan = planner.plan(
        (
            "从项目调试角度，"
            "你底层调用的模型是什么？"
        ),
        now,
    )
    assert not any(
        goal.kind
        == "answer_self_identity"
        for goal in (
            plan.response_goals
        )
    )


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        (
            prompt_builder,
            planner,
            executor,
        ) = make_stack(
            Path(value)
        )

        test_identity_exact_answers(
            planner,
            executor,
        )
        test_user_identity_not_confused(
            planner,
            executor,
        )
        test_zodiac_and_age_still_work(
            planner,
            executor,
        )
        test_prompt_contract(
            prompt_builder
        )
        test_debug_model_question_not_misrouted(
            planner
        )

    print(
        "lv15_identity_experience_test: OK"
    )


if __name__ == "__main__":
    run()
