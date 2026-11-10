from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import threading
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..paths import WEATHER_CACHE_PATH, ensure_directories


WMO_CONDITIONS: dict[int, str] = {
    0: "晴",
    1: "大体晴朗",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "轻微冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "较强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴小冰雹",
    99: "雷雨伴冰雹",
}


@dataclass(frozen=True)
class WeatherSnapshot:
    location: str
    latitude: float
    longitude: float
    timezone: str
    fetched_at: str
    forecast_date: str
    condition: str
    weather_code: int
    temperature_c: float | None
    apparent_temperature_c: float | None
    minimum_temperature_c: float | None
    maximum_temperature_c: float | None
    precipitation_probability: int | None
    precipitation_sum_mm: float | None
    maximum_wind_kmh: float | None
    rain_likely: bool
    severe: bool
    provider: str = "open-meteo"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WeatherSnapshot":
        return cls(
            location=str(data["location"]),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            timezone=str(data.get("timezone", "Asia/Shanghai")),
            fetched_at=str(data["fetched_at"]),
            forecast_date=str(data["forecast_date"]),
            condition=str(data.get("condition", "天气情况不明")),
            weather_code=int(data.get("weather_code", -1)),
            temperature_c=_optional_float(data.get("temperature_c")),
            apparent_temperature_c=_optional_float(
                data.get("apparent_temperature_c")
            ),
            minimum_temperature_c=_optional_float(
                data.get("minimum_temperature_c")
            ),
            maximum_temperature_c=_optional_float(
                data.get("maximum_temperature_c")
            ),
            precipitation_probability=_optional_int(
                data.get("precipitation_probability")
            ),
            precipitation_sum_mm=_optional_float(
                data.get("precipitation_sum_mm")
            ),
            maximum_wind_kmh=_optional_float(data.get("maximum_wind_kmh")),
            rain_likely=bool(data.get("rain_likely", False)),
            severe=bool(data.get("severe", False)),
            provider=str(data.get("provider", "open-meteo")),
        )

    def natural_brief(self, *, include_location: bool = True) -> str:
        location = f"{self.location}今天" if include_location else "今天"
        temp = _temperature_range(
            self.minimum_temperature_c,
            self.maximum_temperature_c,
        )
        pieces = [f"{location}{self.condition}"]
        if temp:
            pieces.append(temp)
        if self.rain_likely:
            probability = (
                f"，降雨概率最高约{self.precipitation_probability}%"
                if self.precipitation_probability is not None
                else ""
            )
            pieces.append(f"可能下雨{probability}，出门记得带伞")
        elif self.maximum_wind_kmh is not None and self.maximum_wind_kmh >= 35:
            pieces.append("风会比较大，外出注意一下")
        elif (
            self.maximum_temperature_c is not None
            and self.maximum_temperature_c >= 34
        ):
            pieces.append("白天会挺热，别在外面晒太久")
        elif (
            self.minimum_temperature_c is not None
            and self.minimum_temperature_c <= 5
        ):
            pieces.append("早晚偏冷，外套最好带上")
        return "，".join(piece.strip("，。") for piece in pieces if piece) + "。"


class WeatherProvider(Protocol):
    def geocode(self, query: str) -> dict[str, Any]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("地点不能为空")

        selected: dict[str, Any] | None = None
        selected_query = cleaned
        for candidate in _geocoding_queries(cleaned):
            data = self._get_json(
                self.GEOCODING_ENDPOINT,
                {
                    "name": candidate,
                    "count": 20,
                    "language": "zh",
                    "format": "json",
                    "countryCode": "CN",
                },
            )
            results = data.get("results", [])
            if not isinstance(results, list) or not results:
                continue
            selected = _select_geocoding_result(cleaned, results)
            selected_query = candidate
            break

        if selected is None:
            raise ValueError(f"没有找到地点：{cleaned}")

        name_parts = [
            str(selected.get("admin1", "")).strip(),
            str(selected.get("admin2", "")).strip(),
            str(selected.get("admin3", "")).strip(),
            str(selected.get("name", "")).strip(),
        ]
        unique_parts: list[str] = []
        for part in name_parts:
            if part and part not in unique_parts:
                unique_parts.append(part)
        display = "".join(unique_parts) or cleaned
        return {
            "country": str(selected.get("country", "中国")),
            "province": str(selected.get("admin1", "")),
            "city": str(selected.get("admin2", "")),
            "district": str(selected.get("name", "")),
            "display_name": display,
            "query": cleaned,
            "geocoding_query": selected_query,
            "latitude": float(selected["latitude"]),
            "longitude": float(selected["longitude"]),
            "timezone": str(selected.get("timezone", "Asia/Shanghai")),
            "resolved_by": "open-meteo-geocoding",
        }

    def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str,
        display_name: str,
        now: datetime,
    ) -> WeatherSnapshot: ...


