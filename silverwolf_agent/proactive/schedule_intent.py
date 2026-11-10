from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)
import re

from .contracts import ScheduleDecision
from .time_manager import TimeManager


CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def chinese_number(
    value: str,
) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)

    if value == "十":
        return 10
    if value.startswith("十"):
        tail = value[1:]
        return 10 + (
            CHINESE_DIGITS.get(
                tail,
                0,
            )
            if tail
            else 0
        )
    if value.endswith("十"):
        head = value[:-1]
        return (
            CHINESE_DIGITS.get(
                head,
                1,
            )
            * 10
        )
    if "十" in value:
        head, tail = value.split(
            "十",
            1,
        )
        return (
            CHINESE_DIGITS.get(
                head,
                1,
            )
            * 10
            + CHINESE_DIGITS.get(
                tail,
                0,
            )
        )
    return CHINESE_DIGITS.get(value)


def clean_schedule_title(
    value: str,
) -> str:
    """Normalize reminder titles into the action itself, not a system phrase."""
    cleaned = value.strip(
        " ，,。！？!?的"
    )
    cleaned = re.sub(
        r"^(?:请)?(?:提醒(?:我)?|叫(?:我)?|喊(?:我)?|敲(?:我)?)(?:一下)?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:好不好|好吗|行不行|可以吗|可不可以|吧|啦|呀|啊|哦)+$",
        "",
        cleaned,
    )
    # 计划标题描述的是用户要做的动作，不应该把第一人称主语存进去。
    # 只在后面明显是动作动词时去掉“我”，避免破坏“我妈生日”之类名词短语。
    cleaned = re.sub(
        r"^我(?:今天|明天|等会儿|待会儿)?(?:要|得|该|需要|应该|准备|打算|会)?"
        r"(?=(?:去|到|回|出发|上班|下班|开会|参加|学习|复习|写|做|交|提交|吃|喝|睡|起|买|拿|取|联系|打|看|训练|运动|工作|赶|收|发))",
        "",
        cleaned,
    )
    cleaned = cleaned.strip(
        " ，,。！？!?的"
    )
    return cleaned


