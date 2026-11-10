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

from silverwolf_agent.llm.echo import EchoLLMClient
from silverwolf_agent.memory import AgentIdentityManager, JsonlRAGStore, ShortTermMemory, UserProfileManager
from silverwolf_agent.pae import ConversationExecutor, ConversationPlanner
from silverwolf_agent.proactive import PlanManager, TimeManager
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.tools import (
    EventFollowUpCreateTool,
    InteractionPreferencesSetTool,
    PlanCancelTool,
    PlanCreateTool,
    PlanListTool,
    TimePreferencesGetTool,
    TimePreferencesSetTool,
    ToolRegistry,
    WeatherLookupTool,
    WorldContextUpdateTool,
)
from silverwolf_agent.world import (
    Lv17IntentAnalyzer,
    WeatherService,
    WeatherSnapshot,
    WorldContextManager,
)


class DialogueWeatherProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def geocode(self, query: str):
        if self.fail:
            raise RuntimeError("地理编码暂时不可用")
        locations = {
            "南京": ("江苏南京", 32.06, 118.79),
            "杭州": ("浙江杭州", 30.27, 120.15),
            "上海": ("上海", 31.23, 121.47),
            "苏州工业园区": ("江苏苏州工业园区", 31.30, 120.72),
        }
        display, lat, lon = locations.get(query, (query, 30.0, 120.0))
        return {
            "country": "中国",
            "province": "测试省",
            "city": "测试市",
            "district": query,
            "display_name": display,
            "query": query,
            "latitude": lat,
            "longitude": lon,
            "timezone": "Asia/Shanghai",
            "resolved_by": "dialogue-fake",
        }

    def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str,
        display_name: str,
        now: datetime,
    ) -> WeatherSnapshot:
        if self.fail:
            raise RuntimeError("天气服务暂时不可用")
        return WeatherSnapshot(
            location=display_name,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            fetched_at=now.isoformat(timespec="seconds"),
            forecast_date=now.date().isoformat(),
            condition="阵雨",
            weather_code=80,
            temperature_c=25.0,
            apparent_temperature_c=26.0,
            minimum_temperature_c=22.0,
            maximum_temperature_c=29.0,
            precipitation_probability=75,
            precipitation_sum_mm=4.0,
            maximum_wind_kmh=22.0,
            rain_likely=True,
            severe=False,
        )


class DialogueHarness:
    def __init__(self, root: Path, *, weather_fail: bool = False) -> None:
        default_path = root / "default_profile.json"
        shutil.copyfile(PROJECT_ROOT / "config" / "default_user_profile.json", default_path)
        self.profile = UserProfileManager(path=root / "profile.json", default_path=default_path)
        self.memory = ShortTermMemory(path=root / "memory.json")
        self.rag = JsonlRAGStore(path=root / "rag.jsonl")
        self.plan_manager = PlanManager(path=root / "plans.json")
        self.time_manager = TimeManager(path=root / "time.json", timezone="Asia/Shanghai")
        self.provider = DialogueWeatherProvider(fail=weather_fail)
        self.world = WorldContextManager(self.profile, geocoder=self.provider)
        self.weather = WeatherService(
            context_manager=self.world,
            provider=self.provider,
            cache_path=root / "weather_cache.json",
        )
        self.now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.registry = ToolRegistry()
        self.registry.register(WorldContextUpdateTool(self.world))
        self.registry.register(WeatherLookupTool(self.weather, lambda: self.now))
        self.registry.register(InteractionPreferencesSetTool(self.world, self.plan_manager))
        self.registry.register(EventFollowUpCreateTool(self.plan_manager))
        self.registry.register(PlanCancelTool(self.plan_manager))
        self.registry.register(PlanCreateTool(self.plan_manager))
        self.registry.register(PlanListTool(self.plan_manager))
        self.registry.register(TimePreferencesGetTool(self.time_manager))
        self.registry.register(TimePreferencesSetTool(self.time_manager))

        identity = AgentIdentityManager()
        self.planner = ConversationPlanner(
            profile=self.profile,
            memory=self.memory,
            time_manager=self.time_manager,
            plan_manager=self.plan_manager,
            agent_identity=identity,
            lv17_intent_analyzer=Lv17IntentAnalyzer(),
            world_context=self.world,
        )
        self.executor = ConversationExecutor(
            llm=EchoLLMClient(),
            tool_registry=self.registry,
            profile=self.profile,
            memory=self.memory,
            rag=self.rag,
            prompt_builder=PromptBuilder(agent_identity=identity),
            agent_identity=identity,
        )

    def say(self, text: str) -> str:
        plan_json = self.planner.plan_json(text, self.now)
        bundle, _packet = self.executor.execute_json(plan_json, self.now)
        response = "\n".join(item.content for item in bundle.selected_messages())
        self.memory.add_turn(text, response, at=self.now)
        return response


def test_natural_dialogue_controls(root: Path) -> None:
    h = DialogueHarness(root)

    weather = h.say("今天出门需要带伞吗？")
    assert "南京浦口" in weather
    assert "带伞" in weather
    assert "窗外" not in weather
    assert "检测到" not in weather

    home = h.say("以后看浦口天气。")
    assert "以后就看南京浦口" in home
    assert "配置" not in home

    temporary = h.say("我这周在上海出差，天气先看上海的。")
    assert "先看上海" in temporary
    assert "自动回到" in temporary
    assert h.world.active_location(h.now)["source"] == "temporary"

    restored = h.say("我回南京了。")
    assert "继续看南京浦口" in restored
    assert h.world.active_location(h.now)["source"] == "home"

    weather_pref = h.say("天气不用每天说了，下雨再提醒我。")
    assert "不每天" in weather_pref
    assert "下雨" in weather_pref

    quiet = h.say("今天别主动找我。")
    assert "不主动打扰" in quiet

    event = h.say("我今天下午三点有面试。")
    assert "等你忙完" in event
    assert "面试" in event
    assert "提醒已创建" not in event

    cancelled = h.say("面试的事情别再问了。")
    assert "不再主动" in cancelled
    assert not any(
        plan.metadata.get("kind") == "relationship_event_follow_up"
        for plan in h.plan_manager.list_plans(active_only=True)
    )


def test_complex_location_dialogue(root: Path) -> None:
    h = DialogueHarness(root)
    response = h.say(
        "我最近住南京，不过下周一到周三去杭州，那几天帮我留意杭州会不会下雨，回来以后还是看南京。"
    )
    assert "以后就看江苏南京" in response
    assert "先看浙江杭州" in response
    profile = h.profile.load()["dynamic"]["world_context"]
    assert profile["home_location"]["display_name"] == "江苏南京"
    assert profile["temporary_location"]["display_name"] == "浙江杭州"
    assert profile["temporary_location"]["ends_at"].startswith("2026-08-12")


def test_weather_failure_dialogue(root: Path) -> None:
    h = DialogueHarness(root, weather_fail=True)
    response = h.say("今天会不会下雨？")
    assert "拿不到可靠结果" in response
    assert "先不乱猜" in response
    assert "℃" not in response
    assert "%" not in response


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_natural_dialogue_controls(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_complex_location_dialogue(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_weather_failure_dialogue(Path(value))
    print("lv17_natural_dialogue_test: OK")


if __name__ == "__main__":
    run()