class OpenMeteoWeatherProvider:
    """Open-Meteo 的轻量标准库客户端，不要求 API Key。"""

    GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = max(2.0, float(timeout_seconds))

    def _get_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = endpoint + "?" + urlencode(params)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "SilverWolf-Lv17/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"天气服务暂时不可用：{exc}") from exc
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("天气服务返回了无效数据") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("天气服务返回格式不正确")
        return parsed

    def geocode(self, query: str) -> dict[str, Any]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("地点不能为空")
        data = self._get_json(
            self.GEOCODING_ENDPOINT,
            {
                "name": cleaned,
                "count": 10,
                "language": "zh",
                "format": "json",
                "countryCode": "CN",
            },
        )
        results = data.get("results", [])
        if not isinstance(results, list) or not results:
            raise ValueError(f"没有找到地点：{cleaned}")
        selected = _select_geocoding_result(cleaned, results)
        name_parts = [
            str(selected.get("admin1", "")).strip(),
            str(selected.get("admin2", "")).strip(),
            str(selected.get("name", "")).strip(),
        ]
        display = "".join(
            part for index, part in enumerate(name_parts)
            if part and part not in name_parts[:index]
        ) or cleaned
        return {
            "country": str(selected.get("country", "中国")),
            "province": str(selected.get("admin1", "")),
            "city": str(selected.get("admin2", "")),
            "district": str(selected.get("name", "")),
            "display_name": display,
            "query": cleaned,
            "latitude": float(selected["latitude"]),
            "longitude": float(selected["longitude"]),
            "timezone": str(selected.get("timezone", "Asia/Shanghai")),
            "resolved_by": "open-meteo-geocoding",
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
        data = self._get_json(
            self.FORECAST_ENDPOINT,
            {
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone or "auto",
                "forecast_days": 3,
                "current": (
                    "temperature_2m,apparent_temperature,weather_code,"
                    "wind_speed_10m"
                ),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,precipitation_sum,"
                    "wind_speed_10m_max"
                ),
            },
        )
        current = data.get("current", {})
        daily = data.get("daily", {})
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise RuntimeError("天气服务缺少必要字段")
        weather_code = int(_first(daily.get("weather_code"), current.get("weather_code", -1)))
        precipitation_probability = _optional_int(
            _first(daily.get("precipitation_probability_max"), None)
        )
        precipitation_sum = _optional_float(
            _first(daily.get("precipitation_sum"), None)
        )
        maximum_wind = _optional_float(
            _first(daily.get("wind_speed_10m_max"), current.get("wind_speed_10m"))
        )
        rain_likely = bool(
            weather_code in set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}
            or (precipitation_probability or 0) >= 45
            or (precipitation_sum or 0) >= 0.5
        )
        severe = bool(
            weather_code in {65, 67, 75, 82, 86, 95, 96, 99}
            or (maximum_wind or 0) >= 50
            or (precipitation_sum or 0) >= 25
        )
        forecast_date = str(_first(daily.get("time"), now.date().isoformat()))
        return WeatherSnapshot(
            location=display_name,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=str(data.get("timezone", timezone or "Asia/Shanghai")),
            fetched_at=now.isoformat(timespec="seconds"),
            forecast_date=forecast_date,
            condition=WMO_CONDITIONS.get(weather_code, "天气情况不明"),
            weather_code=weather_code,
            temperature_c=_optional_float(current.get("temperature_2m")),
            apparent_temperature_c=_optional_float(
                current.get("apparent_temperature")
            ),
            minimum_temperature_c=_optional_float(
                _first(daily.get("temperature_2m_min"), None)
            ),
            maximum_temperature_c=_optional_float(
                _first(daily.get("temperature_2m_max"), None)
            ),
            precipitation_probability=precipitation_probability,
            precipitation_sum_mm=precipitation_sum,
            maximum_wind_kmh=maximum_wind,
            rain_likely=rain_likely,
            severe=severe,
        )


