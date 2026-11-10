from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from ..memory.profile import UserProfileManager
from .weather import OpenMeteoWeatherProvider, WeatherProvider


DEFAULT_HOME_LOCATION: dict[str, Any] = {
    "country": "中国",
    "province": "江苏省",
    "city": "南京市",
    "district": "浦口区",
    "display_name": "南京浦口",
    "query": "江苏省南京市浦口区",
    "latitude": 32.0584,
    "longitude": 118.6279,
    "timezone": "Asia/Shanghai",
    "resolved_by": "built-in-default",
}

DEFAULT_WEATHER_PREFERENCES: dict[str, Any] = {
    "enabled": True,
    "daily_brief_enabled": True,
    "severe_weather_alerts": True,
    "rain_alerts": True,
    "temperature_change_alerts": True,
    "mention_in_morning_message": True,
    "max_proactive_weather_messages_per_day": 1,
}

DEFAULT_INTERACTION_PREFERENCES: dict[str, Any] = {
    "event_follow_up_enabled": True,
    "memory_callback_enabled": True,
    "adaptive_proactive_frequency": True,
    "weekend_suggestions_enabled": True,
    "proactive_frequency_mode": "normal",
    "proactive_frequency_until": None,
    "quiet_until": None,
}


class WorldContextManager:
    def __init__(
        self,
        profile: UserProfileManager,
        *,
        geocoder: WeatherProvider | None = None,
    ) -> None:
        self.profile = profile
        self.geocoder = geocoder or OpenMeteoWeatherProvider()
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        profile = self.profile.load()
        dynamic = profile.setdefault("dynamic", {})
        changed = False
        world = dynamic.setdefault("world_context", {})
        if not isinstance(world.get("home_location"), dict):
            world["home_location"] = deepcopy(DEFAULT_HOME_LOCATION)
            changed = True
        if "temporary_location" not in world:
            world["temporary_location"] = None
            changed = True
        weather = dynamic.setdefault("weather_preferences", {})
        for key, value in DEFAULT_WEATHER_PREFERENCES.items():
            if key not in weather:
                weather[key] = deepcopy(value)
                changed = True
        interaction = dynamic.setdefault("interaction_preferences", {})
        for key, value in DEFAULT_INTERACTION_PREFERENCES.items():
            if key not in interaction:
                interaction[key] = deepcopy(value)
                changed = True
        if changed:
            self.profile.save(profile, reason="automatic_lv17_world_context_migration")

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        self.ensure_defaults()
        current = now or datetime.now().astimezone()
        return {
            "active_location": self.active_location(current),
            "world_context": deepcopy(
                self.profile.load().get("dynamic", {}).get("world_context", {})
            ),
            "weather_preferences": self.weather_preferences(),
            "interaction_preferences": self.interaction_preferences(current),
        }

    def active_location(self, now: datetime) -> dict[str, Any]:
        self.ensure_defaults()
        world = self.profile.load().get("dynamic", {}).get("world_context", {})
        temporary = world.get("temporary_location")
        if isinstance(temporary, dict) and self._temporary_active(temporary, now):
            result = deepcopy(temporary)
            result["source"] = "temporary"
            return result
        if isinstance(temporary, dict):
            # 临时地点过期后自动清理，避免档案里长期留着失效行程。
            profile = self.profile.load()
            profile.setdefault("dynamic", {}).setdefault("world_context", {})[
                "temporary_location"
            ] = None
            self.profile.save(profile, reason="automatic_expired_temporary_location")
        result = deepcopy(world.get("home_location") or DEFAULT_HOME_LOCATION)
        result["source"] = "home"
        return result

    @staticmethod
    def _temporary_active(location: dict[str, Any], now: datetime) -> bool:
        try:
            starts = datetime.fromisoformat(str(location.get("starts_at")))
            ends = datetime.fromisoformat(str(location.get("ends_at")))
        except (TypeError, ValueError):
            return False
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=now.tzinfo)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=now.tzinfo)
        return starts <= now <= ends

    def ensure_resolved(self, location: dict[str, Any]) -> dict[str, Any]:
        if location.get("latitude") is not None and location.get("longitude") is not None:
            return location
        resolved = self._resolve_query(
            str(location.get("query") or location.get("display_name"))
        )
        source = str(location.get("source", "home"))
        if source == "temporary":
            self._replace_location("temporary_location", {**location, **resolved})
        else:
            self._replace_location("home_location", {**location, **resolved})
        result = {**location, **resolved, "source": source}
        return result


    def _resolve_query(self, query: str) -> dict[str, Any]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("地点不能为空")
        compact = cleaned.replace("中国", "").replace("江苏省", "江苏")
        if "浦口" in compact and ("南京" in compact or compact in {"浦口", "浦口区"}):
            result = deepcopy(DEFAULT_HOME_LOCATION)
            result["query"] = cleaned
            result["resolved_by"] = "built-in-pukou-alias"
            return result
        return self.geocoder.geocode(cleaned)

    def set_home_location(self, query: str) -> dict[str, Any]:
        resolved = self._resolve_query(query)
        self._replace_location("home_location", resolved)
        return deepcopy(resolved)

    def set_temporary_location(
        self,
        query: str,
        *,
        starts_at: str,
        ends_at: str,
    ) -> dict[str, Any]:
        start = datetime.fromisoformat(starts_at)
        end = datetime.fromisoformat(ends_at)
        if end <= start:
            raise ValueError("临时地点结束时间必须晚于开始时间")
        resolved = self._resolve_query(query)
        resolved.update({"starts_at": starts_at, "ends_at": ends_at})
        self._replace_location("temporary_location", resolved)
        return deepcopy(resolved)

    def clear_temporary_location(self) -> dict[str, Any]:
        profile = self.profile.load()
        world = profile.setdefault("dynamic", {}).setdefault("world_context", {})
        previous = world.get("temporary_location")
        world["temporary_location"] = None
        self.profile.save(profile, reason="user_cleared_temporary_location")
        return {"cleared": previous is not None, "home_location": world.get("home_location")}

    def _replace_location(self, key: str, value: dict[str, Any]) -> None:
        profile = self.profile.load()
        world = profile.setdefault("dynamic", {}).setdefault("world_context", {})
        world[key] = deepcopy(value)
        self.profile.save(profile, reason=f"user_updated_{key}")

    def weather_preferences(self) -> dict[str, Any]:
        self.ensure_defaults()
        return deepcopy(
            self.profile.load().get("dynamic", {}).get("weather_preferences", {})
        )

    def set_weather_preferences(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_WEATHER_PREFERENCES)
        profile = self.profile.load()
        prefs = profile.setdefault("dynamic", {}).setdefault("weather_preferences", {})
        for key, value in updates.items():
            if key not in allowed:
                raise ValueError(f"未知天气偏好：{key}")
            prefs[key] = value
        self.profile.save(profile, reason="user_updated_weather_preferences")
        return deepcopy(prefs)

    def interaction_preferences(self, now: datetime | None = None) -> dict[str, Any]:
        self.ensure_defaults()
        prefs = deepcopy(
            self.profile.load().get("dynamic", {}).get("interaction_preferences", {})
        )
        current = now or datetime.now().astimezone()
        until_raw = prefs.get("proactive_frequency_until")
        if until_raw:
            try:
                until = datetime.fromisoformat(str(until_raw))
                if until.tzinfo is None:
                    until = until.replace(tzinfo=current.tzinfo)
                if current > until:
                    prefs["proactive_frequency_mode"] = "normal"
                    prefs["proactive_frequency_until"] = None
                    profile = self.profile.load()
                    stored = profile.setdefault("dynamic", {}).setdefault(
                        "interaction_preferences", {}
                    )
                    stored["proactive_frequency_mode"] = "normal"
                    stored["proactive_frequency_until"] = None
                    self.profile.save(
                        profile,
                        reason="automatic_expired_proactive_frequency",
                    )
            except ValueError:
                prefs["proactive_frequency_until"] = None
        return prefs

    def set_interaction_preferences(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_INTERACTION_PREFERENCES)
        profile = self.profile.load()
        prefs = profile.setdefault("dynamic", {}).setdefault("interaction_preferences", {})
        for key, value in updates.items():
            if key not in allowed:
                raise ValueError(f"未知互动偏好：{key}")
            if key == "proactive_frequency_mode" and value not in {"low", "normal", "high"}:
                raise ValueError("主动频率必须是 low、normal 或 high")
            prefs[key] = value
        self.profile.save(profile, reason="user_updated_interaction_preferences")
        return deepcopy(prefs)
