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
    PlanCreateTool,
    ToolRegistry,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 7, 1, 34, 3, tzinfo=ZONE)


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
        registry.register(PlanCreateTool(self.plan_manager))
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


def test_clock_tool_only_handles_current_clock_questions(root: Path) -> None:
    h = Harness(root)

    knowledge_questions = [
        "正常来说的话，早睡早起的标准是几点睡几点起啊",
        "你一般几点睡",
        "晚饭几点吃比较好",
        "明天几点出发比较合适",
        "十一点半睡算早睡吗",
    ]
    for text in knowledge_questions:
        assert TemporalQueryAnalyzer.analyze(text, NOW) is None, text
        plan = h.planner.plan(text, NOW)
        assert not any(
            request.name == "time_now"
            for request in plan.tool_requests
        ), text
        assert "answer_current_time" not in {
            goal.kind
            for goal in plan.response_goals
        }, text

    current_time_questions = [
        "现在几点了",
        "几点了",
        "你看看几点了",
        "对了，现在几点呀",
    ]
    for text in current_time_questions:
        query = TemporalQueryAnalyzer.analyze(text, NOW)
        assert query is not None and query.kind == "time", text
        plan = h.planner.plan(text, NOW)
        assert any(
            request.name == "time_now"
            for request in plan.tool_requests
        ), text


def test_mixed_current_time_clause_still_works(root: Path) -> None:
    h = Harness(root)
    response, plan = h.say("你看看几点了，我已经吃过了，都睡好午觉啦")
    assert any(
        request.name == "time_now"
        for request in plan.tool_requests
    )
    assert "01:34" in response
    assert "吃过饭" in response
    assert "午觉" in response


def test_bedtime_request_becomes_daily_2330_plan(root: Path) -> None:
    h = Harness(root)
    response, plan = h.say("那以后你11点半叫我睡觉好不好")

    decision = plan.metadata["schedule_decision"]
    assert decision["should_persist"] is True
    assert decision["title"] == "睡觉"
    assert decision["recurrence"] == "daily"
    due = datetime.fromisoformat(decision["due_at"])
    assert due.strftime("%Y-%m-%d %H:%M") == "2026-08-07 23:30"

    assert response == (
        "好啊，以后每天 23:30 我叫你睡觉。"
        "到点就别再偷偷熬夜了"
    )
    assert "记住了。" not in response
    assert "今天 23:30" not in response
    assert "提醒你提醒睡觉" not in response
    assert "提醒你一下" not in response

    active = h.plan_manager.list_plans(active_only=True)
    assert len(active) == 1
    assert active[0].title == "睡觉"
    assert active[0].recurrence == "daily"


def test_schedule_confirmation_cleans_redundant_reminder_title(root: Path) -> None:
    h = Harness(root)
    # Simulate a model-produced title that redundantly contains "提醒".
    plan = h.planner.plan("明天早上8点提醒我提醒睡觉", NOW)
    for request in plan.tool_requests:
        if request.name == "plan_create":
            request.arguments["title"] = "提醒睡觉"
    bundle, _ = h.executor.execute_json(plan.to_json(), NOW)
    response = bundle.joined_text()
    assert "提醒你提醒睡觉" not in response
    assert "提醒你一下" not in response
    assert "我来喊你睡觉" in response


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        test_clock_tool_only_handles_current_clock_questions(root / "clock")
        test_mixed_current_time_clause_still_works(root / "mixed")
        test_bedtime_request_becomes_daily_2330_plan(root / "bedtime")
        test_schedule_confirmation_cleans_redundant_reminder_title(root / "clean")
    print("lv20_time_intent_and_schedule_reply_test: OK")


if __name__ == "__main__":
    run()