class WeatherService:
    def __init__(
        self,
        *,
        context_manager: Any,
        provider: WeatherProvider | None = None,
        cache_path: Path = WEATHER_CACHE_PATH,
        cache_minutes: int = 30,
    ) -> None:
        ensure_directories()
        self.context_manager = context_manager
        self.provider = provider or OpenMeteoWeatherProvider()
        self.cache_path = cache_path
        self.cache_minutes = max(5, int(cache_minutes))
        self._lock = threading.RLock()

    def lookup(
        self,
        *,
        now: datetime,
        force: bool = False,
    ) -> dict[str, Any]:
        location = self.context_manager.active_location(now)
        try:
            location = self.context_manager.ensure_resolved(location)
        except Exception as exc:
            return {
                "available": False,
                "cached": False,
                "location": str(location.get("display_name", location.get("query", "当前地点"))),
                "error": str(exc),
            }
        cache_key = self._cache_key(location, now)
        if not force:
            cached = self._load_cached(cache_key, now)
            if cached is not None:
                comparison = self._temperature_comparison(location, cached)
                return {
                    "available": True,
                    "cached": True,
                    "location_source": location.get("source", "home"),
                    "snapshot": cached.to_dict(),
                    "summary": cached.natural_brief(),
                    **comparison,
                }
        try:
            snapshot = self.provider.forecast(
                latitude=float(location["latitude"]),
                longitude=float(location["longitude"]),
                timezone=str(location.get("timezone", "Asia/Shanghai")),
                display_name=str(location.get("display_name", location.get("query", "当前地点"))),
                now=now,
            )
        except Exception as exc:
            return {
                "available": False,
                "cached": False,
                "location": str(location.get("display_name", "当前地点")),
                "error": str(exc),
            }
        comparison = self._temperature_comparison(location, snapshot)
        self._save_cached(cache_key, snapshot)
        return {
            "available": True,
            "cached": False,
            "location_source": location.get("source", "home"),
            "snapshot": snapshot.to_dict(),
            "summary": snapshot.natural_brief(),
            **comparison,
        }

    def _cache_key(self, location: dict[str, Any], now: datetime) -> str:
        return "|".join(
            [
                str(location.get("latitude")),
                str(location.get("longitude")),
                now.date().isoformat(),
            ]
        )

    def _read_cache(self) -> dict[str, Any]:
        with self._lock:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return {"schema_version": 1, "entries": {}}
            return data if isinstance(data, dict) else {"schema_version": 1, "entries": {}}

    def _load_cached(
        self,
        cache_key: str,
        now: datetime,
    ) -> WeatherSnapshot | None:
        entry = self._read_cache().get("entries", {}).get(cache_key)
        if not isinstance(entry, dict):
            return None
        try:
            fetched_at = datetime.fromisoformat(str(entry["fetched_at"]))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=now.tzinfo)
            if now - fetched_at > timedelta(minutes=self.cache_minutes):
                return None
            return WeatherSnapshot.from_dict(dict(entry["snapshot"]))
        except (KeyError, TypeError, ValueError):
            return None

    def _temperature_comparison(
        self,
        location: dict[str, Any],
        current: WeatherSnapshot,
    ) -> dict[str, Any]:
        latitude = str(location.get("latitude"))
        longitude = str(location.get("longitude"))
        candidates: list[WeatherSnapshot] = []
        for key, entry in self._read_cache().get("entries", {}).items():
            if not str(key).startswith(f"{latitude}|{longitude}|"):
                continue
            if not isinstance(entry, dict):
                continue
            try:
                snapshot = WeatherSnapshot.from_dict(dict(entry["snapshot"]))
            except (KeyError, TypeError, ValueError):
                continue
            if snapshot.forecast_date < current.forecast_date:
                candidates.append(snapshot)
        if not candidates:
            return {
                "temperature_change_c": None,
                "temperature_change_significant": False,
            }
        previous = max(candidates, key=lambda item: item.forecast_date)
        current_value = _representative_temperature(current)
        previous_value = _representative_temperature(previous)
        if current_value is None or previous_value is None:
            return {
                "temperature_change_c": None,
                "temperature_change_significant": False,
            }
        change = round(current_value - previous_value, 1)
        return {
            "temperature_change_c": change,
            "temperature_change_significant": abs(change) >= 5.0,
            "temperature_change_reference_date": previous.forecast_date,
        }

    def _save_cached(self, cache_key: str, snapshot: WeatherSnapshot) -> None:
        with self._lock:
            data = self._read_cache()
            entries = data.setdefault("entries", {})
            entries[cache_key] = {
                "fetched_at": snapshot.fetched_at,
                "snapshot": snapshot.to_dict(),
            }
            if len(entries) > 20:
                newest = sorted(
                    entries.items(),
                    key=lambda item: str(item[1].get("fetched_at", "")),
                    reverse=True,
                )[:20]
                data["entries"] = dict(newest)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _geocoding_queries(query: str) -> list[str]:
    """为中国行政区名称生成少量、可解释的回退查询。"""
    cleaned = query.strip()
    candidates = [cleaned]
    without_suffix = re.sub(r"(中华人民共和国|中国)", "", cleaned)
    without_suffix = re.sub(r"(省|自治区|特别行政区|市|区|县|旗)$", "", without_suffix)
    candidates.append(without_suffix)

    parts = [
        part
        for part in re.split(r"省|自治区|特别行政区|市|区|县|旗", cleaned)
        if part
    ]
    candidates.extend(reversed(parts))

    result: list[str] = []
    for candidate in candidates:
        value = candidate.strip()
        if len(value) >= 2 and value not in result:
            result.append(value)
    return result


