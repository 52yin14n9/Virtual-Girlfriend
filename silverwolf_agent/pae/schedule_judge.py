from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timedelta,
)
import json
import re
from typing import Any

from ..llm import (
    BaseLLMClient,
    EchoLLMClient,
    LLMServiceError,
)
from ..models import ChatMessage


ALLOWED_ACTIONS = {
    "none",
    "create_plan",
    "update_time_preference",
    "clarify",
}
ALLOWED_RECURRENCES = {
    "none",
    "daily",
    "weekly",
}
ALLOWED_SLOTS = {
    "morning",
    "noon",
    "evening",
}
CLOCK_PATTERN = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d$"
)


@dataclass
class ModelScheduleJudgement:
    consulted: bool
    accepted: bool
    action: str = "none"
    confidence: float = 0.0
    reason: str = ""
    source: str = "rule_fallback"
    title: str = ""
    due_at: str = ""
    recurrence: str = "none"
    importance: int = 0
    slot: str = ""
    time: str = ""
    purpose: str = ""
    clarification: str = ""
    raw: dict[str, Any] = field(
        default_factory=dict
    )
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelScheduleJudge:
    """
    用大模型做日程语义裁决，但不允许模型直接写数据。

    模型只返回 JSON。程序随后验证动作白名单、时间格式、
    未来时间和置信度，验证通过后 Planner 才会调用工具。
    """

    SCHEDULE_SIGNAL_PATTERN = re.compile(
        (
            r"(提醒|叫我|喊我|敲我|找我|联系我|"
            r"发(?:个|一条)?消息|计划|日程|安排|"
            r"更新.{0,8}时间|修改.{0,8}时间|"
            r"改到|设成|定在|取消|删掉|"
            r"明天|后天|下周|每天|每日|"
            r"\d{1,2}[:：]\d{1,2}|"
            r"[零一二两三四五六七八九十百\d]+"
            r"(?:秒|分钟|小时)后|"
            r"刚刚该做什么|你自己能更新)"
        )
    )

    def __init__(
        self,
        *,
        llm: BaseLLMClient,
        enabled: bool = True,
        minimum_confidence: float = 0.72,
    ) -> None:
        self.llm = llm
        self.enabled = bool(enabled)
        self.minimum_confidence = max(
            0.0,
            min(
                1.0,
                float(minimum_confidence),
            ),
        )

    @property
    def available(self) -> bool:
        return (
            self.enabled
            and not isinstance(
                self.llm,
                EchoLLMClient,
            )
        )

    def should_consult(
        self,
        *,
        text: str,
        recent_messages: list[
            dict[str, str]
        ],
        active_plans: list[
            dict[str, Any]
        ],
    ) -> bool:
        if self.SCHEDULE_SIGNAL_PATTERN.search(
            text
        ):
            return True

        follow_up = bool(
            re.search(
                (
                    r"(你能改吗|你自己能|"
                    r"那就这样|行就这样|"
                    r"刚才那个|之前那个|"
                    r"你是不是忘了|"
                    r"你忘记了吗)"
                ),
                text,
            )
        )
        if not follow_up:
            return False

        if active_plans:
            return True

        recent_text = "\n".join(
            item.get(
                "content",
                "",
            )
            for item in recent_messages[-8:]
        )
        return bool(
            self.SCHEDULE_SIGNAL_PATTERN.search(
                recent_text
            )
        )

    def judge(
        self,
        *,
        text: str,
        now: datetime,
        recent_messages: list[
            dict[str, str]
        ],
        time_settings: dict[str, Any],
        active_plans: list[
            dict[str, Any]
        ],
        rule_hint: dict[str, Any],
    ) -> ModelScheduleJudgement:
        if not self.available:
            return ModelScheduleJudgement(
                consulted=False,
                accepted=False,
                error=(
                    "planner_llm_disabled_or_offline"
                ),
            )

        if not self.should_consult(
            text=text,
            recent_messages=recent_messages,
            active_plans=active_plans,
        ):
            return ModelScheduleJudgement(
                consulted=False,
                accepted=False,
            )

        system = self._system_prompt()
        context = {
            "current_time": now.isoformat(
                timespec="seconds"
            ),
            "timezone": str(
                now.tzinfo
                or ""
            ),
            "user_input": text,
            "recent_messages": (
                self._compact_history(
                    recent_messages
                )
            ),
            "current_time_settings": (
                time_settings
            ),
            "active_plans": (
                active_plans
            ),
            "rule_based_hint": (
                rule_hint
            ),
        }

        try:
            response = self.llm.complete(
                system=system,
                messages=[
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                ],
                tools=None,
            )
            data = self._parse_json(
                response.text
            )
            return self._validate(
                data=data,
                now=now,
            )
        except (
            LLMServiceError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            return ModelScheduleJudgement(
                consulted=True,
                accepted=False,
                source="model_error",
                error=str(exc),
            )

    @staticmethod
    def _compact_history(
        messages: list[
            dict[str, str]
        ],
    ) -> list[dict[str, str]]:
        compact: list[
            dict[str, str]
        ] = []
        for item in messages[-60:]:
            compact.append(
                {
                    "role": str(
                        item.get(
                            "role",
                            "",
                        )
                    ),
                    "content": str(
                        item.get(
                            "content",
                            "",
                        )
                    )[:500],
                }
            )
        return compact

    @staticmethod
    def _system_prompt() -> str:
        return """
你是银狼 Agent 的日程语义裁决器。只负责判断用户这轮话是否需要创建、修改或澄清日程。

必须只输出一个合法 JSON object，不要 Markdown，不要解释性前后缀。

允许的 action：
- none：没有需要持久化或修改的日程动作。
- create_plan：创建一次性或周期性计划。
- update_time_preference：修改 morning/noon/evening 主动关心时间。
- clarify：用户确实想安排任务，但缺少可执行时间。

JSON 格式：
{
  "action": "none|create_plan|update_time_preference|clarify",
  "confidence": 0.0,
  "reason": "简短理由",
  "plan": {
    "title": "简洁动作名称",
    "relative_seconds": 0,
    "due_at": "带时区 ISO 8601；若 relative_seconds>0 可留空",
    "recurrence": "none|daily|weekly",
    "importance": 0
  },
  "time_preference": {
    "slot": "morning|noon|evening",
    "time": "HH:MM",
    "purpose": "例如吃晚饭"
  },
  "clarification": ""
}

判断规则：
1. “更新一下提醒我吃晚饭的时间，我差不多5点40就该吃晚饭了”
   => update_time_preference，slot=evening，time=17:40，purpose=吃晚饭。
   这是修改每日晚间主动关心时间，不是创建明天早上的一次性提醒。
2. “一分钟后叫我一下，我休息一分钟”
   => create_plan，title=结束休息，relative_seconds=60，recurrence=none。
3. “两分钟后给我发个消息”
   => create_plan，title=主动联系星，relative_seconds=120。
4. “我明天可能学 pandas”
   => none。没有明确提醒请求。
5. “我明天要学 pandas，记得提醒我”
   => create_plan。若未给具体时刻，可结合现有 morning 时间。
6. “以后提醒我吃晚饭”但没有时间
   => clarify。
7. “以后你11点半叫我睡觉好不好”
   => create_plan，title=睡觉，recurrence=daily，并把首次 due_at 设为下一个 23:30。
   title 只写动作本身，不要写成“提醒睡觉”“叫我睡觉”等系统式短语。
8. 结合最近对话理解“你自己能更新吗”等追问。
9. 不要把“现在几点”“早睡一般几点睡几点起”“晚饭几点吃比较好”等普通问题判为当前时间或日程。
10. “我忘记取快递了，晚上提醒我吃饭的时候再敲我一下”
   => create_plan，title=取快递；时间沿用 evening/晚饭提醒时间。前半句不是另一个聊天任务，而是在说明这次提醒要做什么。
11. 如果 rule_hint 已经从“忘记 X + 未来提醒/敲我”恢复出具体动作 X，而你只能判断成泛化的“主动联系星”，应优先保留具体动作 X。
12. current_time 是所有相对时间计算的唯一基准。
13. 置信度不足时 action=none，confidence 保持真实，不要硬猜。
""".strip()

    @staticmethod
    def _parse_json(
        value: str,
    ) -> dict[str, Any]:
        cleaned = value.strip()
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

        try:
            data = json.loads(
                cleaned
            )
        except json.JSONDecodeError:
            start = cleaned.find("{")
            if start < 0:
                raise
            data, _ = (
                json.JSONDecoder()
                .raw_decode(
                    cleaned[start:]
                )
            )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Planner JSON 顶层必须是 object"
            )
        return data

    def _validate(
        self,
        *,
        data: dict[str, Any],
        now: datetime,
    ) -> ModelScheduleJudgement:
        action = str(
            data.get(
                "action",
                "none",
            )
        )
        if action not in ALLOWED_ACTIONS:
            raise ValueError(
                f"未知日程 action：{action}"
            )

        confidence = max(
            0.0,
            min(
                1.0,
                float(
                    data.get(
                        "confidence",
                        0.0,
                    )
                ),
            ),
        )
        result = ModelScheduleJudgement(
            consulted=True,
            accepted=(
                confidence
                >= self.minimum_confidence
            ),
            action=action,
            confidence=confidence,
            reason=str(
                data.get(
                    "reason",
                    "",
                )
            )[:300],
            source="model",
            raw=data,
            clarification=str(
                data.get(
                    "clarification",
                    "",
                )
            )[:300],
        )

        if not result.accepted:
            return result

        if action == "none":
            return result

        if action == "clarify":
            if not result.clarification:
                result.clarification = (
                    "告诉我具体要在什么时候提醒。"
                )
            return result

        if action == "update_time_preference":
            pref = data.get(
                "time_preference",
                {},
            )
            if not isinstance(
                pref,
                dict,
            ):
                raise ValueError(
                    "time_preference 必须是 object"
                )

            slot = str(
                pref.get(
                    "slot",
                    "",
                )
            )
            clock = str(
                pref.get(
                    "time",
                    "",
                )
            )
            if slot not in ALLOWED_SLOTS:
                raise ValueError(
                    "模型返回了非法时间槽"
                )
            if not CLOCK_PATTERN.fullmatch(
                clock
            ):
                raise ValueError(
                    "模型返回了非法 HH:MM"
                )

            result.slot = slot
            result.time = clock
            result.purpose = str(
                pref.get(
                    "purpose",
                    "",
                )
            )[:80]
            return result

        plan = data.get(
            "plan",
            {},
        )
        if not isinstance(
            plan,
            dict,
        ):
            raise ValueError(
                "plan 必须是 object"
            )

        title = str(
            plan.get(
                "title",
                "",
            )
        ).strip()[:60]
        if not title:
            raise ValueError(
                "计划标题不能为空"
            )

        recurrence = str(
            plan.get(
                "recurrence",
                "none",
            )
        )
        if recurrence not in (
            ALLOWED_RECURRENCES
        ):
            raise ValueError(
                "模型返回了非法 recurrence"
            )

        relative_seconds = int(
            plan.get(
                "relative_seconds",
                0,
            )
            or 0
        )
        if relative_seconds > 0:
            if relative_seconds > (
                366 * 24 * 3600
            ):
                raise ValueError(
                    "相对时间超过一年"
                )
            due = now + timedelta(
                seconds=relative_seconds
            )
        else:
            due_raw = str(
                plan.get(
                    "due_at",
                    "",
                )
            )
            due = datetime.fromisoformat(
                due_raw
            )
            if due.tzinfo is None:
                due = due.replace(
                    tzinfo=now.tzinfo
                )
            due = due.astimezone(
                now.tzinfo
            )

        if due <= now:
            raise ValueError(
                "模型返回的计划时间不在未来"
            )
        if due > now + timedelta(
            days=366 * 5
        ):
            raise ValueError(
                "模型返回的计划时间过远"
            )

        result.title = title
        result.due_at = due.isoformat(
            timespec=(
                "microseconds"
                if due.microsecond
                else "seconds"
            )
        )
        result.recurrence = recurrence
        result.importance = max(
            0,
            min(
                100,
                int(
                    plan.get(
                        "importance",
                        80,
                    )
                ),
            ),
        )
        return result
