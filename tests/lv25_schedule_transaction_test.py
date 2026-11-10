from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.llm.base import BaseLLMClient
from silverwolf_agent.memory import (
    AgentIdentityManager,
    JsonlRAGStore,
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.models import LLMResponse
from silverwolf_agent.pae import ConversationExecutor, ConversationPlanner
from silverwolf_agent.pae.schedule_judge import ModelScheduleJudgement
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_PATH
from silverwolf_agent.proactive import PlanManager, TimeManager
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.tools import PlanCreateTool, ToolRegistry


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 19, 14, 33, 16, tzinfo=ZONE)


class MustNotRunLLM(BaseLLMClient):
    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        raise AssertionError("schedule transaction should not call the chat LLM")


class GenericTitleScheduleJudge:
    def judge(self, **kwargs) -> ModelScheduleJudgement:
        return ModelScheduleJudgement(
            consulted=True,
            accepted=True,
            action="create_plan",
            confidence=0.99,
            reason="用户明确要求晚上主动敲一下",
            source="model",
            title="主动联系星",
            due_at="2026-08-19T17:40:00+08:00",
            recurrence="none",
            importance=100,
        )


class Harness:
    def __init__(self, root: Path, *, schedule_judge=None) -> None:
        root.mkdir(parents=True, exist_ok=True)
        default_profile = root / "default_user_profile.json"
        default_agent = root / "default_agent_profile.json"
        shutil.copy2(PROJECT_ROOT / "config" / "default_user_profile.json", default_profile)
        shutil.copy2(PROJECT_ROOT / "config" / "default_agent_profile.json", default_agent)

        self.profile = UserProfileManager(
            path=root / "user_profile.json",
            default_path=default_profile,
        )
        self.memory = ShortTermMemory(path=root / "short_term.json")
        self.rag = JsonlRAGStore(path=root / "rag.jsonl")
        self.identity = AgentIdentityManager(path=default_agent)
        self.time_manager = TimeManager(
            path=root / "time_preferences.json",
            timezone="Asia/Shanghai",
        )
        self.time_manager.set_slot("evening", "17:40")
        self.plan_manager = PlanManager(path=root / "plans.json")

        self.planner = ConversationPlanner(
            profile=self.profile,
            memory=self.memory,
            time_manager=self.time_manager,
            plan_manager=self.plan_manager,
            message_gap_seconds=0.0,
            agent_identity=self.identity,
            schedule_judge=schedule_judge,
        )

        registry = ToolRegistry()
        registry.register(PlanCreateTool(self.plan_manager))
        self.executor = ConversationExecutor(
            llm=MustNotRunLLM(),
            tool_registry=registry,
            profile=self.profile,
            memory=self.memory,
            rag=self.rag,
            prompt_builder=PromptBuilder(agent_identity=self.identity),
            agent_identity=self.identity,
        )

    def say(self, text: str):
        plan = self.planner.plan(text, NOW)
        bundle, _ = self.executor.execute_json(plan.to_json(), NOW)
        return plan, bundle


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    # Lv30: 人设已拆成核心 + 世界书模块，断言改为在「整份人设」上检查
    persona = PersonaLibrary().full_text()
    assert "日程创建确认只说一次" in persona
    assert "别让快递等你" in persona


def test_forgotten_parcel_becomes_real_action_and_single_reply(root: Path) -> None:
    h = Harness(root)
    text = "我忘记取快递了，晚上提醒我吃饭的时候再敲我一下喵"
    plan, bundle = h.say(text)

    decision = plan.metadata["schedule_decision"]
    assert decision["title"] == "取快递"
    assert decision["due_at"] == "2026-08-19T17:40:00+08:00"
    assert plan.metadata["user_state_facts"] == []
    assert [goal.kind for goal in plan.response_goals] == ["confirm_schedule"]
    assert plan.render_mode == "local"
    assert plan.delivery_policy.maximum_messages == 1

    selected = bundle.selected_messages()
    assert len(selected) == 1
    assert bundle.joined_text() == "好，今天 17:40 我敲你一下，记得取快递"
    for phrase in (
        "过夜",
        "快递等你",
        "等你太久",
        "我会在那时提醒你",
        "顺便看看晚饭",
    ):
        assert phrase not in bundle.joined_text()

    active = h.plan_manager.list_plans(active_only=True)
    assert len(active) == 1
    assert active[0].title == "取快递"


def test_generic_model_title_cannot_erase_concrete_rule_action(root: Path) -> None:
    h = Harness(root, schedule_judge=GenericTitleScheduleJudge())
    plan, bundle = h.say(
        "我忘记取快递了，晚上提醒我吃饭的时候再敲我一下喵"
    )
    assert plan.metadata["schedule_decision"]["title"] == "取快递"
    assert plan.metadata["user_state_facts"] == []
    assert len(bundle.selected_messages()) == 1
    assert "取快递" in bundle.joined_text()


def test_independent_state_is_kept_but_coalesced_into_one_message(root: Path) -> None:
    h = Harness(root)
    plan, bundle = h.say("我今天有点头疼，晚上提醒我吃药")

    assert plan.metadata["schedule_decision"]["title"] == "吃药"
    assert plan.metadata["user_state_facts"] == ["我今天有点头疼"]
    assert {goal.kind for goal in plan.response_goals} == {
        "acknowledge_user_state",
        "confirm_schedule",
    }
    selected = bundle.selected_messages()
    assert len(selected) == 1
    text = bundle.joined_text()
    assert "头疼" not in text or "不舒服" in text
    assert "吃药" in text
    assert "17:40" in text


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        test_version_and_persona()
        test_forgotten_parcel_becomes_real_action_and_single_reply(root / "rule")
        test_generic_model_title_cannot_erase_concrete_rule_action(root / "model")
        test_independent_state_is_kept_but_coalesced_into_one_message(root / "state")
    print("lv25_schedule_transaction_test: OK")


if __name__ == "__main__":
    run()
