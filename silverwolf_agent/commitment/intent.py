"""Lv27: 长期任务承诺的确定性识别层。

这里只做"能从字面确定下来的东西"，不做猜测：

* 这句话是不是一项**每周重复**的长期任务；
* 它已经说清了哪些槽位（开始时间 / 钟点 / 周几 / 几周）；
* 用户是在补全、改口、跳过、还是要结束这项承诺。

任何缺失的部分都交给 `ClarificationSession` 去问，绝不默认补全。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re

from .contracts import (
    SLOT_CLOCK,
    SLOT_START,
    SLOT_WEEKDAYS,
    SLOT_WEEKS,
    CommitmentSeed,
)

_CN_DIGITS = {
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


def chinese_number(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        if left and left not in _CN_DIGITS:
            return None
        if right and right not in _CN_DIGITS:
            return None
        return tens * 10 + ones
    if len(text) == 1 and text in _CN_DIGITS:
        return _CN_DIGITS[text]
    return None


class CommitmentIntentAnalyzer:
    """识别长期承诺，并抽取已经说清的槽位。"""

    # 每周重复信号：没有这些词就不当长期承诺，避免把一次性提醒误升级。
    ROUTINE_PATTERN = re.compile(
        r"(以后每(?:个)?(?:周|星期)|今后每(?:个)?(?:周|星期)|"
        r"每(?:个)?(?:周|星期)|每周|每周末|"
        r"以后每周|之后每周|往后每周)"
    )

    ACTION_PATTERN = re.compile(
        r"(学习|复习|背单词|背|刷题|练习|练|上课|听课|看视频|视频|网课|课程|"
        r"读书|读完|阅读|写作|写代码|做项目|做作业|作业|打卡|训练|健身|跑步|"
        r"锻炼|背课文|准备考试|刷课|追课)"
    )

    UNCERTAIN_PATTERN = re.compile(r"(可能|也许|看情况|有空再|不一定|考虑一下)")

    # "我以后每周的周末打算完成创新创业基础的视频学习"
    TITLE_PREFIX_PATTERN = re.compile(
        r"^\s*(?:"
        r"(?:我|咱|咱们)?\s*"
        r"(?:以后|今后|之后|往后|接下来|这段时间)?\s*"
        r"(?:每(?:个)?(?:周的)?(?:周[末六日天]|星期[六日天末]|周[一二三四五]|星期[一二三四五]|工作日)?)?\s*"
        r"(?:都|也)?\s*"
        r"(?:要|打算|计划|准备|想|会|得|需要)?\s*"
        r"(?:去|开始)?\s*"
        r")"
    )

    TITLE_TRAILER_PATTERN = re.compile(
        r"(?:，|,)?\s*(?:你|请)?\s*(?:记得|要记得)?\s*"
        r"(?:提醒我|叫我|盯着我|监督我|喊我)[^。！？!?]*[。！？!?]?\s*$"
    )

    WEEKEND_PATTERN = re.compile(r"(周末|双休)")
    SATURDAY_PATTERN = re.compile(r"(周六|星期六|礼拜六)")
    SUNDAY_PATTERN = re.compile(r"(周日|周天|星期日|星期天|礼拜天|礼拜日)")
    WEEKDAY_RANGE_PATTERN = re.compile(
        r"(?:周|星期|礼拜)([一二三四五])\s*(?:到|至|-|~)\s*(?:周|星期|礼拜)([一二三四五])"
    )
    WORKDAY_PATTERN = re.compile(r"(工作日|周一到周五|星期一到星期五)")

    CLOCK_PATTERN = re.compile(
        r"(?P<period>凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|今晚|明早)?\s*"
        r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})"
        r"\s*(?:点|时)"
        r"(?:\s*(?P<half>半)|(?:\s*(?P<minute>\d{1,2})\s*分?))?"
    )
    ISO_CLOCK_PATTERN = re.compile(
        r"(?<![\d:])(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2})(?![\d:])"
    )

    WEEKS_PATTERN = re.compile(
        r"(?P<value>\d{1,3}|[零一二两三四五六七八九十]{1,3})\s*"
        r"(?:个)?\s*(?:周|星期|礼拜)"
        r"(?![末六日天一二三四五])"
    )
    MONTHS_PATTERN = re.compile(
        r"(?P<value>\d{1,2}|[一二两三四五六七八九十]{1,3})\s*个?\s*月"
    )

    START_THIS_WEEK_PATTERN = re.compile(
        r"(这周|本周|这个星期|这礼拜|从现在|今天开始|从今天)"
    )
    START_NEXT_WEEK_PATTERN = re.compile(
        r"(下周|下个星期|下礼拜|从下周|明天开始|从明天)"
    )

    SKIP_PATTERN = re.compile(
        r"((这|本|那)(?:周|次|回)|今天|这礼拜)?\s*(先|就)?\s*"
        r"(跳过|跳一期|略过|不算|顺延|挪到下周|改下周)"
    )
    FINISH_PATTERN = re.compile(
        r"(做完了|学完了|看完|搞定了|完成了|弄完了|打卡完成|今天做完了|已经做完)"
    )
    CANCEL_PATTERN = re.compile(
        r"(不学了|不想学|不做了|不弄了|不搞了|先不弄|先别弄|先不排|"
        r"取消(?:这个|这项|掉|了)?|别提醒了|停掉|放弃|算了)"
    )
    EDIT_PATTERN = re.compile(
        r"(改成|换成|改成每周|调整成|变成)"
    )

    # ---------- 主入口 ----------

    def detect(
        self,
        text: str,
        now: datetime,
    ) -> CommitmentSeed | None:
        """识别一句长期承诺，返回只含已知槽位的 seed。"""
        cleaned = text.strip()
        if not cleaned:
            return None
        if self.UNCERTAIN_PATTERN.search(cleaned):
            return None
        if not self.ROUTINE_PATTERN.search(cleaned):
            return None
        if not self.ACTION_PATTERN.search(cleaned):
            return None

        title = self.extract_title(cleaned)
        if not title:
            return None

        slots = self.extract_slots(cleaned, now)
        return CommitmentSeed(
            title=title,
            source_text=cleaned,
            weekdays=tuple(slots.get("weekdays", ())),
            clock=str(slots.get("clock", "")),
            weeks=int(slots.get("weeks", 0) or 0),
            starts_on=str(slots.get("starts_on", "")),
            soft_weekend=bool(slots.get("soft_weekend", False)),
        )

    def extract_title(self, text: str) -> str:
        body = self.ROUTINE_PATTERN.sub(" ", text, count=1)
        body = self.TITLE_TRAILER_PATTERN.sub("", body)
        # 先去掉“我/咱、以后、打算”这类前缀，再清残留的“的周末/周X”，
        # 否则锚点匹配会因为前面还有字而失效。
        body = self.TITLE_PREFIX_PATTERN.sub("", body)
        body = re.sub(
            r"^(?:我|咱|咱们)?\s*(?:以后|今后|之后|往后|接下来)?\s*",
            "",
            body,
        )
        body = re.sub(
            r"^\s*(?:的)?\s*(?:每?周(?:的)?(?:周末|周[一二三四五六日天末])"
            r"|每?星期(?:[一二三四五六日天末]|末)"
            r"|每?礼拜(?:[一二三四五六日天末]|末)"
            r"|周末|工作日)\s*",
            "",
            body,
        )
        body = re.sub(r"^(?:打算|计划|准备|要|想|会|得|需要|去|开始)+", "", body)
        body = re.sub(r"^(?:完成|做完|搞定|把)+", "", body)
        body = body.lstrip(" 的")
        body = body.strip(" ，,。！？!?、~～")
        body = re.sub(r"\s+", "", body)
        if len(body) > 40:
            body = body[:40]
        return body

    def extract_slots(
        self,
        text: str,
        now: datetime,
    ) -> dict[str, object]:
        """从一句话里尽可能抽取四个槽位；抽不到就不写。"""
        slots: dict[str, object] = {}

        weekdays, soft = self._extract_weekdays(text)
        if weekdays:
            slots["weekdays"] = weekdays
            slots["soft_weekend"] = soft

        clock = self._extract_clock(text)
        if clock:
            slots[SLOT_CLOCK] = clock

        weeks = self._extract_weeks(text)
        if weeks:
            slots[SLOT_WEEKS] = weeks

        start = self._extract_start(text)
        if start:
            slots[SLOT_START] = start

        return slots

    def apply_slots(
        self,
        seed: CommitmentSeed,
        text: str,
        now: datetime,
    ) -> CommitmentSeed:
        """把用户这一轮回答合并进已有 seed（后说的覆盖先说的）。"""
        slots = self.extract_slots(text, now)
        if "weekdays" in slots:
            seed.weekdays = tuple(slots["weekdays"])  # type: ignore[arg-type]
            seed.soft_weekend = bool(slots.get("soft_weekend", False))
        if SLOT_CLOCK in slots:
            seed.clock = str(slots[SLOT_CLOCK])
        if SLOT_WEEKS in slots:
            seed.weeks = int(slots[SLOT_WEEKS])
        if SLOT_START in slots:
            seed.starts_on = str(slots[SLOT_START])
        return seed

    # ---------- 槽位抽取 ----------

    def _extract_weekdays(
        self,
        text: str,
    ) -> tuple[tuple[int, ...], bool]:
        if self.WORKDAY_PATTERN.search(text):
            return (0, 1, 2, 3, 4), False

        range_match = self.WEEKDAY_RANGE_PATTERN.search(text)
        if range_match:
            start_char = range_match.group(1)
            end_char = range_match.group(2)
            table = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4}
            left = table.get(start_char)
            right = table.get(end_char)
            if left is not None and right is not None and left <= right:
                return tuple(range(left, right + 1)), False

        days: set[int] = set()
        soft = False
        if self.WEEKEND_PATTERN.search(text):
            # "周末"是柔性约定：两天都可以，完成一次就算这周做到。
            days.update({5, 6})
            soft = True
        if self.SATURDAY_PATTERN.search(text):
            days.add(5)
        if self.SUNDAY_PATTERN.search(text):
            days.add(6)

        # 单独的“周六/周天”也覆盖“周末”柔性：用户点名某一天就不是柔性。
        named = self.SATURDAY_PATTERN.search(text) or self.SUNDAY_PATTERN.search(text)
        if named and "周末" not in text:
            soft = False

        return tuple(sorted(days)), soft

    def _extract_clock(self, text: str) -> str:
        iso = self.ISO_CLOCK_PATTERN.search(text)
        if iso:
            hour = int(iso.group("hour"))
            minute = int(iso.group("minute"))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"

        # “周六十点”里 “六十” 会被贪心读成 60 点。遇到非法读数时从下一个
        # 字符重新找，而不是直接放弃整句。
        position = 0
        while position < len(text):
            match = self.CLOCK_PATTERN.search(text, position)
            if not match:
                return ""
            parsed = self._clock_from_match(match)
            if parsed:
                return parsed
            position = match.start() + 1
        return ""

    def _clock_from_match(self, match: re.Match[str]) -> str:
        hour = chinese_number(match.group("hour"))
        if hour is None:
            return ""
        period = match.group("period") or ""
        if match.group("half"):
            minute = 30
        elif match.group("minute"):
            minute = int(match.group("minute"))
        else:
            minute = 0
        if not 0 <= minute <= 59:
            minute = 0

        if period in {"下午", "傍晚", "晚上", "夜里", "今晚"} and 1 <= hour <= 11:
            hour += 12
        elif period in {"凌晨", "早上", "早晨", "上午", "明早"} and hour == 12:
            hour = 0
        elif period == "中午" and 1 <= hour <= 2:
            hour += 12
        if not 0 <= hour <= 23:
            return ""
        return f"{hour:02d}:{minute:02d}"

    def _extract_weeks(self, text: str) -> int:
        for match in self.WEEKS_PATTERN.finditer(text):
            raw = match.group("value")
            # “每周六”里的数字会紧跟在“周”后面，正则已用否定前瞻挡掉。
            value = chinese_number(raw)
            if value is None:
                continue
            if 1 <= value <= 104:
                return value
        month_match = self.MONTHS_PATTERN.search(text)
        if month_match:
            value = chinese_number(month_match.group("value"))
            if value and 1 <= value <= 24:
                return value * 4
        return 0

    def _extract_start(self, text: str) -> str:
        if self.START_NEXT_WEEK_PATTERN.search(text):
            return "next_week"
        if self.START_THIS_WEEK_PATTERN.search(text):
            return "this_week"
        return ""

    # ---------- 承诺状态操作 ----------

    def wants_finish(self, text: str) -> bool:
        return bool(self.FINISH_PATTERN.search(text.strip()))

    def wants_skip(self, text: str) -> bool:
        return bool(self.SKIP_PATTERN.search(text.strip()))

    def wants_cancel(self, text: str) -> bool:
        return bool(self.CANCEL_PATTERN.search(text.strip()))

    def wants_edit(self, text: str) -> bool:
        return bool(self.EDIT_PATTERN.search(text.strip()))

    def looks_like_slot_answer(
        self,
        text: str,
        now: datetime,
    ) -> bool:
        """澄清等待中：这一句是否携带任何可用的槽位信息。"""
        slots = self.extract_slots(text, now)
        return bool(slots)


def resolve_start_date(
    anchor: str,
    *,
    weekdays: tuple[int, ...],
    clock: str,
    now: datetime,
) -> date:
    """把 this_week / next_week / ISO 日期解析成真实的第一次日期。"""
    weekdays = weekdays or (5, 6)
    today = now.date()

    try:
        explicit = date.fromisoformat(anchor)
        return explicit
    except ValueError:
        pass

    first_weekday = min(weekdays)
    days_ahead = (first_weekday - today.weekday()) % 7
    candidate = today + timedelta(days=days_ahead)

    if anchor == "next_week":
        if candidate <= today:
            return candidate + timedelta(days=7)
        return candidate + timedelta(days=7)

    if anchor == "this_week":
        # 本周：如果该日已过，或就是今天而时间已过，则顺延到下周。
        if candidate < today:
            return candidate + timedelta(days=7)
        if candidate == today and clock:
            try:
                hour, minute = (int(part) for part in clock.split(":", 1))
                if (now.hour, now.minute) >= (hour, minute):
                    return candidate + timedelta(days=7)
            except (ValueError, TypeError):
                pass
        return candidate

    return candidate
