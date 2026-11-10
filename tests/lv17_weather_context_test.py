from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.memory.profile import UserProfileManager
from silverwolf_agent.world import (
    Lv17IntentAnalyzer,
    WeatherService,
    WeatherSnapshot,
    WorldContextManager,
)


class FakeWeatherProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.geocode_calls: list[str] = []
        self.forecast_calls = 0

    def geocode(self, query: str) -> dict[str, object]:
        self.geocode_calls.append(query)
        if self.fail:
            raise RuntimeError("fake geocoding failure")
        names = {
            "南京": ("江苏南京", 32.06, 118.79),
            "杭州": ("浙江杭州", 30.27, 120.15),
            "上海": ("上海", 31.23, 121.47),
            "苏州工业园区": ("江苏苏州工业园区", 31.30, 120.72),
        }
        display, lat, lon = names.get(query, (query, 30.0, 120.0))
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
            "resolved_by": "fake",
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
        self.forecast_calls += 1
        if self.fail:
            raise RuntimeError("fake forecast failure")
        return WeatherSnapshot(
            location=display_name,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            fetched_at=now.isoformat(timespec="seconds"),
            forecast_date=now.date().isoformat(),
            condition="小雨",
            weather_code=61,
            temperature_c=19.0,
            apparent_temperature_c=18.0,
            minimum_temperature_c=16.0,
            maximum_temperature_c=22.0,
            precipitation_probability=70,
            precipitation_sum_mm=3.2,
            maximum_wind_kmh=18.0,
            rain_likely=True,
            severe=False,
        )


def make_profile(root: Path) -> UserProfileManager:
    default_path = root / "default_user_profile.json"
    shutil.copyfile(PROJECT_ROOT / "config" / "default_user_profile.json", default_path)
    return UserProfileManager(
        path=root / "user_profile.json",
        default_path=default_path,
    )


def test_default_pukou_and_cache(root: Path) -> None:
    profile = make_profile(root)
    provider = FakeWeatherProvider()
    context = WorldContextManager(profile, geocoder=provider)
    now = datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    location = context.active_location(now)
    assert location["display_name"] == "南京浦口"
    assert location["source"] == "home"

    service = WeatherService(
        context_manager=context,
        provider=provider,
        cache_path=root / "weather_cache.json",
        cache_minutes=30,
    )
    first = service.lookup(now=now)
    second = service.lookup(now=now + timedelta(minutes=5))
    assert first["available"] is True
    assert second["available"] is True
    assert second["cached"] is True
    assert provider.forecast_calls == 1
    assert "南京浦口" in first["summary"]
    assert "带伞" in first["summary"]


def test_location_updates_and_expiry(root: Path) -> None:
    profile = make_profile(root)
    provider = FakeWeatherProvider()
    context = WorldContextManager(profile, geocoder=provider)
    now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    # 浦口别名使用内置安全坐标，不依赖外部地理编码。
    home = context.set_home_location("浦口")
    assert home["display_name"] == "南京浦口"
    assert provider.geocode_calls == []

    temporary = context.set_temporary_location(
        "上海",
        starts_at=now.isoformat(timespec="seconds"),
        ends_at=(now + timedelta(days=2)).isoformat(timespec="seconds"),
    )
    assert temporary["display_name"] == "上海"
    assert context.active_location(now + timedelta(hours=1))["source"] == "temporary"
    assert context.active_location(now + timedelta(days=3))["source"] == "home"
    assert profile.load()["dynamic"]["world_context"]["temporary_location"] is None


def test_weather_failure_is_explicit(root: Path) -> None:
    profile = make_profile(root)
    context = WorldContextManager(profile, geocoder=FakeWeatherProvider())
    service = WeatherService(
        context_manager=context,
        provider=FakeWeatherProvider(fail=True),
        cache_path=root / "weather_cache.json",
    )
    result = service.lookup(
        now=datetime(2026, 8, 5, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert result["available"] is False
    assert "fake forecast failure" in result["error"]
    assert "temperature" not in result


def test_natural_language_location_intents() -> None:
    analyzer = Lv17IntentAnalyzer()
    now = datetime(2026, 8, 5, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    intents = analyzer.analyze(
        "我最近住南京，不过下周一到周三去杭州，那几天帮我留意杭州会不会下雨，回来以后还是看南京。",
        now,
    )
    kinds = [intent.kind for intent in intents]
    assert "set_home_location" in kinds
    assert "set_temporary_location" in kinds
    assert "weather_lookup" not in kinds
    home = next(item for item in intents if item.kind == "set_home_location")
    temporary = next(item for item in intents if item.kind == "set_temporary_location")
    assert home.arguments["query"] == "南京"
    assert temporary.arguments["query"] == "杭州"
    assert temporary.arguments["starts_at"].startswith("2026-08-10")
    assert temporary.arguments["ends_at"].startswith("2026-08-12")

    preference = analyzer.analyze("天气不用每天说了，下雨再提醒我。", now)
    assert preference[0].kind == "set_weather_preferences"
    assert preference[0].arguments["updates"]["daily_brief_enabled"] is False
    assert preference[0].arguments["updates"]["rain_alerts"] is True


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        test_default_pukou_and_cache(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_location_updates_and_expiry(Path(value))
    with tempfile.TemporaryDirectory() as value:
        test_weather_failure_is_explicit(Path(value))
    test_natural_language_location_intents()
    print("lv17_weather_context_test: OK")


if __name__ == "__main__":
    run()
