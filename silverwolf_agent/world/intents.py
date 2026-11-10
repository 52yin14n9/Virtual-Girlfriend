from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import re
from typing import Any


@dataclass(frozen=True)
class Lv17Intent:
    kind: str
    arguments: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


class Lv17IntentAnalyzer:
    """Lv17 环境与关系型主动行为的本地自然语言意图识别。"""

    WEATHER_PATTERN = re.compile(
        r"(天气|气温|温度|下雨|降雨|带伞|冷不冷|热不热|会不会冷|会不会热|降温|升温)"
    )
    EVENT_LABELS: tuple[tuple[str, str, int], ...] = (
        ("面试", "面试", 120),
        ("考试", "考试", 210),
        ("答辩", "答辩", 150),
        ("会议", "会议", 120),
        ("开会", "会议", 120),
        ("体检", "体检", 180),
        ("看病", "看病", 180),
        ("去医院", "看病", 180),
        ("坐车", "行程", 240),
        ("出发", "行程", 240),
        ("部署", "部署", 180),
        ("上线", "上线", 120),
        ("提交作业", "作业提交", 60),
        ("交作业", "作业提交", 60),
    )

    def analyze(self, text: str, now: datetime) -> list[Lv17Intent]:
        cleaned = text.strip()
        intents: list[Lv17Intent] = []

        location_intents = self._location_intents(cleaned, now)
        intents.extend(location_intents)

        weather_pref = self._weather_preference_intent(cleaned)
        if weather_pref is not None:
            intents.append(weather_pref)

        interaction = self._interaction_intent(cleaned, now)
        if interaction is not None:
            intents.append(interaction)

        event_cancel = self._event_cancel_intent(cleaned)
        if event_cancel is not None:
            intents.append(event_cancel)
        else:
            event = self._event_follow_up_intent(cleaned, now)
            if event is not None:
                intents.append(event)

        # 修改地点或天气偏好时，不顺带查询当前天气，避免“下周去杭州”
        # 却错误回答今天常住地的天气。
        if (
            self.WEATHER_PATTERN.search(cleaned)
            and weather_pref is None
            and not location_intents
        ):
            intents.append(Lv17Intent(kind="weather_lookup"))

        return self._deduplicate(intents)

    def _location_intents(self, text: str, now: datetime) -> list[Lv17Intent]:
        if re.search(r"(我回(?:南京|家)了|恢复(?:看|关注)(?:南京|浦口)(?:的)?天气|清除临时地点)", text):
            return [Lv17Intent(kind="clear_temporary_location")]

        intents: list[Lv17Intent] = []

        permanent_patterns = (
            re.compile(r"(?:以后|今后).{0,8}(?:看|查|关注)(?P<location>[^，。！？]{2,24}?)(?:的)?天气"),
            re.compile(r"(?:把我的位置|把位置|把地点|位置|地点)(?:改成|设为|设置为)(?P<location>[^，。！？]{2,24})"),
            re.compile(r"我搬到(?P<location>[^，。！？]{2,24}?)(?:了|居住|住了|$)"),
            re.compile(r"我(?:现在|最近)?住(?:在)?(?P<location>[\u4e00-\u9fffA-Za-z0-9·]{2,24})(?=[，,。！？]|$)"),
        )
        for pattern in permanent_patterns:
            match = pattern.search(text)
            if not match:
                continue
            location = self._clean_location(match.group("location"))
            if location:
                intents.append(
                    Lv17Intent(
                        kind="set_home_location",
                        arguments={"query": location},
                    )
                )
                break

        temporary_patterns = (
            re.compile(
                r"(?:这周|本周|今天|明天|下周[^，。]{0,8})?(?:我)?(?:在|去|住在)"
                r"(?P<location>[^，。！？]{2,20}?)(?:出差|旅游|住几天|待几天|待到|开会)"
            ),
            re.compile(r"(?:天气)?先看(?P<location>[^，。！？]{2,20}?)(?:的)?天气?(?=[，,。！？]|$)"),
            re.compile(
                r"(?:今天|明天|这周|本周|下周[一二三四五六日天]?(?:到周?[一二三四五六日天])?)"
                r"(?:我)?(?:去|在)(?P<location>[\u4e00-\u9fffA-Za-z0-9·]{2,20})(?=[，,。！？]|$)"
            ),
        )
        for pattern in temporary_patterns:
            match = pattern.search(text)
            if not match:
                continue
            location = self._clean_location(match.group("location"))
            if not location:
                continue
            starts_at, ends_at = self._temporary_window(text, now)
            intents.append(
                Lv17Intent(
                    kind="set_temporary_location",
                    arguments={
                        "query": location,
                        "starts_at": starts_at.isoformat(timespec="seconds"),
                        "ends_at": ends_at.isoformat(timespec="seconds"),
                    },
                )
            )
            break

        return intents

    @staticmethod
    def _clean_location(value: str) -> str:
        cleaned = value.strip(" ，,。！？!?的")
        cleaned = re.sub(r"^(?:我|先|暂时)", "", cleaned)
        cleaned = re.sub(r"(?:这边|那里|那边)$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _temporary_window(text: str, now: datetime) -> tuple[datetime, datetime]:
        start = now
        end = now + timedelta(days=7)

        if "今天" in text:
            end = datetime.combine(now.date(), time(23, 59), tzinfo=now.tzinfo)
        elif "明天" in text:
            start = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
            end = datetime.combine(start.date(), time(23, 59), tzinfo=now.tzinfo)
        elif "下周" in text:
            days_to_monday = (7 - now.weekday()) % 7 or 7
            start_date = now.date() + timedelta(days=days_to_monday)
            start = datetime.combine(start_date, time.min, tzinfo=now.tzinfo)
            end = start + timedelta(days=7) - timedelta(minutes=1)
            range_match = re.search(r"下周([一二三四五六日天])到周?([一二三四五六日天])", text)
            if range_match:
                mapping = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
                start = datetime.combine(
                    start_date + timedelta(days=mapping[range_match.group(1)]),
                    time.min,
                    tzinfo=now.tzinfo,
                )
                end = datetime.combine(
                    start_date + timedelta(days=mapping[range_match.group(2)]),
                    time(23, 59),
                    tzinfo=now.tzinfo,
                )
        elif "这周" in text or "本周" in text:
            days_to_sunday = 6 - now.weekday()
            end = datetime.combine(
                now.date() + timedelta(days=max(0, days_to_sunday)),
                time(23, 59),
                tzinfo=now.tzinfo,
            )
        return start, end

    @staticmethod
    def _weather_preference_intent(text: str) -> Lv17Intent | None:
        if re.search(r"(不要告诉我天气|关闭天气|别再看天气)", text):
            return Lv17Intent(kind="set_weather_preferences", arguments={"updates": {"enabled": False}})
        if re.search(r"(恢复天气|每天告诉我天气|每天说一下天气)", text):
            return Lv17Intent(
                kind="set_weather_preferences",
                arguments={"updates": {"enabled": True, "daily_brief_enabled": True}},
            )
        if re.search(r"(天气不用每天说|别每天.*天气|不用每天.*天气)", text):
            updates: dict[str, Any] = {"daily_brief_enabled": False}
            if "下雨" in text:
                updates["rain_alerts"] = True
            return Lv17Intent(kind="set_weather_preferences", arguments={"updates": updates})
        if re.search(r"(下雨再提醒|只有下雨|下雨的时候提醒)", text):
            return Lv17Intent(
                kind="set_weather_preferences",
                arguments={"updates": {"enabled": True, "daily_brief_enabled": False, "rain_alerts": True}},
            )
        return None

    @staticmethod
    def _interaction_intent(text: str, now: datetime) -> Lv17Intent | None:
        if re.search(r"(今天别主动找我|今天不要主动找我|今天安静一点)", text):
            until = datetime.combine(now.date(), time(23, 59), tzinfo=now.tzinfo)
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"quiet_until": until.isoformat(timespec="seconds")}})
        if re.search(r"(晚上可以来找我|晚上再来找我)", text):
            until = datetime.combine(now.date(), time(19, 0), tzinfo=now.tzinfo)
            if until <= now:
                until = now
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"quiet_until": until.isoformat(timespec="seconds")}})
        if re.search(r"(这几天很忙|最近很忙|这几天少找我|最近少找我|今天少找我)", text):
            until = (
                datetime.combine(now.date(), time(23, 59), tzinfo=now.tzinfo)
                if "今天" in text
                else now + timedelta(days=3)
            )
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"proactive_frequency_mode": "low", "proactive_frequency_until": until.isoformat(timespec="seconds")}})
        if re.search(r"(多陪我聊|多主动找我|可以多找我|最近多找我)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"proactive_frequency_mode": "high", "proactive_frequency_until": None, "quiet_until": None}})
        if re.search(r"(恢复正常频率|正常一点就好|按平常来)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"proactive_frequency_mode": "normal", "proactive_frequency_until": None, "quiet_until": None}})
        if re.search(r"(别再事后问我|关闭事件关心|不要问我事情结果)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"event_follow_up_enabled": False}})
        if re.search(r"(恢复事件关心|事情结束后可以问我|可以事后问我)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"event_follow_up_enabled": True}})
        if re.search(r"(周末别推荐|关闭周末建议|周末不用给建议)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"weekend_suggestions_enabled": False}})
        if re.search(r"(恢复周末建议|周末可以给我建议)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"weekend_suggestions_enabled": True}})
        if re.search(r"(别再提以前的事|关闭话题回访|不要回忆旧话题)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"memory_callback_enabled": False}})
        if re.search(r"(恢复话题回访|可以提以前的事)", text):
            return Lv17Intent(kind="set_interaction_preferences", arguments={"updates": {"memory_callback_enabled": True}})
        return None

    def _event_cancel_intent(self, text: str) -> Lv17Intent | None:
        if not re.search(r"(别问|别再问|不用问|不要再问|别再提|取消.*关心)", text):
            return None
        for token, label, _duration in self.EVENT_LABELS:
            if token in text or label in text:
                return Lv17Intent(kind="cancel_event_follow_up", arguments={"query": label})
        return None

    def _event_follow_up_intent(self, text: str, now: datetime) -> Lv17Intent | None:
        explicitly_requests_follow_up = bool(
            re.search(r"(结束后|忙完后|完事后|结束了以后).{0,10}(问|找|关心)|到时候问问我", text)
        )
        if not explicitly_requests_follow_up and re.search(
            r"(刚刚?|已经).{0,12}(结束|完成|做完|考完|面完)|(?:结束|完成|做完|考完|面完)了",
            text,
        ):
            return None

        selected: tuple[str, str, int] | None = None
        for item in self.EVENT_LABELS:
            if item[0] in text:
                selected = item
                break
        if selected is None:
            return None

        if not explicitly_requests_follow_up and not re.search(
            r"(今天|明天|后天|上午|中午|下午|晚上|晚点|一会|\d{1,2}(?:[:：]|点)|[一二三四五六七八九十两]点|要去|有|准备|打算)",
            text,
        ):
            return None

        _token, label, duration_minutes = selected
        due_at = self._event_due(text, now, duration_minutes)
        if due_at <= now + timedelta(minutes=5):
            return None
        return Lv17Intent(
            kind="create_event_follow_up",
            arguments={
                "event_label": label,
                "title": f"问问{label}怎么样",
                "due_at": due_at.isoformat(timespec="seconds"),
                "source_text": text,
                "explicit_request": explicitly_requests_follow_up,
            },
            confidence=0.9 if explicitly_requests_follow_up else 0.86,
        )

    def _event_due(self, text: str, now: datetime, duration_minutes: int) -> datetime:
        target_date = now.date()
        if "后天" in text:
            target_date += timedelta(days=2)
        elif "明天" in text:
            target_date += timedelta(days=1)

        hour, minute = self._extract_clock(text)
        if hour is None:
            if "上午" in text:
                hour, minute = 12, 0
            elif "中午" in text:
                hour, minute = 14, 0
            elif "下午" in text:
                hour, minute = 18, 0
            elif "晚上" in text:
                hour, minute = 22, 0
            else:
                return now + timedelta(hours=4)
            # 没有明确起始时刻时，这里直接取一个保守的“可能结束”时间。
            return datetime.combine(target_date, time(hour, minute), tzinfo=now.tzinfo)

        start = datetime.combine(target_date, time(hour, minute), tzinfo=now.tzinfo)
        return start + timedelta(minutes=duration_minutes)

    @staticmethod
    def _extract_clock(text: str) -> tuple[int | None, int]:
        match = re.search(
            r"(?P<hour>\d{1,2})(?:[:：](?P<minute>\d{1,2})|点(?P<half>半)?(?:(?P<cnminute>[一二三四五六]?十?)[分]?)?)",
            text,
        )
        if match:
            hour = int(match.group("hour"))
            minute = int(match.group("minute") or 0)
            if match.group("half"):
                minute = 30
            if "下午" in text or "晚上" in text:
                if 1 <= hour < 12:
                    hour += 12
            return min(hour, 23), min(minute, 59)

        cn_match = re.search(r"([一二三四五六七八九十两]{1,3})点(半)?", text)
        if cn_match:
            hour = _chinese_number(cn_match.group(1))
            if ("下午" in text or "晚上" in text) and hour < 12:
                hour += 12
            return min(hour, 23), 30 if cn_match.group(2) else 0
        return None, 0

    @staticmethod
    def _deduplicate(intents: list[Lv17Intent]) -> list[Lv17Intent]:
        result: list[Lv17Intent] = []
        seen: set[tuple[str, str]] = set()
        for intent in intents:
            key = (intent.kind, repr(sorted(intent.arguments.items())))
            if key not in seen:
                seen.add(key)
                result.append(intent)
        return result


def _chinese_number(value: str) -> int:
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        return (mapping.get(left, 1) * 10) + mapping.get(right, 0)
    return mapping.get(value, 0)