class ScheduleIntentAnalyzer:
    REMINDER_PATTERN = re.compile(
        (
            r"(提醒我|记得提醒我|"
            r"别忘了提醒我|"
            r"到时候叫我|"
            r"记得叫我|"
            r"叫我(?:一下)?|"
            r"喊我(?:一下)?|"
            r"敲我(?:一下)?|"
            r"你记一下|"
            r"给我发(?:个|一条)?消息|"
            r"发(?:个|一条)?消息给我|"
            r"到时候(?:来)?找我|"
            r"到时候联系我|"
            r"到时候敲我|"
            r"到时候喊我)"
        )
    )

    FUTURE_MESSAGE_REQUEST_PATTERN = re.compile(
        (
            r"(给我发(?:个|一条)?消息|"
            r"发(?:个|一条)?消息给我|"
            r"(?:来)?找我|联系我|敲我|喊我)"
        )
    )

    FUTURE_PATTERN = re.compile(
        (
            r"(今天|今晚|明天|后天|"
            r"下周|以后|每天|"
            r"早上|上午|中午|"
            r"下午|晚上|"
            r"[零一二两三四五六七八九十百\d]+"
            r"(?:秒|分钟|小时)后)"
        )
    )

    RELATIVE_DURATION_PATTERN = re.compile(
        (
            r"(?P<amount>"
            r"[零一二两三四五六七八九十百\d]+)"
            r"(?P<unit>秒|分钟|小时)后"
        )
    )

    IMPORTANT_ACTION_PATTERN = re.compile(
        (
            r"(学习|复习|考试|上课|"
            r"开会|提交|截止|作业|"
            r"工作|训练|运动|吃药|"
            r"预约|出发|面试|"
            r"写代码|看书|休息|睡觉|睡下|起床|起来|"
            r"发消息|联系|找我|敲我|喊我)"
        ),
        re.IGNORECASE,
    )

    UNCERTAIN_PATTERN = re.compile(
        r"(可能|也许|看情况|随便|有空再)"
    )

    TIME_PREFERENCE_PATTERN = re.compile(
        (
            r"(以后|每天|每日|今后|改成|"
            r"调整到|换成|更新|修改|设成|定在|"
            r"提醒我).{0,36}"
            r"(早上|上午|中午|午饭|"
            r"下午|晚上|晚饭)"
        )
    )

    PLAN_LIST_PATTERN = re.compile(
        (
            r"(我有哪些提醒|"
            r"我的提醒|"
            r"查看计划|"
            r"看看计划|"
            r"我的计划|"
            r"你记着哪些事)"
        )
    )

    PLAN_CANCEL_PATTERN = re.compile(
        (
            r"(取消|删掉|不用提醒)"
            r"(?P<query>[^。！？\n]{0,40})"
            r"(?:提醒|计划)?"
        )
    )

    def __init__(
        self,
        time_manager: TimeManager,
    ) -> None:
        self.time_manager = time_manager

    def analyze(
        self,
        text: str,
        now: datetime,
    ) -> ScheduleDecision:
        explicit_reminder = bool(
            self.REMINDER_PATTERN.search(
                text
            )
        )
        future_message_request = bool(
            self.FUTURE_MESSAGE_REQUEST_PATTERN.search(
                text
            )
        )
        future_signal = bool(
            self.FUTURE_PATTERN.search(
                text
            )
        )
        action_signal = bool(
            self.IMPORTANT_ACTION_PATTERN.search(
                text
            )
        )
        uncertain = bool(
            self.UNCERTAIN_PATTERN.search(
                text
            )
        )

        relative_delta = (
            self._extract_relative_delta(
                text
            )
        )
        due_at = self._resolve_due_at(
            text,
            now,
        )
        exact_time = bool(
            self._extract_clock(text)
            or relative_delta
        )

        score = 0
        reasons: list[str] = []

        if explicit_reminder:
            score += 55
            reasons.append(
                "用户明确要求提醒或主动联系"
            )
        if future_message_request:
            score += 10
            reasons.append(
                "用户要求未来主动发消息"
            )
        if future_signal:
            score += 20
            reasons.append(
                "包含未来时间信号"
            )
        if relative_delta is not None:
            score += 10
            reasons.append(
                "包含相对倒计时"
            )
        if action_signal:
            score += 15
            reasons.append(
                "包含明确行动事项"
            )
        if exact_time:
            score += 10
            reasons.append(
                "包含具体时间"
            )
        if re.search(
            r"(必须|一定|重要|考试|截止)",
            text,
        ):
            score += 15
            reasons.append(
                "事项重要性较高"
            )
        if uncertain:
            score -= 30
            reasons.append(
                "表达存在不确定性"
            )

        score = max(
            0,
            min(100, score),
        )
        should_persist = (
            score >= 65
            and bool(due_at)
        )

        title = self._extract_title(text)
        if not title:
            title = "需要提醒的事项"

        habitual_clock_reminder = bool(
            explicit_reminder
            and exact_time
            and re.search(
                r"(以后|今后|往后)",
                text,
            )
        )
        recurrence = (
            "daily"
            if (
                re.search(
                    r"(每天|每日|每晚|每夜|每早)",
                    text,
                )
                or habitual_clock_reminder
            )
            else "none"
        )

        return ScheduleDecision(
            should_persist=should_persist,
            importance=score,
            reason=(
                "；".join(reasons)
                or "没有足够的计划信号"
            ),
            title=title,
            due_at=due_at,
            recurrence=recurrence,
            source_text=text,
        )

    def is_future_message_request(
        self,
        text: str,
    ) -> bool:
        return bool(
            self.FUTURE_MESSAGE_REQUEST_PATTERN.search(
                text
            )
            and self.FUTURE_PATTERN.search(
                text
            )
        )

    def analyze_time_preference(
        self,
        text: str,
    ) -> dict[str, str] | None:
        if not self.TIME_PREFERENCE_PATTERN.search(
            text
        ):
            return None

        slot = self._detect_slot(text)
        clock = self._extract_clock(text)
        if (
            slot is None
            or clock is None
        ):
            return None

        return {
            "slot": slot,
            "time": clock,
        }

    def wants_plan_list(
        self,
        text: str,
    ) -> bool:
        return bool(
            self.PLAN_LIST_PATTERN.search(
                text
            )
        )

    def cancellation_query(
        self,
        text: str,
    ) -> str | None:
        match = self.PLAN_CANCEL_PATTERN.search(
            text
        )
        if not match:
            return None

        query = (
            match.group("query")
            .strip(" ，,的")
        )
        return query or ""

    def _resolve_due_at(
        self,
        text: str,
        now: datetime,
    ) -> str:
        now = now.astimezone(
            self.time_manager.timezone()
        )

        relative_delta = (
            self._extract_relative_delta(
                text
            )
        )
        if relative_delta is not None:
            target = now + relative_delta
            return target.isoformat(
                timespec="seconds"
            )

        day_offset = 0
        if "后天" in text:
            day_offset = 2
        elif "明天" in text:
            day_offset = 1

        slot_name = self._detect_slot(
            text
        )
        clock = self._extract_clock(
            text
        )

        target_date = (
            now + timedelta(
                days=day_offset
            )
        )

        if clock is None:
            if slot_name is None:
                if day_offset > 0:
                    slot_name = "morning"
                else:
                    return ""
            clock = (
                self.time_manager
                .slot_time(slot_name)
            )

        hour, minute = (
            int(part)
            for part in clock.split(":")
        )
        target = target_date.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        if (
            day_offset == 0
            and target <= now
        ):
            target += timedelta(days=1)

        return target.isoformat(
            timespec="seconds"
        )

    def _extract_relative_delta(
        self,
        text: str,
    ) -> timedelta | None:
        match = (
            self.RELATIVE_DURATION_PATTERN
            .search(text)
        )
        if not match:
            return None

        amount = chinese_number(
            match.group("amount")
        )
        if amount is None or amount <= 0:
            return None

        unit = match.group("unit")
        if unit == "秒":
            return timedelta(
                seconds=amount
            )
        if unit == "分钟":
            return timedelta(
                minutes=amount
            )
        if unit == "小时":
            return timedelta(
                hours=amount
            )
        return None

    def _extract_clock(
        self,
        text: str,
    ) -> str | None:
        colon = re.search(
            (
                r"(?P<h>\d{1,2})"
                r"[:：]"
                r"(?P<m>\d{1,2})"
            ),
            text,
        )
        if colon:
            hour = int(
                colon.group("h")
            )
            minute = int(
                colon.group("m")
            )
            return self._normalize_hour(
                hour,
                minute,
                text,
            )

        point = re.search(
            (
                r"(?P<h>[零一二两三四五六"
                r"七八九十\d]{1,3})点"
                r"(?P<m>半|"
                r"[零一二两三四五六七八九十\d]"
                r"{1,3}分?)?"
            ),
            text,
        )
        if not point:
            return None

        hour = chinese_number(
            point.group("h")
        )
        if hour is None:
            return None

        minute_text = (
            point.group("m")
            or ""
        ).rstrip("分")
        if minute_text == "半":
            minute = 30
        elif minute_text:
            parsed = chinese_number(
                minute_text
            )
            minute = (
                parsed
                if parsed is not None
                else 0
            )
        else:
            minute = 0

        return self._normalize_hour(
            hour,
            minute,
            text,
        )

    @staticmethod
    def _normalize_hour(
        hour: int,
        minute: int,
        text: str,
    ) -> str | None:
        if (
            "下午" in text
            or "晚上" in text
            or "晚饭" in text
        ) and 1 <= hour <= 11:
            hour += 12
        elif (
            (
                "中午" in text
                or "午饭" in text
            )
            and 1 <= hour <= 10
        ):
            hour += 12
        elif (
            (
                "睡觉" in text
                or "睡下" in text
                or "上床" in text
            )
            and not re.search(
                r"(早上|上午|中午|下午|凌晨)",
                text,
            )
            and 6 <= hour <= 11
        ):
            # “11点半叫我睡觉”在没有日间限定时通常指晚间 23:30。
            hour += 12
        elif (
            "凌晨" in text
            and hour == 12
        ):
            hour = 0

        if not (
            0 <= hour <= 23
            and 0 <= minute <= 59
        ):
            return None

        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _detect_slot(
        text: str,
    ) -> str | None:
        if re.search(
            r"(早上|上午|起床)",
            text,
        ):
            return "morning"
        if re.search(
            r"(中午|午饭|午安)",
            text,
        ):
            return "noon"
        if re.search(
            r"(晚上|晚饭|晚安)",
            text,
        ):
            return "evening"
        return None

    def _extract_title(
        self,
        text: str,
    ) -> str:
        if (
            "休息" in text
            and self._extract_relative_delta(
                text
            ) is not None
        ):
            return "结束休息"

        # Lv25: “我忘记取快递了，晚上……再敲我一下”里，
        # 真正需要持久化的是“取快递”，而不是泛化成“主动联系星”。
        # 先从忘记/漏掉的前置事实里恢复动作，再考虑纯主动联系。
        forgotten_action = re.search(
            (
                r"(?:^|[，,。！？!?；;\n])"
                r"(?:我)?(?:刚才|刚刚|今天)?"
                r"(?:忘记|忘了|差点忘了|漏了|没记得)"
                r"(?P<action>[^，,。！？!?；;\n]{1,30})"
            ),
            text,
        )
        if (
            forgotten_action
            and self.REMINDER_PATTERN.search(text)
        ):
            action = clean_schedule_title(
                forgotten_action.group("action")
            )
            action = re.sub(
                r"(?:了|啦|喵)+$",
                "",
                action,
            ).strip(" ，,。！？!?的")
            if action:
                return action

        direct_action = re.search(
            (
                r"(?:提醒我|叫我|喊我|敲我)"
                r"(?:一下)?"
                r"(?P<action>[^，,。！？!?\\n]{1,30})"
            ),
            text,
        )
        if direct_action:
            action = clean_schedule_title(
                direct_action.group("action")
            )
            if action:
                return action

        if self.is_future_message_request(
            text
        ):
            return "主动联系星"

        first_clause = re.split(
            r"[，,。！？!?\n]",
            text,
            maxsplit=1,
        )[0]

        value = re.sub(
            (
                r"(今天|今晚|明天|后天|以后|今后|往后|"
                r"每天|每日|每晚|每夜|每早|"
                r"早上|上午|中午|下午|晚上|"
                r"[零一二两三四五六七八九十百\d]+"
                r"(?:秒|分钟|小时)后|"
                r"\d{1,2}[:：]\d{1,2}|"
                r"[零一二两三四五六七八九十\d]"
                r"{1,3}点(?:半|"
                r"[零一二两三四五六七八九十\d]"
                r"{1,3}分?)?)"
            ),
            "",
            first_clause,
        )
        value = re.sub(
            r"^(?:那|那么)?(?:你)?(?:以后)?"
            r"(?:我要|我得|我会|要|准备|打算)?",
            "",
            value,
        )
        value = re.sub(
            (
                r"(你记得提醒我|"
                r"记得提醒我|提醒我|"
                r"别忘了提醒我|"
                r"叫我(?:一下)?|"
                r"喊我(?:一下)?|"
                r"敲我(?:一下)?)"
            ),
            "",
            value,
        )
        return clean_schedule_title(value)