def _location_tokens(query: str) -> list[str]:
    raw = query.strip()
    tokens = [raw]
    tokens.extend(
        part
        for part in re.split(r"省|自治区|特别行政区|市|区|县|旗|[ /,，]", raw)
        if len(part) >= 2
    )
    result: list[str] = []
    for token in tokens:
        normalized = token.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _select_geocoding_result(query: str, results: list[Any]) -> dict[str, Any]:
    tokens = _location_tokens(query)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        fields = [
            str(item.get(key, ""))
            for key in ("name", "admin1", "admin2", "admin3", "country")
        ]
        haystack = "".join(fields)
        score = 0
        for token in tokens:
            if token in haystack:
                score += 3 if token == query else 1
        if str(item.get("country_code", "")).upper() == "CN":
            score += 1
        scored.append((score, -index, item))
    if not scored:
        raise ValueError(f"没有找到地点：{query}")
    return max(scored, key=lambda item: (item[0], item[1]))[2]


def _first(value: Any, fallback: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else fallback
    return fallback if value is None else value


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _representative_temperature(snapshot: WeatherSnapshot) -> float | None:
    values = [
        value
        for value in (
            snapshot.minimum_temperature_c,
            snapshot.maximum_temperature_c,
        )
        if value is not None
    ]
    if values:
        return sum(values) / len(values)
    return snapshot.temperature_c


def _temperature_range(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return ""
    if low is None:
        return f"最高约{high:g}℃"
    if high is None:
        return f"最低约{low:g}℃"
    return f"{low:g}～{high:g}℃"
