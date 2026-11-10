from __future__ import annotations

from datetime import datetime, timedelta
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
from silverwolf_agent.proactive import ProactivePlanner, ProactiveStateStore
from silverwolf_agent.proactive.contracts import RoutineEvent
from silverwolf_agent.world import WeatherSnapshot, WorldContextManager


class FakeGeocoder:
    def geocode(self, query: str):
        return {
            "country": "中国",
            "province": "江苏省",
            "city": "南京市",
            "district": query,
            "display_name": query,
            "query": query,
            "latitude": 32.0,
            "longitude": 118.7,
            "timezone": "Asia/Shanghai",
            "resolved_by": "fake",
        }


class FakeWeatherService:
    def __init__(self, snapshot: WeatherSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def lookup(self, *, now: datetime, force: bool = False):
        self.calls += 1
        return {
            "available": True,
            "cached": self.calls > 1,
            "snapshot": self.snapshot.to_dict(),
            "summary": self.snapshot.natural_brief(),
            "temperature_change_c": None,
            "temperature_change_significant": False,
        }


def make_components(root: Path):
    default_path = root / "default.json"
    shutil.copyfile(PROJECT_ROOT / "config" / "default_user_profile.json", default_path)
    profile = UserProfileManager(path=root / "profile.json", default_path=default_path)
    memory = ShortTermMemory(path=root / "memory.json")
    state = ProactiveStateStore(path=root / "state.json")
    world = WorldContextManager(profile, geocoder=FakeGeocoder())
    return profile, memory, state, world


def rainy_snapshot(now: datetime) -> WeatherSnapshot:
    return WeatherSnapshot(
        location="南京浦口",
        latitude=32.0584,
        longitude=118.6279,
        timezone="Asia/Shanghai",
        fetched_at=now.isoformat(timespec="seconds"),
        forecast_date=now.date().isoformat(),
        condition="中雨",
        weather_code=63,
        temperature_c=21.0,
        apparent_temperature_c=20.0,
        minimum_temperature_c=18.0,
        maximum_temperature_c=24.0,
        precipitation_probability=80,
        precipitation_sum_mm=8.0,
        maximum_wind_kmh=20.0,
        rain_likely=True,
        severe=False,
    )


def routine(key: str, now: datetime) -> RoutineEvent:
    return RoutineEvent(
        key=key,
        scheduled_at=now.isoformat(timespec="seconds"),
        weight=72,
        window_minutes=60,
    )


def test_contextual_morning_and_once_per_day(root: Path) -> None:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # Saturday
    profile, memory, state, world = make_components(root)
    memory.add_turn(
        "NapCat总算跑起来了，昨晚折腾死我了。",
        "跑起来就好。",
        at=now - timedelta(hours=8),
    )
    weather = FakeWeatherService(rainy_snapshot(now))
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        state=state,
        weather_service=weather,
        world_context=world,
    )
    planned = json.loads(
        planner.plan_json(now=now, routines=[routine("morning", now)], due_plans=[])
    )["planned_messages"]
    assert len(planned) == 1
    message = planned[0]
    assert "南京浦口" in message["content"]
    assert "带伞" in message["content"]
    assert "部署后来跑稳" in message["content"]
    assert "周末" in message["content"] or "外面" in message["content"]
    assert message["metadata"]["weather_context_included"] is True
    assert message["metadata"]["memory_callback"]
    assert message["metadata"]["weekend_suggestion"]

    state.mark_weather_sent(now.date().isoformat())
    state.mark_memory_callback_sent(now.date().isoformat())
    state.mark_weekend_suggestion_sent(now.date().isoformat())
    noon = json.loads(
        planner.plan_json(
            now=now.replace(hour=12),
            routines=[routine("noon", now.replace(hour=12))],
            due_plans=[],
        )
    )["planned_messages"]
    assert len(noon) == 1
    assert "weather_context_included" not in noon[0]["metadata"]
    assert "memory_callback" not in noon[0]["metadata"]
    assert "weekend_suggestion" not in noon[0]["metadata"]


def test_quiet_mode_keeps_weather_alert(root: Path) -> None:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    profile, memory, state, world = make_components(root)
    world.set_interaction_preferences(
        {"quiet_until": now.replace(hour=23, minute=59).isoformat(timespec="seconds")}
    )
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        state=state,
        weather_service=FakeWeatherService(rainy_snapshot(now)),
        world_context=world,
    )
    planned = json.loads(
        planner.plan_json(now=now, routines=[routine("morning", now)], due_plans=[])
    )["planned_messages"]
    assert len(planned) == 1
    assert planned[0]["category"] == "weather_alert"
    assert planned[0]["metadata"]["weather_alert_only"] is True
    assert "下雨" in planned[0]["content"]


def test_adaptive_frequency_and_recovery(root: Path) -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    profile, memory, state, world = make_components(root)
    planner = ProactivePlanner(
        profile=profile,
        memory=memory,
        state=state,
        world_context=world,
    )

    state.record_relationship_sent(sent_at=now - timedelta(days=2), expects_reply=True)
    state.record_relationship_sent(sent_at=now - timedelta(days=1), expects_reply=True)
    state.record_relationship_sent(sent_at=now - timedelta(hours=1), expects_reply=True)
    assert state.snapshot()["engagement"]["consecutive_unanswered"] == 2

    planned = json.loads(
        planner.plan_json(now=now, routines=[routine("noon", now)], due_plans=[])
    )["planned_messages"]
    assert planned == []

    state.note_user_activity(now + timedelta(minutes=1))
    assert state.snapshot()["engagement"]["consecutive_unanswered"] == 0
    recovered = json.loads(
        planner.plan_json(
            now=now + timedelta(minutes=2),
            routines=[routine("noon", now + timedelta(minutes=2))],
            due_plans=[],
        )
    )["planned_messages"]
    assert len(recovered) == 1


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_contextual_morning_and_once_per_day(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_quiet_mode_keeps_weather_alert(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_adaptive_frequency_and_recovery(Path(value))
    print("lv17_adaptive_proactive_test: OK")


if __name__ == "__main__":
    run()
