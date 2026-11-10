from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.llm.echo import EchoLLMClient
from silverwolf_agent.memory import (
    AgentIdentityManager,
    JsonlRAGStore,
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.pae import ConversationExecutor, ConversationPlanner
from silverwolf_agent.proactive import PlanManager, TimeManager
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.tools import ToolRegistry


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 5, 20, 0, tzinfo=ZONE)
NICKNAME = "正在等你说早安"
SIGNATURE = "正在改写现实，先给你开个后门。本账号不支持注销，终身绑定你"


def make_stack(root: Path):
    default_profile = root / "default_user.json"
    default_profile.write_text(
        json.dumps(
            {
                "schema_version": 18,
                "stable": {},
                "dynamic": {
                    "preferred_name": "星",
                    "casual_aliases": ["宝"],
                    "address_style": {"default": "星", "casual": "宝"},
                },
                "metadata": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    identity = AgentIdentityManager(
        path=PROJECT_ROOT / "config" / "default_agent_profile.json"
    )
    profile = UserProfileManager(
        path=root / "profile.json",
        default_path=default_profile,
    )
    memory = ShortTermMemory(path=root / "memory.json")
    rag = JsonlRAGStore(path=root / "rag.jsonl")
    time_manager = TimeManager(
        path=root / "time.json",
        timezone="Asia/Shanghai",
    )
    plan_manager = PlanManager(path=root / "plans.json")
    planner = ConversationPlanner(
        profile=profile,
        memory=memory,
        time_manager=time_manager,
        plan_manager=plan_manager,
        agent_identity=identity,
    )
    executor = ConversationExecutor(
        llm=EchoLLMClient(),
        tool_registry=ToolRegistry(),
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(agent_identity=identity),
        agent_identity=identity,
    )
    return identity, planner, executor


def answer(planner, executor, text: str) -> str:
    plan = planner.plan(text, NOW)
    bundle, _ = executor.execute_json(plan.to_json(), NOW)
    return bundle.joined_text()


def test_dynamic_identity_contains_qq() -> None:
    identity = AgentIdentityManager(
        path=PROJECT_ROOT / "config" / "default_agent_profile.json"
    )
    qq = identity.prompt_view(NOW.date())["qq"]
    assert qq["has_account"] is True
    assert qq["nickname"] == NICKNAME
    assert qq["signature"] == SIGNATURE
    assert qq["account_number"] is None


def test_qq_nickname_and_signature_answers() -> None:
    with tempfile.TemporaryDirectory() as value:
        _identity, planner, executor = make_stack(Path(value))
        assert answer(planner, executor, "你的QQ昵称是什么？") == (
            f"我的 QQ 昵称是“{NICKNAME}”"
        )
        assert answer(planner, executor, "你的QQ个性签名是什么？") == (
            f"我的 QQ 签名是“{SIGNATURE}”"
        )


def test_account_number_is_not_invented() -> None:
    with tempfile.TemporaryDirectory() as value:
        _identity, planner, executor = make_stack(Path(value))
        response = answer(planner, executor, "你的QQ号是多少？")
        assert "不乱猜" in response
        assert NICKNAME in response
        assert "MASTER_QQ" not in response


def test_persona_contains_qq_identity_and_turn_taking() -> None:
    persona = (
        PROJECT_ROOT
        / "config"
        / "persona"
        / "silverwolf_lv18.md"
    ).read_text(encoding="utf-8")
    assert NICKNAME in persona
    assert SIGNATURE in persona
    assert "不是每条用户消息都需要再发送一条回复" in persona
    assert "嗯呢" in persona


def run() -> None:
    test_dynamic_identity_contains_qq()
    test_qq_nickname_and_signature_answers()
    test_account_number_is_not_invented()
    test_persona_contains_qq_identity_and_turn_taking()
    print("lv18_qq_identity_test: OK")


if __name__ == "__main__":
    run()
