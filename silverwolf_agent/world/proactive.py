from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .weather import WeatherSnapshot


class ContextualCareComposer:
    """把天气、近期话题与周末建议融入既有主动消息。"""

    TOPIC_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"(NapCat|napcat|部署|服务器|上线)"), "之前折腾的部署后来跑稳了吗？"),
        (re.compile(r"(项目|代码|开发|程序)"), "手头那个项目后来推进得怎么样？"),
        (re.compile(r"(面试|考试|答辩|会议)"), "之前提到的那件重要事情，后来还顺利吗？"),
        (re.compile(r"(头疼|不舒服|生病|发烧)"), "之前不太舒服，现在好一点了吗？"),
        (re.compile(r"(累|很忙|熬夜|没睡好)"), "你前面看起来挺累的，今天别一开局就把自己塞满。"),
    )

    def compose(
        self,
        *,
        base: str,
        routine_key: str,
        now: datetime,
        recent_user_text: str,
        weather_result: dict[str, Any] | None,
        memory_callback_enabled: bool,
        weekend_suggestions_enabled: bool,
        silence_return: bool = False,
        open_threads: tuple[str, ...] | list[str] = (),
    ) -> tuple[str, dict[str, Any]]:
        content = base.strip()
        metadata: dict[str, Any] = {}
        callback_used = False

        # Lv28: 长时间没说话之后，第一条不再是"早上好"式重新认识，
        # 而是顺着上次没结束的事接着说。
        if silence_return:
            continuation = self.silence_continuation(
                recent_user_text,
                open_threads=open_threads,
            )
            if continuation:
                content = continuation
                metadata["silence_return"] = True
                metadata["silence_continuation"] = continuation
                callback_used = True

        snapshot: WeatherSnapshot | None = None
        if weather_result and weather_result.get("available"):
            raw = weather_result.get("snapshot")
            if isinstance(raw, dict):
                snapshot = WeatherSnapshot.from_dict(raw)
        if snapshot is not None:
            # Lv24: weather is a piece of shared context, not a data bulletin.
            # Keep the useful fact, omit low-value probability telemetry, and
            # place it after the greeting when possible so the message still
            # sounds like one person opening a conversation.
            weather_line = self._weather_context_line(snapshot)
            content = self._blend_context_line(content, weather_line)
            metadata["weather_context_included"] = True
            metadata["weather_severe"] = snapshot.severe
            metadata["weather_rain_likely"] = snapshot.rain_likely
            # Lv31: 语料重写时，地名/天气是必须保留的事实词
            metadata["weather_location"] = str(snapshot.location or "")
            metadata["weather_condition"] = str(snapshot.condition or "")
        if memory_callback_enabled and not callback_used:
            callback = self._memory_callback(recent_user_text)
            if callback and callback not in content:
                content = f"{content} {callback}"
                metadata["memory_callback"] = callback
        if (
            weekend_suggestions_enabled
            and now.weekday() >= 5
            and routine_key == "morning"
            and not metadata.get("silence_return")
        ):
            suggestion = self._weekend_suggestion(snapshot)
            if suggestion and suggestion not in content:
                content = f"{content} {suggestion}"
                metadata["weekend_suggestion"] = suggestion
        return content[:360], metadata

    def silence_continuation(
        self,
        recent_user_text: str,
        *,
        open_threads: tuple[str, ...] | list[str] = (),
    ) -> str:
        """沉默回归的第一句：先接未完成的事，再退回到话题回忆。"""
        for thread in open_threads:
            label = str(thread).strip()
            if len(label) >= 2:
                return f"上次说的「{label}」，这几天动过一点吗？"
        return self._memory_callback(recent_user_text)


    def weather_alert(
        self,
        *,
        snapshot: WeatherSnapshot,
    ) -> str | None:
        if snapshot.severe:
            return f"{snapshot.location}今天的天气不太安分：{snapshot.condition}。外出前再确认一下情况，别硬顶。"
        if snapshot.rain_likely:
            return f"{snapshot.location}今天可能下雨，伞带上，省得回来一身湿。"
        return None

    @classmethod
    def _weather_context_line(cls, snapshot: WeatherSnapshot) -> str:
        condition = str(snapshot.condition or "天气").strip()
        temperature = cls._temperature_text(snapshot)
        if snapshot.severe:
            tail = "外出前再看一眼天气"
        elif snapshot.rain_likely or re.search(r"雨|雪|雷", condition):
            tail = "出门的话记得带伞"
        elif snapshot.maximum_wind_kmh is not None and snapshot.maximum_wind_kmh >= 35:
            tail = "外面风挺大"
        elif snapshot.maximum_temperature_c is not None and snapshot.maximum_temperature_c >= 34:
            tail = "白天会挺热"
        elif snapshot.minimum_temperature_c is not None and snapshot.minimum_temperature_c <= 5:
            tail = "早晚有点冷"
        else:
            tail = ""

        pieces = [f"{snapshot.location}今天{condition}"]
        if temperature:
            pieces.append(temperature)
        if tail:
            pieces.append(tail)
        return "，".join(pieces).rstrip("，。") + "。"

    @staticmethod
    def _temperature_text(snapshot: WeatherSnapshot) -> str:
        low = snapshot.minimum_temperature_c
        high = snapshot.maximum_temperature_c
        if low is not None and high is not None:
            return f"{low:g}～{high:g}℃"
        if snapshot.temperature_c is not None:
            return f"大概{snapshot.temperature_c:g}℃"
        return ""

    @staticmethod
    def _blend_context_line(base: str, context_line: str) -> str:
        # Preserve a short greeting/opening before the weather, instead of
        # producing "weather bulletin + template" as two visibly glued blocks.
        match = re.match(r"^(.{1,24}?[。！？!?])(.+)$", base)
        if match:
            opening = match.group(1).strip()
            rest = match.group(2).strip()
            return f"{opening}{context_line}{rest}"
        return f"{context_line}{base}"

    def _memory_callback(self, recent_user_text: str) -> str:
        text = recent_user_text[-1200:]
        for pattern, response in self.TOPIC_RULES:
            if pattern.search(text):
                return response
        return ""

    @staticmethod
    def _weekend_suggestion(snapshot: WeatherSnapshot | None) -> str:
        if snapshot is None:
            return "周末不用把进度条塞满，给自己留点真正休息的时间。"
        if snapshot.rain_likely or snapshot.severe:
            return "周末外面不太友好，窝在室内打会儿游戏或者安静做点喜欢的事也不错。"
        if snapshot.maximum_temperature_c is not None and snapshot.maximum_temperature_c >= 34:
            return "想出去的话挑凉快一点的时间，别在最热的时候和太阳硬碰硬。"
        if snapshot.minimum_temperature_c is not None and snapshot.minimum_temperature_c <= 5:
            return "天气偏冷，想出门走走就多穿一点；留在室内也完全合理。"
        return "天气还行，晚点出去走走、吃点喜欢的东西也不错。"
