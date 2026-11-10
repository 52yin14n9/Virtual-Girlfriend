from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.memory.profile import UserProfileManager
from silverwolf_agent.memory.short_term import ShortTermMemory
from silverwolf_agent.proactive import PlanManager, ProactivePlanner, ProactiveStateStore
from silverwolf_agent.tools.plan_tools import PlanCancelTool
from silverwolf_agent.tools.world_tools import (
    EventFollowUpCreateTool,
    InteractionPreferencesSetTool,
)
from silverwolf_agent.world import Lv17IntentAnalyzer, WorldContextManager


class FakeGeocoder:
    def geocode(self, query: str):
        return {
            "country": "中国",
            "province": "测试省",
            "city": "测试市",
            "district": query,
            "display_name": query,
            "query": query,
            "latitude": 30.0,
            "longitude": 120.0,
            "timezone": "Asia/Shanghai",
            "resolved_by": "fake",
        }


def make_profile(root: Path) -> UserProfileManager:
    default_path = root / "default.json"
    shutil.copyfile(PROJECT_ROOT / "config" / "default_user_profile.json", default_path)
    return UserProfileManager(path=root / "profile.json", default_path=default_path)


def test_event_detection_and_creation(root: Path) -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    analyzer = Lv17IntentAnalyzer()
    intents = analyzer.analyze("我今天下午三点有面试。", now)
    event = next(item for item in intents if item.kind == "create_event_follow_up")
    assert event.arguments["event_label"] == "面试"
    assert event.arguments["due_at"].startswith("2026-08-05T17:00:00")
    assert event.arguments["explicit_request"] is False

    manager = PlanManager(path=root / "plans.json")
    result = EventFollowUpCreateTool(manager).run(dict(event.arguments))
    assert result.ok is True
    active = manager.list_plans(active_only=True)
    assert len(active) == 1
    assert active[0].metadata["kind"] == "relationship_event_follow_up"
    assert active[0].metadata["no_secondary_follow_up"] is True

    profile = make_profile(root)
    memory = ShortTermMemory(path=root / "memory.json")
    state = ProactiveStateStore(path=root / "state.json")
    planner = ProactivePlanner(profile=profile, memory=memory, state=state)
    plan_json = planner.plan_json(
        now=datetime(2026, 8, 5, 17, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        routines=[],
        due_plans=active,
    )
    planned = json.loads(plan_json)["planned_messages"]
    assert len(planned) == 1
    assert planned[0]["category"] == "relationship_event_follow_up"
    assert planned[0]["metadata"]["no_secondary_follow_up"] is True
    assert "面试" in planned[0]["content"]
    assert "感觉怎么样" in planned[0]["content"]


def test_explicit_follow_up_and_past_event() -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    analyzer = Lv17IntentAnalyzer()
    explicit = analyzer.analyze("面试结束后问问我。", now)
    event = next(item for item in explicit if item.kind == "create_event_follow_up")
    assert event.arguments["explicit_request"] is True

    past = analyzer.analyze("我刚刚面试完了。", now)
    assert all(item.kind != "create_event_follow_up" for item in past)


def test_cancel_and_global_disable(root: Path) -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    analyzer = Lv17IntentAnalyzer()
    event = next(
        item
        for item in analyzer.analyze("我下午三点有面试。", now)
        if item.kind == "create_event_follow_up"
    )
    manager = PlanManager(path=root / "plans.json")
    EventFollowUpCreateTool(manager).run(dict(event.arguments))

    cancel_intent = analyzer.analyze("面试的事情别再问了。", now)
    assert cancel_intent[0].kind == "cancel_event_follow_up"
    cancelled = PlanCancelTool(manager).run({"query": "面试"})
    assert cancelled.ok is True
    assert len(cancelled.content["cancelled"]) == 1
    assert manager.list_plans(active_only=True) == []

    EventFollowUpCreateTool(manager).run(dict(event.arguments))
    profile = make_profile(root)
    world = WorldContextManager(profile, geocoder=FakeGeocoder())
    setting = InteractionPreferencesSetTool(world, manager).run(
        {"updates": {"event_follow_up_enabled": False}}
    )
    assert setting.ok is True
    assert setting.content["cancelled_event_follow_ups"]
    assert manager.list_plans(active_only=True) == []


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_event_detection_and_creation(Path(value))
    test_explicit_follow_up_and_past_event()
    with tempfile.TemporaryDirectory() as value:
        test_cancel_and_global_disable(Path(value))
    print("lv17_event_follow_up_test: OK")


if __name__ == "__main__":
    run()
