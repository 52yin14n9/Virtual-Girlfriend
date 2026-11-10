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

from silverwolf_agent.llm import EchoLLMClient
from silverwolf_agent.memory import (
    AgentIdentityManager,
    JsonlRAGStore,
    ShortTermMemory,
    UserProfileManager,
)
from silverwolf_agent.pae import ConversationExecutor, ConversationPlanner
from silverwolf_agent.proactive import PlanManager, TimeManager
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.temporal import TemporalQueryAnalyzer
from silverwolf_agent.tools import (
    CalendarQueryTool,
    CurrentTimeTool,
    ToolRegistry,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 5, 11, 26, 44, tzinfo=ZONE)


class Harness:
    def __init__(self, root: Path) -> None:
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
        self.plan_manager = PlanManager(path=root / "plans.json")

        self.planner = ConversationPlanner(
            profile=self.profile,
            memory=self.memory,
            time_manager=self.time_manager,
            plan_manager=self.plan_manager,
            message_gap_seconds=0.0,
            agent_identity=self.identity,
        )

        registry = ToolRegistry()
        registry.register(CurrentTimeTool(
            timezone="Asia/Shanghai",
            now_provider=lambda: NOW,
        ))
        registry.register(CalendarQueryTool())
        self.executor = ConversationExecutor(
            llm=EchoLLMClient(),
            tool_registry=registry,
            profile=self.profile,
            memory=self.memory,
            rag=self.rag,
            prompt_builder=PromptBuilder(agent_identity=self.identity),
            agent_identity=self.identity,
        )

    def say(self, text: str) -> tuple[str, object]:
        plan = self.planner.plan(text, NOW)
        bundle, _ = self.executor.execute_json(plan.to_json(), NOW)
        return bundle.joined_text(), plan


def test_reported_bug_is_fixed(root: Path) -> None:
    h = Harness(root)

    today, plan = h.say("今天星期几啊")
    assert today == "今天是星期三"
    assert [goal.kind for goal in plan.response_goals] == [
        "answer_calendar_query"
    ]
    assert plan.tool_requests[0].name == "calendar_query"

    tomorrow, plan = h.say("明天星期几啊")
    assert tomorrow == "明天是星期四"
    assert "这次" not in tomorrow
    assert "11:26" not in tomorrow
    assert plan.metadata["temporal_query"]["target_date"] == "2026-08-06"


def test_clock_and_calendar_are_separate(root: Path) -> None:
    h = Harness(root)
    clock, plan = h.say("现在几点了")
    assert clock == "现在 11:26"
    assert [goal.kind for goal in plan.response_goals] == [
        "answer_current_time"
    ]

    date_text, _ = h.say("今天几号")
    assert date_text == "今天是8月5日"

    both, _ = h.say("今天是几号，星期几？")
    assert both == "今天是8月5日，星期三"


def test_relative_and_explicit_dates(root: Path) -> None:
    h = Harness(root)
    cases = {
        "昨天星期几": "昨天是星期二",
        "后天星期几": "后天是星期五",
        "大后天星期几": "大后天是星期六",
        "下周一是几号": "下周一是8月10日",
        "8月10号星期几": "8月10日是星期一",
        "2026年8月10日星期几": "2026年8月10日是星期一",
    }
    for question, expected in cases.items():
        actual, _ = h.say(question)
        assert actual == expected, (question, actual)


def test_invalid_date_does_not_guess() -> None:
    query = TemporalQueryAnalyzer.analyze("2月30号星期几", NOW)
    assert query is None


def test_personal_dates_are_not_mistaken_for_today() -> None:
    assert TemporalQueryAnalyzer.analyze("你生日是哪天？", NOW) is None
    assert TemporalQueryAnalyzer.analyze("你的生日是几号？", NOW) is None


def test_mixed_state_and_weekday_keeps_both_goals(root: Path) -> None:
    h = Harness(root)
    response, plan = h.say("今天中午睡得不错，对了今天星期几啊")
    kinds = {goal.kind for goal in plan.response_goals}
    assert "acknowledge_user_state" in kinds
    assert "answer_calendar_query" in kinds
    assert "星期三" in response
    assert "11:26" not in response


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        test_reported_bug_is_fixed(root / "reported")
        test_clock_and_calendar_are_separate(root / "separate")
        test_relative_and_explicit_dates(root / "relative")
        test_invalid_date_does_not_guess()
        test_personal_dates_are_not_mistaken_for_today()
        test_mixed_state_and_weekday_keeps_both_goals(root / "mixed")
    print("lv19_temporal_query_test: OK")


if __name__ == "__main__":
    run()
