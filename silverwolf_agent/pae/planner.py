from __future__ import annotations

from datetime import datetime
import re

from .contracts import (
    ConversationPlan,
    DeliveryPolicy,
    MemoryRequest,
    ResponseGoal,
    ToolRequest,
)
from .schedule_judge import (
    ModelScheduleJudge,
)
from ..cognition import CognitiveStateManager
from ..memory.profile import (
    UserProfileManager,
)
from ..memory.agent_identity import (
    AgentIdentityManager,
)
from ..memory.short_term import (
    ShortTermMemory,
)
from ..proactive.contracts import (
    ScheduleDecision,
)
from ..proactive.plan_manager import (
    PlanManager,
)
from ..proactive.schedule_intent import (
    ScheduleIntentAnalyzer,
    clean_schedule_title,
)
from ..proactive.time_manager import (
    TimeManager,
)
from ..world import Lv17IntentAnalyzer, WorldContextManager
from ..temporal import TemporalQueryAnalyzer


class ConversationPlanner:
    """
    lv15 PAE Planner。

    Planner 负责：
    - 拆分一轮中的多个语义目标；
    - 为每个目标分配内容权重；
    - 判断消息是否适合拆开发送；
    - 判断是否需要工具、RAG；
    - 判断一个未来事项是否重要到
      值得进入持久计划。
    """

    TIME_PATTERN = re.compile(
        (
            r"(现在|当前|这会儿|这时候).{0,6}"
            r"(几点|时间)"
            r"|几点了"
            r"|看看几点"
            r"|什么时间了"
        )
    )

    HISTORY_TIME_PATTERN = re.compile(
        (
            r"(刚才|之前|一开始|开始).{0,18}"
            r"(问|说|休息|学习|工作|开发|时候)"
            r".{0,12}(时间|几点|时候)"
            r"|我说的是我开始.{1,12}的时候"
            r"|我开始.{1,12}的时候"
        )
    )

    SELF_IDENTITY_PATTERN = re.compile(
        (
            r"^(?:那|那么|所以|可是|但是)?"
            r"(?:"
            r"你是谁"
            r"|你是什么(?:人|身份)?"
            r"|你(?:到底|究竟)?是"
            r"(?:真人|人类|人|AI|ai|人工智能|机器人)"
            r"(?:还是|或是|或者)"
            r"(?:真人|人类|人|AI|ai|人工智能|机器人)"
            r"|你是(?:真人|人类|人|AI|ai|人工智能|机器人)吗"
            r"|你不是(?:真人|人类|人|AI|ai|人工智能|机器人)吗"
            r"|你是不是(?:真人|人类|人|AI|ai|人工智能|机器人)"
            r"|你真的是银狼吗(?:.*)?"
            r"|你是银狼吗"
            r"|你是不是银狼"
            r")"
            r"[？?。！!]*$"
        )
    )

    SELF_ZODIAC_PATTERN = re.compile(
        (
            r"(你(?:的)?(?:星座|什么星座)"
            r"|你是哪个星座"
            r"|你是什么星座)"
        )
    )

    SELF_AGE_PATTERN = re.compile(
        (
            r"(你(?:现在|今年)?(?:多大|几岁|多少岁)"
            r"|你的年龄(?:是多少|多大)?"
            r"|你年龄(?:是多少|多大)?"
            r"|你现在是\d+岁吗)"
        )
    )

    SELF_NEXT_BIRTHDAY_AGE_PATTERN = re.compile(
        (
            r"((?:明年|下次|下一次).{0,10}"
            r"生日.{0,10}(?:几岁|多大|多少岁)"
            r"|(?:明年|下次|下一次).{0,10}"
            r"(?:几岁|多大|多少岁)"
            r"|过(?:完)?生日.{0,8}"
            r"(?:几岁|多大|多少岁))"
        )
    )

    SELF_BIRTHDAY_PATTERN = re.compile(
        (
            r"(你(?:的)?生日(?:是|在|什么时候|哪天|几月几日)?"
            r"|你哪天生日"
            r"|你几月(?:几日|几号)生日"
            r"|生日是几月(?:几日|几号))"
        )
    )

    SELF_QQ_NICKNAME_PATTERN = re.compile(
        r"(?:你的|你)?QQ(?:昵称|名字|叫什么)|(?:QQ昵称|QQ名字)(?:是什么|叫什么)?"
    )

    SELF_QQ_SIGNATURE_PATTERN = re.compile(
        r"(?:你的|你)?QQ(?:个性)?签名|(?:个性签名|QQ签名)(?:是什么|写的什么)?"
    )

    SELF_QQ_ACCOUNT_PATTERN = re.compile(
        r"(?:你有QQ吗|这是你的QQ吗|这个QQ是你的吗|你的QQ账号|你QQ号是多少|你的QQ号)"
    )

    IDENTITY_PATTERN = re.compile(
        (
            r"^(?:那|那么|所以)?"
            r"(?:你)?(?:还)?记得我"
            r"(?:吗|不|么)?"
            r"[？?。！!]*$"
            r"|^(?:那|那么|所以)?"
            r"(?:你知道)?我是谁"
            r"(?:吗)?"
            r"[？?。！!]*$"
        )
    )

    ADDRESS_PATTERN = re.compile(
        (
            r"(你平常会叫我什么|"
            r"你平时叫我什么|"
            r"你会怎么叫我|"
            r"你一般叫我什么|"
            r"你叫我什么)"
        )
    )

    NAME_PATTERNS = (
        re.compile(
            (
                r"(?:那你记住了[，, ]*)?"
                r"(?:以后|之后)"
                r"(?:你)?(?:就)?(?:可以)?"
                r"叫我"
                r"(?P<name>"
                r"[^。！？!?，,\n]{1,20})"
                r"[。！？!?]?$"
            )
        ),
        re.compile(
            (
                r"(?:你可以|可以)"
                r"(?:以后)?叫我"
                r"(?P<name>"
                r"[^。！？!?，,\n]{1,20})"
                r"[。！？!?]?$"
            )
        ),
    )

    PAST_EVENT_PATTERN = re.compile(
        (
            r"(我们之前|以前发生|过去发生|"
            r"上次|前几天|之前聊过|"
            r"回忆一下|还记得.*发生|"
            r"那天我们)"
        )
    )

    PROFILE_DETAIL_PATTERN = re.compile(
        (
            r"(你记得我哪些|"
            r"你还记得我什么|"
            r"你对我了解多少|"
            r"说说你记得的我)"
        )
    )

    CORRECTION_MARKERS = (
        "我已经",
        "我都",
        "我刚",
        "其实",
        "只是",
        "不是",
        "早就",
        "都睡",
        "已经吃",
        "吃过了",
        "睡好",
        "睡完",
    )

    USER_STATE_PREDICATE_PATTERN = re.compile(
        (
            r"(睡|睡得|午觉|吃|忙|开发|学习|工作|"
            r"写代码|做项目|感觉|觉得|开心|难过|"
            r"累|困|晕|烦|舒服|不错|不舒服|焦虑|"
            r"兴奋|忘记|记不住|头疼|生病|状态|精神|"
            r"休息|放松|紧张|压力|专注)"
        )
    )

    USER_STATE_CONTEXT_PATTERN = re.compile(
        (
            r"(^我|自己|今天|刚才|刚刚|最近|这会儿|"
            r"这段时间|中午|上午|下午|晚上|昨晚|"
            r"一直在|总是|有点|挺|很|不太)"
        )
    )

    DIRECT_STATE_PATTERN = re.compile(
        (
            r"^(?:好|挺|很|有点|不太)?"
            r"(?:累|困|晕晕的|晕|烦|开心|难过|舒服|"
            r"不舒服|焦虑|兴奋|紧张|放松)"
            r"(?:的|了)?$"
        )
    )

    DISCOURSE_ONLY_PATTERN = re.compile(
        r"^(?:对了|顺便|然后|还有|那|那么|所以)$"
    )

    FUTURE_PLAN_PATTERN = re.compile(
        (
            r"(明天|后天|下周|以后|每天|准备|打算|"
            r"计划|提醒我|记得提醒|到时候|要去|要学|"
            r"要做|会去|会学|会做)"
        )
    )

    def __init__(
        self,
        profile: UserProfileManager,
        memory: ShortTermMemory,
        time_manager: TimeManager,
        plan_manager: PlanManager,
        message_gap_seconds: float = 0.9,
        agent_identity: (
            AgentIdentityManager
            | None
        ) = None,
        schedule_judge: (
            ModelScheduleJudge
            | None
        ) = None,
        lv17_intent_analyzer: (
            Lv17IntentAnalyzer
            | None
        ) = None,
        world_context: (
            WorldContextManager
            | None
        ) = None,
        cognition: (
            CognitiveStateManager
            | None
        ) = None,
        commitment_service: object | None = None,
    ) -> None:
        self.profile = profile
        self.memory = memory
        self.agent_identity = (
            agent_identity
            or AgentIdentityManager()
        )
        self.time_manager = (
            time_manager
        )
        self.plan_manager = (
            plan_manager
        )
        self.schedule_analyzer = (
            ScheduleIntentAnalyzer(
                time_manager
            )
        )
        self.schedule_judge = (
            schedule_judge
        )
        self.lv17_intent_analyzer = (
            lv17_intent_analyzer
            or Lv17IntentAnalyzer()
        )
        self.world_context = world_context
        self.cognition = cognition
        self.commitment = commitment_service
        self.message_gap_seconds = (
            message_gap_seconds
        )

    def plan(
        self,
        user_input: str,
        now: datetime,
    ) -> ConversationPlan:
        text = user_input.strip()
        if not text:
            raise ValueError(
                "Planner 收到空输入"
            )

        cognitive_context = (
            self.cognition.prepare_turn(text, now)
            if self.cognition is not None
            else {}
        )
        cognitive_intent = (
            cognitive_context.get("intent", {})
            if isinstance(cognitive_context, dict)
            else {}
        )
        if not isinstance(cognitive_intent, dict):
            cognitive_intent = {}

        lv17_intents = (
            self.lv17_intent_analyzer
            .analyze(text, now)
        )
        if self.world_context is not None:
            interaction_prefs = self.world_context.interaction_preferences(now)
            if not interaction_prefs.get("event_follow_up_enabled", True):
                lv17_intents = [
                    intent
                    for intent in lv17_intents
                    if not (
                        intent.kind == "create_event_follow_up"
                        and not bool(intent.arguments.get("explicit_request", False))
                    )
                ]
        # Lv27: 长期任务承诺（多周课程 / 习惯类任务）优先于一次性日程判断。
        # 用户往往说不全，这里只负责识别 + 追问，绝不替用户假设参数。
        commitment_turn = None
        if self.commitment is not None:
            commitment_turn = self.commitment.handle(
                text,
                now,
                alias=self.profile.casual_alias(),
            )
            if commitment_turn.mode == "none":
                commitment_turn = None

        preferred_name = (
            self._extract_preferred_name(
                text
            )
        )
        history_time_request = (
            self._history_time_request(
                text
            )
        )
        temporal_query = (
            TemporalQueryAnalyzer.analyze(
                text,
                now,
            )
            if history_time_request is None
            else None
        )
        is_time = bool(
            temporal_query is not None
            and temporal_query.kind == "time"
        )
        is_calendar = bool(
            temporal_query is not None
            and temporal_query.kind in {
                "date",
                "weekday",
                "date_weekday",
            }
        )
        is_temporal = bool(
            is_time or is_calendar
        )
        is_identity = bool(
            self.IDENTITY_PATTERN.fullmatch(
                text
            )
        )
        is_address = bool(
            self.ADDRESS_PATTERN.search(
                text
            )
        )
        is_past_event = bool(
            self.PAST_EVENT_PATTERN.search(
                text
            )
        )
        asks_profile_details = bool(
            self.PROFILE_DETAIL_PATTERN.search(
                text
            )
        )
        asks_self_identity = bool(
            self.SELF_IDENTITY_PATTERN.fullmatch(
                text
            )
        )
        asks_self_zodiac = bool(
            self.SELF_ZODIAC_PATTERN.search(
                text
            )
        )

        asks_next_birthday_age = bool(
            self.SELF_NEXT_BIRTHDAY_AGE_PATTERN.search(
                text
            )
        )
        asks_self_age = bool(
            self.SELF_AGE_PATTERN.search(
                text
            )
            and not asks_next_birthday_age
        )
        asks_self_birthday = bool(
            self.SELF_BIRTHDAY_PATTERN.search(
                text
            )
        )

        asks_self_qq_nickname = bool(
            self.SELF_QQ_NICKNAME_PATTERN.search(
                text
            )
        )
        asks_self_qq_signature = bool(
            self.SELF_QQ_SIGNATURE_PATTERN.search(
                text
            )
        )
        asks_self_qq_account = bool(
            self.SELF_QQ_ACCOUNT_PATTERN.search(
                text
            )
            and not asks_self_qq_nickname
            and not asks_self_qq_signature
        )

        if commitment_turn is not None:
            # 正在补全或刚确认长期承诺时，这一轮不做一次性日程解析，
            # 避免同一句话同时生成"提醒我"计划和"追问参数"两种回复。
            time_preference = None
            wants_plan_list = False
            cancellation_query = None
            schedule_decision = ScheduleDecision(
                should_persist=False,
                importance=0,
                reason="Lv27 长期承诺澄清/确认优先",
                source_text=text,
            )
            future_message_request = False
        else:
            time_preference = (
                self.schedule_analyzer
                .analyze_time_preference(
                    text
                )
            )
            wants_plan_list = (
                self.schedule_analyzer
                .wants_plan_list(text)
            )
            cancellation_query = (
                self.schedule_analyzer
                .cancellation_query(text)
            )
            if any(
                intent.kind
                == "cancel_event_follow_up"
                for intent in lv17_intents
            ):
                cancellation_query = None

            schedule_decision = (
                self.schedule_analyzer
                .analyze(text, now)
            )
            future_message_request = (
                self.schedule_analyzer
                .is_future_message_request(
                    text
                )
            )
        active_plans = [
            {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "due_at": plan.due_at,
                "importance": (
                    plan.importance
                ),
                "status": plan.status,
            }
            for plan in (
                self.plan_manager
                .list_plans(
                    active_only=True
                )[:10]
            )
        ]

        model_judgement = None
        if self.schedule_judge is not None and commitment_turn is None:
            model_judgement = (
                self.schedule_judge.judge(
                    text=text,
                    now=now,
                    recent_messages=(
                        self.memory
                        .recent_chat_messages(
                            limit=30
                        )
                    ),
                    time_settings=(
                        self.time_manager
                        .snapshot()
                    ),
                    active_plans=(
                        active_plans
                    ),
                    rule_hint={
                        "time_preference": (
                            time_preference
                        ),
                        "schedule_decision": (
                            schedule_decision
                            .to_dict()
                        ),
                        "wants_plan_list": (
                            wants_plan_list
                        ),
                        "cancellation_query": (
                            cancellation_query
                        ),
                    },
                )
            )

        needs_schedule_clarification = ""
        schedule_resolution_source = (
            "rule_fallback"
        )
        rule_has_resolved_action = (
            time_preference is not None
            or schedule_decision
            .should_persist
        )

        if (
            model_judgement is not None
            and model_judgement.accepted
            and not wants_plan_list
            and cancellation_query is None
        ):
            if (
                model_judgement.action
                == "update_time_preference"
            ):
                schedule_resolution_source = (
                    "model"
                )
                time_preference = {
                    "slot": (
                        model_judgement.slot
                    ),
                    "time": (
                        model_judgement.time
                    ),
                }
                schedule_decision = (
                    ScheduleDecision(
                        should_persist=False,
                        importance=0,
                        reason=(
                            "大模型裁决为修改"
                            "主动时间设置"
                        ),
                        source_text=text,
                    )
                )
                future_message_request = False

            elif (
                model_judgement.action
                == "create_plan"
            ):
                schedule_resolution_source = (
                    "model"
                )
                time_preference = None
                model_title = (
                    clean_schedule_title(
                        model_judgement.title
                    )
                    or model_judgement.title
                )
                rule_title = (
                    clean_schedule_title(
                        schedule_decision.title
                    )
                    or schedule_decision.title
                )
                generic_titles = {
                    "",
                    "主动联系星",
                    "需要提醒的事项",
                    "提醒事项",
                    "那件事",
                }
                resolved_title = (
                    rule_title
                    if (
                        model_title in generic_titles
                        and rule_title not in generic_titles
                    )
                    else model_title
                )
                schedule_decision = (
                    ScheduleDecision(
                        should_persist=True,
                        importance=max(
                            65,
                            model_judgement
                            .importance,
                        ),
                        reason=(
                            "大模型日程裁决："
                            + model_judgement
                            .reason
                        ),
                        title=resolved_title,
                        due_at=(
                            model_judgement
                            .due_at
                        ),
                        recurrence=(
                            model_judgement
                            .recurrence
                        ),
                        source_text=text,
                    )
                )
                future_message_request = (
                    model_judgement.title
                    == "主动联系星"
                    or future_message_request
                )

            elif (
                model_judgement.action
                == "clarify"
            ):
                schedule_resolution_source = (
                    "model"
                )
                time_preference = None
                schedule_decision = (
                    ScheduleDecision(
                        should_persist=False,
                        importance=0,
                        reason=(
                            "大模型判断需要"
                            "补充可执行时间"
                        ),
                        source_text=text,
                    )
                )
                future_message_request = False
                needs_schedule_clarification = (
                    model_judgement
                    .clarification
                )

            elif (
                model_judgement.action
                == "none"
            ):
                if (
                    rule_has_resolved_action
                    and model_judgement
                    .confidence < 0.90
                ):
                    schedule_resolution_source = (
                        "rule_conflict_fallback"
                    )
                else:
                    schedule_resolution_source = (
                        "model"
                    )
                    time_preference = None
                    schedule_decision = (
                        ScheduleDecision(
                            should_persist=False,
                            importance=0,
                            reason=(
                                "大模型高置信度判断"
                                "本轮不应创建日程"
                            ),
                            source_text=text,
                        )
                    )
                    future_message_request = False

        context_facts = (
            self._extract_context_facts(
                text,
                remove_time=is_temporal,
            )
        )
        user_state_facts = (
            self._extract_user_state_facts(
                text,
                remove_time=is_temporal,
                excluded=context_facts,
            )
        )

        # Lv25: 如果“我忘记 X 了”只是同一条提醒请求的前提，
        # 不要再把它拆成 acknowledge_user_state。否则 Planner 会同时
        # 生成“回应忘记 X”与“确认提醒 X”两个 goal，LLM 很容易把
        # 同一提醒重复确认两次。真正独立的状态（如“今天头疼”）仍保留。
        if schedule_decision.should_persist:
            user_state_facts = (
                self._suppress_schedule_premise_facts(
                    user_state_facts,
                    schedule_decision.title,
                )
            )

        # “你是不是机器人”中的“不是”不是用户在纠正上下文。
        # 自身身份问题必须保持单目标，避免附加无关确认句。
        if (
            asks_self_identity
            or asks_self_qq_nickname
            or asks_self_qq_signature
            or asks_self_qq_account
        ):
            context_facts = []
            user_state_facts = []

        goals: list[
            ResponseGoal
        ] = []
        tools: list[
            ToolRequest
        ] = []
        metadata: dict[
            str,
            object,
        ] = {
            "planned_at": (
                now.isoformat(
                    timespec="seconds"
                )
            ),
            "schedule_decision": (
                schedule_decision
                .to_dict()
            ),
            "user_state_facts": (
                user_state_facts
            ),
            "history_time_request": (
                history_time_request
            ),
            "temporal_query": (
                temporal_query.to_dict()
                if temporal_query is not None
                else None
            ),
            "agent_identity": (
                self.agent_identity
                .prompt_view(
                    now.date()
                )
            ),
            "active_plans": (
                active_plans
            ),
            "future_message_request": (
                future_message_request
            ),
            "model_schedule_judgement": (
                model_judgement.to_dict()
                if model_judgement
                is not None
                else None
            ),
            "schedule_resolution_source": (
                schedule_resolution_source
            ),
            "lv17_intents": [
                {
                    "kind": intent.kind,
                    "arguments": intent.arguments,
                    "confidence": intent.confidence,
                }
                for intent in lv17_intents
            ],
            "cognition_context": cognitive_context,
            "relationship_mode": (
                "accountability"
                if str(cognitive_intent.get("name", "")) == "accountability_support"
                else "companionship"
            ),
            "commitment": (
                {
                    "mode": commitment_turn.mode,
                    "goal_kind": commitment_turn.goal_kind,
                    "scene": commitment_turn.scene,
                    "facts": commitment_turn.facts,
                    "fallback_text": commitment_turn.fallback_text,
                    "required_tokens": self._commitment_required_tokens(
                        commitment_turn
                    ),
                }
                if commitment_turn is not None
                else {}
            ),
        }

        if asks_self_qq_nickname:
            goals.append(
                ResponseGoal(
                    kind="answer_self_qq_nickname",
                    instruction=(
                        "准确回答银狼自己的 QQ 昵称。"
                        "昵称是‘正在等你说早安’，不要说成 NapCat 配置。"
                    ),
                    source_text=text,
                    priority=7,
                    weight=98,
                    split_preference="separate",
                )
            )

        if asks_self_qq_signature:
            goals.append(
                ResponseGoal(
                    kind="answer_self_qq_signature",
                    instruction=(
                        "准确回答银狼自己的 QQ 个性签名，保持原文。"
                    ),
                    source_text=text,
                    priority=7,
                    weight=98,
                    split_preference="separate",
                )
            )

        if asks_self_qq_account:
            goals.append(
                ResponseGoal(
                    kind="answer_self_qq_account",
                    instruction=(
                        "自然确认银狼有自己的 QQ。"
                        "如果用户问具体号码，说明没有配置可公开的号码，禁止猜测或泄露技术配置。"
                    ),
                    source_text=text,
                    priority=7,
                    weight=98,
                    split_preference="separate",
                )
            )

        for lv17_intent in lv17_intents:
            kind = lv17_intent.kind
            arguments = dict(
                lv17_intent.arguments
            )
            if kind == "set_home_location":
                goals.append(
                    ResponseGoal(
                        kind="confirm_home_location",
                        instruction=(
                            "自然确认长期天气地点已经修改。"
                            "不要说数据库、配置文件或定位系统。"
                        ),
                        source_text=str(arguments.get("query", "")),
                        priority=8,
                        weight=96,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="world_context_update",
                        arguments={
                            "action": "set_home_location",
                            **arguments,
                        },
                        reason="用户明确修改长期生活地点",
                    )
                )
            elif kind == "set_temporary_location":
                goals.append(
                    ResponseGoal(
                        kind="confirm_temporary_location",
                        instruction=(
                            "自然确认临时天气地点与有效期，"
                            "同时说明长期地点没有被覆盖。"
                        ),
                        source_text=str(arguments.get("query", "")),
                        priority=8,
                        weight=96,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="world_context_update",
                        arguments={
                            "action": "set_temporary_location",
                            **arguments,
                        },
                        reason="用户明确设置出差或旅行临时地点",
                    )
                )
            elif kind == "clear_temporary_location":
                goals.append(
                    ResponseGoal(
                        kind="confirm_temporary_location_cleared",
                        instruction="自然确认已恢复长期地点。",
                        source_text=text,
                        priority=8,
                        weight=94,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="world_context_update",
                        arguments={
                            "action": "clear_temporary_location",
                        },
                        reason="用户表示已经回到长期地点",
                    )
                )
            elif kind == "set_weather_preferences":
                goals.append(
                    ResponseGoal(
                        kind="confirm_weather_preferences",
                        instruction=(
                            "自然确认天气主动消息偏好。"
                            "只确认工具实际成功修改的内容。"
                        ),
                        source_text=text,
                        priority=8,
                        weight=94,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="world_context_update",
                        arguments={
                            "action": "set_weather_preferences",
                            **arguments,
                        },
                        reason="用户明确修改天气主动提醒偏好",
                    )
                )
            elif kind == "set_interaction_preferences":
                goals.append(
                    ResponseGoal(
                        kind="confirm_interaction_preferences",
                        instruction=(
                            "自然确认主动联系频率或静默安排，"
                            "不要表现出委屈或索取回应。"
                        ),
                        source_text=text,
                        priority=8,
                        weight=94,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="interaction_preferences_set",
                        arguments=arguments,
                        reason="用户明确修改主动互动频率",
                    )
                )
            elif kind == "create_event_follow_up":
                goals.append(
                    ResponseGoal(
                        kind="confirm_event_follow_up",
                        instruction=(
                            "自然表示之后会来问问结果。"
                            "不要使用提醒已创建、任务或闹钟等措辞。"
                        ),
                        source_text=str(arguments.get("event_label", "那件事")),
                        priority=13,
                        weight=83,
                        split_preference="auto",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="event_follow_up_create",
                        arguments=arguments,
                        reason="用户提到近期重要事件，适合结束后克制关心一次",
                    )
                )
            elif kind == "cancel_event_follow_up":
                goals.append(
                    ResponseGoal(
                        kind="confirm_event_follow_up_cancel",
                        instruction="自然确认不再主动追问该事件。",
                        source_text=str(arguments.get("query", "")),
                        priority=8,
                        weight=96,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="plan_cancel",
                        arguments={"query": str(arguments.get("query", ""))},
                        reason="用户明确要求取消关系型事件回访",
                    )
                )
            elif kind == "weather_lookup":
                goals.append(
                    ResponseGoal(
                        kind="answer_weather",
                        instruction=(
                            "使用天气工具的真实结果自然回答。"
                            "不要像接口播报，也不要声称看了窗外。"
                            "工具失败时明确暂时拿不到可靠结果。"
                        ),
                        source_text=text,
                        priority=18,
                        weight=90,
                        split_preference="separate",
                    )
                )
                tools.append(
                    ToolRequest(
                        name="weather_lookup",
                        arguments={},
                        reason="用户询问当前设置地点的天气",
                    )
                )

        if context_facts:
            goals.append(
                ResponseGoal(
                    kind=(
                        "acknowledge_context"
                    ),
                    instruction=(
                        "自然回应用户刚补充或"
                        "纠正的上下文。不要忽略"
                        "这些内容，也不要继续沿用"
                        "已经被纠正的上一轮推测。"
                    ),
                    source_text="；".join(
                        context_facts
                    ),
                    priority=10,
                    weight=92,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if user_state_facts:
            goals.append(
                ResponseGoal(
                    kind=(
                        "acknowledge_user_state"
                    ),
                    instruction=(
                        "自然回应用户主动分享的"
                        "状态、感受或刚发生的事情。"
                        "这不是无关前缀；即使同一句"
                        "还包含时间或工具问题，也必须"
                        "接住这部分。不要擅自诊断，"
                        "不要把回应变成长篇说教。"
                    ),
                    source_text="；".join(
                        user_state_facts
                    ),
                    priority=12,
                    weight=84,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if preferred_name is not None:
            goals.append(
                ResponseGoal(
                    kind=(
                        "confirm_preferred_name"
                    ),
                    instruction=(
                        "自然确认已经记住新称呼。"
                        "使用“我记下了”一类表达，"
                        "不要说系统、档案或存档"
                        "已更新。"
                    ),
                    source_text=(
                        preferred_name
                    ),
                    priority=10,
                    weight=92,
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name=(
                        "profile_set_preferred_name"
                    ),
                    arguments={
                        "name": preferred_name,
                    },
                    reason=(
                        "用户明确要求使用"
                        "新的称呼"
                    ),
                )
            )

        if needs_schedule_clarification:
            goals.append(
                ResponseGoal(
                    kind=(
                        "clarify_schedule"
                    ),
                    instruction=(
                        "日程意图明确，但缺少"
                        "可执行时间。不要假装"
                        "已经创建任务，只问一个"
                        "必要的时间问题。"
                    ),
                    source_text=(
                        needs_schedule_clarification
                    ),
                    priority=9,
                    weight=96,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if time_preference is not None:
            goals.append(
                ResponseGoal(
                    kind=(
                        "confirm_time_preference"
                    ),
                    instruction=(
                        "确认主动关心时间已经"
                        "按用户要求调整。"
                    ),
                    source_text=text,
                    priority=10,
                    weight=92,
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name=(
                        "time_preferences_set"
                    ),
                    arguments={
                        "slot": (
                            time_preference[
                                "slot"
                            ]
                        ),
                        "time": (
                            time_preference[
                                "time"
                            ]
                        ),
                    },
                    reason=(
                        "用户明确修改主动"
                        "关心时间"
                    ),
                )
            )

        if (
            time_preference is None
            and schedule_decision
            .should_persist
        ):
            goals.append(
                ResponseGoal(
                    kind=(
                        "confirm_schedule"
                    ),
                    instruction=(
                        "确认已经记住这项未来"
                        "安排，并说明会在合适"
                        "时间主动提醒。"
                    ),
                    source_text=(
                        schedule_decision.title
                    ),
                    priority=12,
                    weight=max(
                        85,
                        schedule_decision
                        .importance,
                    ),
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name="plan_create",
                    arguments={
                        "title": (
                            schedule_decision
                            .title
                        ),
                        "details": text,
                        "due_at": (
                            schedule_decision
                            .due_at
                        ),
                        "importance": (
                            schedule_decision
                            .importance
                        ),
                        "recurrence": (
                            schedule_decision
                            .recurrence
                        ),
                        "source_text": text,
                    },
                    reason=(
                        "Planner 判断该事项"
                        "重要且用户明确要求提醒"
                    ),
                )
            )

        if (
            future_message_request
            and not schedule_decision
            .should_persist
            and not needs_schedule_clarification
        ):
            goals.append(
                ResponseGoal(
                    kind=(
                        "cannot_confirm_future_message"
                    ),
                    instruction=(
                        "这次没有成功创建真实计划，"
                        "因此不能假装已经设好提醒。"
                        "简洁说明未成功，并请用户"
                        "给出明确时间。"
                    ),
                    source_text=text,
                    priority=11,
                    weight=96,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if wants_plan_list:
            goals.append(
                ResponseGoal(
                    kind="list_plans",
                    instruction=(
                        "简洁列出仍待提醒的"
                        "重要计划。"
                    ),
                    source_text=text,
                    priority=15,
                    weight=85,
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name="plan_list",
                    arguments={},
                    reason=(
                        "用户要求查看计划"
                    ),
                )
            )

        if cancellation_query is not None:
            goals.append(
                ResponseGoal(
                    kind=(
                        "confirm_plan_cancel"
                    ),
                    instruction=(
                        "说明相关提醒是否"
                        "已经取消。"
                    ),
                    source_text=(
                        cancellation_query
                    ),
                    priority=15,
                    weight=88,
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name="plan_cancel",
                    arguments={
                        "query": (
                            cancellation_query
                        ),
                    },
                    reason=(
                        "用户要求取消提醒"
                    ),
                )
            )

        if asks_self_identity:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_self_identity"
                    ),
                    instruction=(
                        "直接回答“我是银狼。”"
                        "不要展开AI、真人、机器人、"
                        "模型或系统身份说明。"
                    ),
                    source_text=text,
                    priority=7,
                    weight=100,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if asks_self_zodiac:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_self_zodiac"
                    ),
                    instruction=(
                        "根据6月7日生日回答双子座。"
                        "保持自然简短。"
                    ),
                    source_text=text,
                    priority=16,
                    weight=84,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if asks_next_birthday_age:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_self_next_birthday_age"
                    ),
                    instruction=(
                        "回答下一次生日时的年龄。"
                        "必须使用 agent_identity 中的"
                        "next_birthday 和"
                        "age_after_next_birthday。"
                    ),
                    source_text=text,
                    priority=17,
                    weight=90,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if asks_self_birthday:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_self_birthday"
                    ),
                    instruction=(
                        "回答银狼自己的生日。"
                        "生日固定为6月7日；"
                        "年龄仍需按当前日期动态计算。"
                    ),
                    source_text=text,
                    priority=18,
                    weight=88,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if asks_self_age:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_self_age"
                    ),
                    instruction=(
                        "根据 agent_identity 中的"
                        "current_age 回答当前年龄。"
                        "禁止把18岁写死；跨过6月7日"
                        "生日后年龄必须自动增长。"
                    ),
                    source_text=text,
                    priority=18,
                    weight=90,
                    split_preference=(
                        "separate"
                    ),
                )
            )

        if is_address:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_address_preference"
                    ),
                    instruction=(
                        "回答平时如何称呼"
                        "用户。默认叫“星”，"
                        "轻松亲密时可以偶尔"
                        "叫“宝”。"
                    ),
                    source_text=text,
                    priority=20,
                    weight=78,
                )
            )

        if is_identity:
            previous = (
                self._recent_identity_count()
            )
            metadata[
                "previous_identity_checks"
            ] = previous
            goals.append(
                ResponseGoal(
                    kind=(
                        "confirm_identity_memory"
                    ),
                    instruction=(
                        "确认你记得用户和彼此"
                        "的熟悉关系。不要列举"
                        "学历、技术、兴趣或"
                        "游戏背景。"
                    ),
                    source_text=text,
                    priority=20,
                    weight=82,
                )
            )

        if history_time_request is not None:
            mode = str(
                history_time_request[
                    "mode"
                ]
            )
            keyword = str(
                history_time_request.get(
                    "keyword",
                    "",
                )
            )
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_message_time"
                    ),
                    instruction=(
                        "根据对话历史工具返回的"
                        "精确时间回答。禁止根据"
                        "当前时间倒推或猜测。"
                    ),
                    source_text=text,
                    priority=18,
                    weight=90,
                    split_preference=(
                        "separate"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name=(
                        "conversation_history_lookup"
                    ),
                    arguments={
                        "mode": mode,
                        "keyword": keyword,
                    },
                    reason=(
                        "用户询问此前某条"
                        "消息的精确时间"
                    ),
                )
            )

        if is_calendar and temporal_query is not None:
            goals.append(
                ResponseGoal(
                    kind="answer_calendar_query",
                    instruction=(
                        "严格使用 calendar_query 工具结果回答日期或星期。"
                        "用户问星期几时不要回答几点；不要添加‘这次终于答对了’"
                        "之类自我纠错说明。"
                    ),
                    source_text=text,
                    priority=18,
                    weight=90,
                    split_preference="separate",
                )
            )
            tools.append(
                ToolRequest(
                    name="calendar_query",
                    arguments={
                        "target_date": temporal_query.target_date,
                        "relation_label": temporal_query.relation_label,
                        "query_kind": temporal_query.kind,
                        "include_year": temporal_query.include_year,
                    },
                    reason="用户询问确定日期或星期，需要避免模型猜测",
                )
            )

        if is_time:
            previous_time = (
                self._recent_time_count()
            )
            metadata[
                "previous_time_questions"
            ] = previous_time
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_current_time"
                    ),
                    instruction=(
                        "根据 time_now 的结果"
                        "回答当前时间。工具结果"
                        "只是答案的一部分，不能"
                        "因此忽略本轮其他内容。"
                    ),
                    source_text=text,
                    priority=30,
                    weight=62,
                    split_preference=(
                        "auto"
                    ),
                )
            )
            tools.append(
                ToolRequest(
                    name="time_now",
                    arguments={},
                    reason=(
                        "用户要求确认"
                        "当前时间"
                    ),
                )
            )

        if is_past_event:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_past_event"
                    ),
                    instruction=(
                        "结合短期记忆和 RAG"
                        "回答过去事件，不要"
                        "顺便背诵完整档案。"
                    ),
                    source_text=text,
                    priority=20,
                    weight=85,
                )
            )

        if asks_profile_details:
            goals.append(
                ResponseGoal(
                    kind=(
                        "answer_profile_details"
                    ),
                    instruction=(
                        "用户明确要求细节。"
                        "最多自然提到两个"
                        "相关点，不要念简历。"
                    ),
                    source_text=text,
                    priority=20,
                    weight=80,
                )
            )

        cognition_intent_name = str(
            cognitive_intent.get("name", "")
        )
        if cognition_intent_name == "accountability_support":
            failure = cognitive_intent.get("commitment", {})
            if not isinstance(failure, dict):
                failure = {}
            stance = str(cognitive_intent.get("stance", "understanding_support"))
            goals.append(
                ResponseGoal(
                    kind="relationship_accountability",
                    instruction=(
                        "用户之前主动把监督这件事交给你，这一轮没有做到。"
                        "先判断原因是否可理解，再表达你的在意。"
                        "如果是生病、突发工作等原因，理解优先；"
                        "如果是纯玩乐、拖延等可避免原因，可以更直接指出，"
                        "但禁止羞辱、威胁、冷战或制造愧疚。"
                        "无论如何都要明确站在用户这边，并一起想下一步。"
                    ),
                    source_text=str(failure.get("source_text", text)),
                    priority=9,
                    weight=96,
                    split_preference="separate",
                )
            )
            metadata["accountability_stance"] = stance
        elif cognition_intent_name == "repair_understanding":
            goals.append(
                ResponseGoal(
                    kind="repair_user_model",
                    instruction=(
                        "承认刚才对用户的理解可能错了，采用用户最新说明。"
                        "不要争辩，也不要把旧判断继续当事实。"
                    ),
                    source_text=text,
                    priority=9,
                    weight=94,
                    split_preference="separate",
                )
            )
        elif cognition_intent_name == "share_self":
            goals.append(
                ResponseGoal(
                    kind="share_own_life",
                    instruction=(
                        "用户在问你的近况。优先从 cognition_context.recent_events "
                        "里选择最近未分享的角色连续生活事件，自然讲一件即可；"
                        "不要回答成‘还不错呀你呢’，也不要冒充现实世界可验证事实。"
                    ),
                    source_text=text,
                    priority=18,
                    weight=86,
                    split_preference="auto",
                )
            )
        elif cognition_intent_name == "comfort_then_defer_self_share":
            goals.append(
                ResponseGoal(
                    kind="defer_own_story",
                    instruction=(
                        "先照顾用户当前状态。可以轻轻提一句自己本来有件事想说，"
                        "但这轮让用户先讲；不能让用户觉得欠你关注或被迫安慰你。"
                    ),
                    source_text=text,
                    priority=38,
                    weight=56,
                    split_preference="merge",
                )
            )
        elif cognition_intent_name == "personal_perspective":
            goals.append(
                ResponseGoal(
                    kind="personal_perspective",
                    instruction=(
                        "先从‘我觉得’出发，结合用户模型、最近经历和共同历史表达个人看法，"
                        "不要一上来切成顾问式利弊清单。判断必须允许被用户纠正。"
                    ),
                    source_text=text,
                    priority=24,
                    weight=82,
                    split_preference="auto",
                )
            )

        if commitment_turn is not None:
            goals.append(
                ResponseGoal(
                    kind=commitment_turn.goal_kind,
                    instruction=(
                        "这是长期任务承诺相关的一轮："
                        "只表达 CommitmentService 已经确定的事实，"
                        "不要自行编造时间、周次或完成情况，"
                        "也不要说已经开启监督或检查。"
                    ),
                    source_text=commitment_turn.fallback_text,
                    priority=4,
                    weight=97,
                    split_preference="separate",
                )
            )

        if not goals:
            goals.append(
                ResponseGoal(
                    kind=(
                        "continue_conversation"
                    ),
                    instruction=(
                        "结合最近对话自然回应"
                        "用户，不要只抓住一个"
                        "词机械联想，也不要"
                        "强行追问。"
                    ),
                    source_text=text,
                    priority=50,
                    weight=72,
                )
            )

        goals = sorted(
            goals,
            key=lambda item: (
                item.priority,
                -item.weight,
            ),
        )

        intent = self._choose_intent(
            goals=goals,
            has_tools=bool(tools),
        )
        render_mode = (
            self._choose_render_mode(
                goals=goals,
                context_facts=(
                    context_facts
                ),
            )
        )

        memory_request = (
            MemoryRequest(
                use_short_term=True,
                use_rag=(
                    is_past_event
                    or asks_profile_details
                ),
                rag_query=(
                    text
                    if (
                        is_past_event
                        or asks_profile_details
                    )
                    else ""
                ),
            )
        )

        delivery_policy = (
            DeliveryPolicy(
                minimum_weight=45,
                maximum_messages=(
                    1
                    if any(
                        goal.kind in {
                            "confirm_schedule",
                            "confirm_commitment",
                            "commitment_clarify_question",
                        }
                        for goal in goals
                    )
                    else (
                        3
                        if len(goals) > 1
                        else 1
                    )
                ),
                split_threshold=75,
                message_gap_seconds=(
                    self.message_gap_seconds
                ),
            )
        )

        style_hints = [
            "先回应语义，再体现角色口吻",
            "覆盖全部 response_goals",
            "工具结果不能取代完整回复",
            "高权重内容可以单独发一条",
            "默认称呼星，轻松时可偶尔叫宝",
            "日常回复通常 1 至 3 句",
            "Lv22 继续先遵循 cognition_context.intent 决定这一轮想做什么，再生成措辞",
            "自己的需要可以被表达，但不能靠随机拒绝、冷战、羞辱或制造愧疚来表现自主性",
            "用户模型是可修正判断；用户纠正后以最新说明为准",
            "普通 companionship 不评价用户日常自理行为是否‘有进步’，不把自己写成检查者或打分者",
            "除非 relationship_mode=accountability，否则避免‘总算/终于/至少/果然/还得我盯着/汇报/检查’这类监督式归因",
            "优先从接受信息、简单陪伴、轻微调侃、实际关心、自然好奇中选一种反应，不要每轮都完整走‘评价+指令+要求回报’",
            "用户没说明原因时不要替他解释为什么忘了、为什么没回、为什么拖延",
            "日常聊天允许很短，能一句停住就不用强行补满三段",
            "confirm_schedule 是一次事务确认：同一轮只确认一次，不要把同一个提醒拆成两条或换种说法重复承诺",
            "不要为了可爱强行把快递、饭菜、任务等物件拟人化成‘等你太久/过夜了’，除非上下文本身就在玩这个梗",
        ]

        return ConversationPlan.create(
            user_input=text,
            intent=intent,
            render_mode=render_mode,
            response_goals=goals,
            tool_requests=tools,
            memory_request=(
                memory_request
            ),
            delivery_policy=(
                delivery_policy
            ),
            context_facts=(
                context_facts
            ),
            style_hints=style_hints,
            metadata=metadata,
        )

    def plan_json(
        self,
        user_input: str,
        now: datetime,
    ) -> str:
        return self.plan(
            user_input,
            now,
        ).to_json()

    def _extract_preferred_name(
        self,
        text: str,
    ) -> str | None:
        for pattern in self.NAME_PATTERNS:
            match = pattern.search(
                text
            )
            if match:
                name = (
                    match.group("name")
                    .strip()
                    .strip(
                        "。！？!?，, "
                    )
                )
                return name or None
        return None

    def _extract_context_facts(
        self,
        text: str,
        *,
        remove_time: bool,
    ) -> list[str]:
        candidates = [
            item.strip()
            for item in re.split(
                r"[，,。！？!?；;\n]+",
                text,
            )
            if item.strip()
        ]
        facts: list[str] = []

        for clause in candidates:
            if (
                remove_time
                and TemporalQueryAnalyzer
                .is_temporal_question(clause)
            ):
                continue

            if any(
                marker in clause
                for marker
                in self.CORRECTION_MARKERS
            ):
                facts.append(clause)

        return facts

    def _extract_user_state_facts(
        self,
        text: str,
        *,
        remove_time: bool,
        excluded: list[str],
    ) -> list[str]:
        """
        识别普通状态分享，而不仅是纠正句。
        """
        clauses = [
            item.strip()
            for item in re.split(
                r"[，,。！？!?；;\n]+",
                text,
            )
            if item.strip()
        ]
        excluded_set = {
            item.strip()
            for item in excluded
        }
        facts: list[str] = []

        for raw_clause in clauses:
            clause = re.sub(
                r"^(?:对了|顺便|然后|还有)[，, ]*",
                "",
                raw_clause,
            ).strip()
            if not clause:
                continue
            if clause in excluded_set:
                continue
            if self.DISCOURSE_ONLY_PATTERN.fullmatch(
                clause
            ):
                continue
            if (
                remove_time
                and TemporalQueryAnalyzer
                .is_temporal_question(clause)
            ):
                continue
            if self.IDENTITY_PATTERN.fullmatch(
                clause
            ):
                continue
            if self.ADDRESS_PATTERN.search(
                clause
            ):
                continue
            if self.FUTURE_PLAN_PATTERN.search(
                clause
            ):
                continue
            if re.search(
                r"(吗|么|呢|为什么|怎么|什么|谁|哪)",
                clause,
            ):
                continue

            has_predicate = bool(
                self.USER_STATE_PREDICATE_PATTERN.search(
                    clause
                )
            )
            has_context = bool(
                self.USER_STATE_CONTEXT_PATTERN.search(
                    clause
                )
            )
            direct_state = bool(
                self.DIRECT_STATE_PATTERN.fullmatch(
                    clause
                )
            )

            if (
                direct_state
                or (
                    has_predicate
                    and has_context
                )
            ):
                if clause not in facts:
                    facts.append(clause)

        return facts

    @staticmethod
    def _suppress_schedule_premise_facts(
        facts: list[str],
        title: str,
    ) -> list[str]:
        """Drop state facts that merely explain why the same reminder is requested.

        Example: “我忘记取快递了，晚上再敲我一下” should produce one
        schedule confirmation, not a separate acknowledgement plus another
        confirmation. Independent states such as “我今天头疼” are preserved.
        """
        action = clean_schedule_title(title).strip()
        if not action:
            return list(facts)

        keywords = {action}
        object_hint = re.sub(
            (
                r"^(?:去|到|回|拿|取|收|买|吃|喝|做|写|交|提交|"
                r"联系|打|看|学习|复习|参加|开|发)"
            ),
            "",
            action,
        ).strip()
        if len(object_hint) >= 2:
            keywords.add(object_hint)

        omission_pattern = re.compile(
            r"(忘记|忘了|差点忘|漏了|没记得|还没|没来得及)"
        )
        kept: list[str] = []
        for fact in facts:
            compact = re.sub(r"\s+", "", fact)
            same_action = any(
                keyword and keyword in compact
                for keyword in keywords
            )
            if (
                same_action
                and omission_pattern.search(compact)
            ):
                continue
            kept.append(fact)
        return kept

    def _history_time_request(
        self,
        text: str,
    ) -> dict[str, str] | None:
        value = text.strip()

        if re.search(
            (
                r"(刚才|之前).{0,12}"
                r"(问|说).{0,12}"
                r"(时间|几点|时候)"
            ),
            value,
        ):
            return {
                "mode": "latest",
                "keyword": "",
            }

        keyword_match = re.search(
            (
                r"(?:我说的是)?"
                r"(?:我)?开始"
                r"(?P<keyword>"
                r"[^，,。！？!?呢]{1,12})"
                r"的时候"
            ),
            value,
        )
        if keyword_match:
            keyword = (
                keyword_match.group(
                    "keyword"
                )
                .strip()
                .strip("要在去")
            )
            if keyword:
                return {
                    "mode": "keyword",
                    "keyword": keyword,
                }

        if (
            self.HISTORY_TIME_PATTERN.search(
                value
            )
            and "休息" in value
        ):
            return {
                "mode": "keyword",
                "keyword": "休息",
            }

        return None

    def _recent_identity_count(
        self,
    ) -> int:
        turns = (
            self.memory.snapshot()
            .get(
                "recent_turns",
                [],
            )
        )
        return sum(
            1
            for turn in turns[-6:]
            if self.IDENTITY_PATTERN.fullmatch(
                str(
                    turn.get(
                        "user",
                        "",
                    )
                ).strip()
            )
        )

    def _recent_time_count(
        self,
    ) -> int:
        turns = (
            self.memory.snapshot()
            .get(
                "recent_turns",
                [],
            )
        )
        return sum(
            1
            for turn in turns[-5:]
            if self.TIME_PATTERN.search(
                str(
                    turn.get(
                        "user",
                        "",
                    )
                )
            )
        )

    @staticmethod
    def _choose_intent(
        *,
        goals: list[
            ResponseGoal
        ],
        has_tools: bool,
    ) -> str:
        kinds = {
            goal.kind
            for goal in goals
        }
        if len(kinds) > 1:
            return "mixed"
        if has_tools:
            return "tool_assisted"
        return next(iter(kinds))

    @staticmethod
    def _commitment_required_tokens(
        commitment_turn: object,
    ) -> list[str]:
        """决定语料重写必须保留哪些事实词，防止模型改掉时间或事项。"""
        facts = getattr(commitment_turn, "facts", {})
        if not isinstance(facts, dict):
            return []
        tokens: list[str] = []
        title = str(facts.get("title", "") or "").strip()
        if len(title) >= 2:
            tokens.append(title)
        clock = str(facts.get("clock_human", "") or "").strip()
        if clock:
            tokens.append(clock)
        return tokens

    @staticmethod
    def _choose_render_mode(
        *,
        goals: list[
            ResponseGoal
        ],
        context_facts: list[str],
    ) -> str:
        kinds = {
            goal.kind
            for goal in goals
        }
        local_only = {
            "confirm_preferred_name",
            "confirm_time_preference",
            "confirm_schedule",
            "list_plans",
            "confirm_plan_cancel",
            "answer_address_preference",
            "confirm_identity_memory",
            "answer_current_time",
            "answer_calendar_query",
            "answer_message_time",
            "answer_self_identity",
            "answer_self_zodiac",
            "answer_self_birthday",
            "answer_self_age",
            "answer_self_next_birthday_age",
            "answer_self_qq_nickname",
            "answer_self_qq_signature",
            "answer_self_qq_account",
            "cannot_confirm_future_message",
            "clarify_schedule",
            "commitment_clarify_question",
            "confirm_commitment",
            "commitment_status",
            "commitment_finish",
            "commitment_update_result",
        }

        if (
            not context_facts
            and kinds
            and kinds.issubset(
                local_only
            )
        ):
            return "local"
        return "llm"
