from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any


WEEKDAY_CN = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}

WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


@dataclass(frozen=True)
class TemporalQuery:
    """A deterministic interpretation of a clock or calendar question."""

    kind: str
    source_text: str
    target_date: str = ""
    relation_label: str = ""
    include_year: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemporalQueryAnalyzer:
    """Recognize Chinese time/date/weekday questions without using an LLM."""

    CLOCK_PATTERN = re.compile(
        r"^(?:(?:对了|顺便|那|那么)?"
        r"(?:你)?(?:看|看看|告诉我|说说)?"
        r"(?:现在|当前|这会儿|这时候)?(?:是)?"
        r"(?:几点(?:了|啦|啊|呀|呢)?|"
        r"什么时间(?:了|啦|啊|呀|呢)?|"
        r"时间(?:是)?多少(?:了|啦|啊|呀|呢)?))$"
    )
    WEEKDAY_QUESTION_PATTERN = re.compile(
        r"(?:星期|周|礼拜)\s*[几幾]"
        r"|是\s*(?:星期|周|礼拜)\s*[几幾]"
    )
    DATE_QUESTION_PATTERN = re.compile(
        r"几号|幾號|几月几(?:日|号)|幾月幾(?:日|號)|"
        r"(?:今天|明天|后天|大后天|昨天|前天|这天|那天)?\s*日期"
        r"|(?:具体)?哪天"
    )
    FULL_DATE_PATTERN = re.compile(
        r"(?P<year>20\d{2})\s*年\s*"
        r"(?P<month>\d{1,2})\s*月\s*"
        r"(?P<day>\d{1,2})\s*(?:日|号)?"
    )
    MONTH_DAY_PATTERN = re.compile(
        r"(?<!\d)(?P<month>\d{1,2})\s*月\s*"
        r"(?P<day>\d{1,2})\s*(?:日|号)"
    )
    WEEK_REFERENCE_PATTERN = re.compile(
        r"(?P<prefix>下周|下星期|下礼拜|"
        r"这周|本周|这个星期|本星期|这星期|这个礼拜|本礼拜)"
        r"\s*(?P<weekday>[一二三四五六日天])"
    )
    SIMPLE_CURRENT_CALENDAR_PATTERN = re.compile(
        r"(?:现在|当前|今天)?(?:是)?"
        r"(?:"
        r"(?:星期|周|礼拜)[几幾]"
        r"|几号|幾號|几月几(?:日|号)|幾月幾(?:日|號)|日期"
        r"|(?:几号|幾號|几月几(?:日|号)|幾月幾(?:日|號))"
        r"(?:星期|周|礼拜)[几幾]"
        r")"
        r"(?:啊|呀|呢|啦|了)?"
    )

    RELATIVE_DAYS = (
        ("大后天", 3),
        ("后天", 2),
        ("明天", 1),
        ("今天", 0),
        ("昨天", -1),
        ("前天", -2),
    )

    @classmethod
    def is_temporal_question(cls, text: str) -> bool:
        value = cls._normalize(text)
        return bool(
            cls._contains_current_clock_question(text)
            or cls.WEEKDAY_QUESTION_PATTERN.search(value)
            or cls.DATE_QUESTION_PATTERN.search(value)
        )

    @classmethod
    def analyze(
        cls,
        text: str,
        now: datetime,
    ) -> TemporalQuery | None:
        value = cls._normalize(text)
        asks_weekday = bool(
            cls.WEEKDAY_QUESTION_PATTERN.search(value)
        )
        asks_date = bool(
            cls.DATE_QUESTION_PATTERN.search(value)
        )

        if not asks_weekday and not asks_date:
            if cls._contains_current_clock_question(text):
                return TemporalQuery(
                    kind="time",
                    source_text=text.strip(),
                )
            return None

        has_explicit_anchor = bool(
            cls.FULL_DATE_PATTERN.search(value)
            or cls.MONTH_DAY_PATTERN.search(value)
            or cls.WEEK_REFERENCE_PATTERN.search(value)
            or any(label in value for label, _ in cls.RELATIVE_DAYS)
        )
        if (
            not has_explicit_anchor
            and not cls.SIMPLE_CURRENT_CALENDAR_PATTERN.fullmatch(value)
        ):
            return None

        target, relation, include_year = cls._resolve_date(value, now.date())
        if target is None:
            return None

        if asks_weekday and asks_date:
            kind = "date_weekday"
        elif asks_weekday:
            kind = "weekday"
        else:
            kind = "date"

        return TemporalQuery(
            kind=kind,
            source_text=text.strip(),
            target_date=target.isoformat(),
            relation_label=relation,
            include_year=include_year,
        )

    @classmethod
    def _contains_current_clock_question(
        cls,
        text: str,
    ) -> bool:
        """
        只把“询问当前钟点”的独立语义片段交给时间工具。

        “几点”也常出现在作息、建议、行程等知识/计划问题中，
        例如“早睡早起一般几点睡几点起”。这些问题不能因为
        含有“几点”就被降级成只返回当前 HH:MM。
        """
        clauses = [
            item
            for item in re.split(
                r"[，,。！？!?；;\n]+",
                text,
            )
            if item.strip()
        ]
        for clause in clauses:
            value = re.sub(
                r"\s+",
                "",
                clause.strip(),
            )
            if cls.CLOCK_PATTERN.fullmatch(
                value
            ):
                return True
        return False

    @classmethod
    def _resolve_date(
        cls,
        text: str,
        today: date,
    ) -> tuple[date | None, str, bool]:
        full = cls.FULL_DATE_PATTERN.search(text)
        if full:
            try:
                target = date(
                    int(full.group("year")),
                    int(full.group("month")),
                    int(full.group("day")),
                )
            except ValueError:
                return None, "", False
            return target, full.group(0).strip(), True

        month_day = cls.MONTH_DAY_PATTERN.search(text)
        if month_day:
            try:
                target = date(
                    today.year,
                    int(month_day.group("month")),
                    int(month_day.group("day")),
                )
            except ValueError:
                return None, "", False
            return target, month_day.group(0).strip(), False

        week_match = cls.WEEK_REFERENCE_PATTERN.search(text)
        if week_match:
            prefix = week_match.group("prefix")
            target_weekday = WEEKDAY_INDEX[week_match.group("weekday")]
            monday = today - timedelta(days=today.weekday())
            if prefix.startswith("下"):
                monday += timedelta(days=7)
            target = monday + timedelta(days=target_weekday)
            return target, week_match.group(0).strip(), False

        for label, offset in cls.RELATIVE_DAYS:
            if label in text:
                return today + timedelta(days=offset), label, False

        return today, "今天", False

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(
            r"[？?！!。,.，；;\s]+",
            "",
            text.strip(),
        )
