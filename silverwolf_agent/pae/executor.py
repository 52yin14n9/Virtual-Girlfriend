from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from .contracts import (
    ConversationPlan,
    ExecutionPacket,
    ResponseGoal,
    ToolExecutionResult,
)
from ..dialogue import companionship_language_guard
from ..delivery import (
    OutboundMessage,
    ReplyBundle,
)
from ..llm import (
    BaseLLMClient,
    EchoLLMClient,
    LLMServiceError,
)
from ..memory.profile import (
    UserProfileManager,
)
from ..memory.agent_identity import (
    AgentIdentityManager,
)
from ..memory.rag import (
    JsonlRAGStore,
)
from ..memory.short_term import (
    ShortTermMemory,
)
from ..models import ChatMessage
from ..prompts import PromptBuilder
from ..proactive.schedule_intent import clean_schedule_title
from ..proactive.reminder_language import render_schedule_confirmation
from ..response_completion import ResponseCompletionAgent
from ..tools.registry import (
    ToolRegistry,
)


class ConversationExecutor:
    """
    PAE Executor。

    输入只接受 Planner JSON，输出：
    - ReplyBundle：可拆分、带权重的消息；
    - ExecutionPacket JSON：完整执行记录。
    """

    def __init__(
        self,
        *,
        llm: BaseLLMClient,
        tool_registry: ToolRegistry,
        profile: UserProfileManager,
        memory: ShortTermMemory,
        rag: JsonlRAGStore,
        prompt_builder: PromptBuilder,
        agent_identity: (
            AgentIdentityManager
            | None
        ) = None,
        completion_agent: ResponseCompletionAgent | None = None,
        completion_max_rounds: int = 2,
        completion_max_chars: int = 12000,
        speech: "SpeechComposer | None" = None,
    ) -> None:
        self.llm = llm
        self.tool_registry = (
            tool_registry
        )
        self.profile = profile
        self.memory = memory
        self.agent_identity = (
            agent_identity
            or AgentIdentityManager()
        )
        self.rag = rag
        self.prompt_builder = (
            prompt_builder
        )
        self.completion_agent = completion_agent
        self.completion_max_rounds = max(0, min(4, int(completion_max_rounds)))
        self.completion_max_chars = max(1000, int(completion_max_chars))
        self.speech = speech
        self.last_completion_decision_json = ""

    @property
    def offline(self) -> bool:
        return isinstance(
            self.llm,
            EchoLLMClient,
        )

    def execute_json(
        self,
        plan_json: str,
        now: datetime,
    ) -> tuple[
        ReplyBundle,
        str,
    ]:
        plan = (
            ConversationPlan.from_json(
                plan_json
            )
        )

        tool_results = (
            self._execute_tools(plan)
        )
        short_memory = (
            self.memory.context_text()
            if (
                plan.memory_request
                .use_short_term
            )
            else ""
        )
        rag_context = (
            self._retrieve_rag(plan, now=now)
        )
        profile_context = (
            self.profile.prompt_view(
                now.date()
            )
        )

        packet = ExecutionPacket(
            schema_version="2.0",
            plan=plan.to_dict(),
            tool_results=tool_results,
            short_memory=short_memory,
            rag_context=rag_context,
            profile_context=(
                profile_context
            ),
            cognition_context=(
                plan.metadata.get(
                    "cognition_context",
                    {},
                )
                if isinstance(plan.metadata, dict)
                else {}
            ),
        )
        packet_json = packet.to_json()

        # Lv25: schedule creation is a single transactional acknowledgement.
        # For the common “state premise + reminder” shape, render it locally
        # and coalesce into one bubble so the model cannot confirm the same
        # persisted plan twice in two differently worded messages.
        if self._can_render_schedule_transaction_locally(plan):
            bundle = self._render_schedule_transaction_local(
                plan=plan,
                tool_results=tool_results,
                now=now,
            )
            return bundle, packet_json

        if (
            plan.render_mode == "local"
            or self.offline
        ):
            bundle = self._render_local(
                plan=plan,
                tool_results=tool_results,
                now=now,
            )
            return bundle, packet_json

        try:
            bundle = self._render_with_llm(
                plan=plan,
                packet_json=(
                    packet_json
                ),
                now=now,
            )
        except (
            LLMServiceError,
            ValueError,
            json.JSONDecodeError,
        ):
            bundle = self._render_local(
                plan=plan,
                tool_results=tool_results,
                now=now,
            )

        bundle = self._ensure_response_complete(
            plan=plan,
            bundle=bundle,
            now=now,
        )
        return bundle, packet_json

    @staticmethod
    def _can_render_schedule_transaction_locally(
        plan: ConversationPlan,
    ) -> bool:
        kinds = {
            goal.kind
            for goal in plan.response_goals
        }
        if "confirm_schedule" not in kinds:
            return False
        return kinds.issubset(
            {
                "confirm_schedule",
                "acknowledge_user_state",
                "acknowledge_context",
            }
        )

    def _render_schedule_transaction_local(
        self,
        *,
        plan: ConversationPlan,
        tool_results: list[ToolExecutionResult],
        now: datetime,
    ) -> ReplyBundle:
        # Acknowledge genuinely independent state first, then confirm the
        # persisted schedule exactly once. Schedule-premise facts have already
        # been removed by Planner.
        order = {
            "acknowledge_context": 0,
            "acknowledge_user_state": 1,
            "confirm_schedule": 2,
        }
        parts: list[str] = []
        weight = 0
        goal_kinds: list[str] = []
        for goal in sorted(
            plan.response_goals,
            key=lambda item: (
                order.get(item.kind, 99),
                item.priority,
                -item.weight,
            ),
        ):
            content = self._render_goal(
                goal=goal,
                plan=plan,
                tool_results=tool_results,
                now=now,
            ).strip()
            if not content:
                continue
            parts.append(content)
            weight = max(weight, goal.weight)
            goal_kinds.append(goal.kind)

        content = " ".join(parts).strip() or "嗯，我记下了"
        return ReplyBundle(
            messages=[
                OutboundMessage(
                    content=content,
                    weight=weight or 90,
                    category="schedule_transaction",
                    source="interactive",
                    sequence=0,
                    delay_seconds=0.0,
                    goal_kinds=goal_kinds,
                )
            ],
            minimum_weight=plan.delivery_policy.minimum_weight,
            maximum_messages=1,
        )

    def _execute_tools(
        self,
        plan: ConversationPlan,
    ) -> list[
        ToolExecutionResult
    ]:
        results: list[
            ToolExecutionResult
        ] = []

        for request in (
            plan.tool_requests
        ):
            result = (
                self.tool_registry.execute(
                    request.name,
                    request.arguments,
                )
            )
            results.append(
                ToolExecutionResult(
                    name=request.name,
                    ok=result.ok,
                    content=(
                        result.content
                    ),
                    error=result.error,
                    reason=request.reason,
                )
            )

        return results

    def _retrieve_rag(
        self,
        plan: ConversationPlan,
        *,
        now: datetime | None = None,
    ) -> str:
        request = (
            plan.memory_request
        )
        if not request.use_rag:
            return ""

        query = (
            request.rag_query
            or plan.user_input
        )
        moment = now or datetime.now()
        # Lv28: 检索结果按"相关性 × 重要度 × 遗忘曲线"排序；
        # 命中的记忆记一次复习，之后更难被忘掉。
        scored = self.rag.search_scored(
            query,
            top_k=4,
            now=moment,
        )
        if not scored:
            return (
                "长期记忆中没有"
                "检索到匹配记录。"
            )

        docs = [doc for doc, _ in scored]
        try:
            self.rag.mark_recalled(
                [doc.id for doc in docs],
                at=moment,
            )
        except Exception:  # noqa: BLE001 - 统计失败不该影响回复
            pass

        lines: list[str] = []
        for doc, detail in scored:
            stamp = doc.metadata.get("date", doc.created_at)
            importance = int(detail.get("importance", doc.importance))
            lines.append(
                f"[{stamp}｜重要度{importance}] {doc.text}"
            )
        return "\n\n".join(lines)

    def _render_with_llm(
        self,
        *,
        plan: ConversationPlan,
        packet_json: str,
        now: datetime,
    ) -> ReplyBundle:
        style_block = ""
        if self.speech is not None:
            try:
                style_block = self.speech.style_block(
                    "chat_general",
                    k=2,
                )
            except Exception:  # noqa: BLE001 - 语料只是锦上添花
                style_block = ""
        system = (
            self.prompt_builder
            .pae_executor_prompt(
                now=now,
                execution_packet_json=(
                    packet_json
                ),
                style_block=style_block,
            )
        )

        history = [
            ChatMessage(
                role=str(
                    item["role"]
                ),
                content=str(
                    item["content"]
                ),
            )
            for item in (
                self.memory
                .recent_chat_messages(
                    limit=30
                )
            )
        ]
        if (
            history
            and history[-1].role == "user"
        ):
            history[-1].content += (
                "\n\n"
                + plan.user_input
            )
        else:
            history.append(
                ChatMessage(
                    role="user",
                    content=(
                        plan.user_input
                    ),
                )
            )

        response = self.llm.complete(
            system=system,
            messages=history,
            tools=None,
        )

        return self._parse_llm_bundle(
            response.text,
            plan,
        )

    def _ensure_response_complete(
        self,
        *,
        plan: ConversationPlan,
        bundle: ReplyBundle,
        now: datetime,
    ) -> ReplyBundle:
        judge = self.completion_agent
        if judge is None or self.completion_max_rounds <= 0 or self.offline:
            self.last_completion_decision_json = ""
            return bundle

        selected = bundle.selected_messages()
        if not selected:
            return bundle

        previous_text = bundle.joined_text().strip()
        if not previous_text:
            return bundle

        goals = [goal.instruction for goal in plan.response_goals]
        for _round in range(self.completion_max_rounds + 1):
            decision = judge.decide(
                user_input=plan.user_input,
                assistant_text=previous_text,
                goal_instructions=goals,
            )
            self.last_completion_decision_json = decision.to_json()
            if decision.complete or _round >= self.completion_max_rounds:
                break
            if len(previous_text) >= self.completion_max_chars:
                break

            continuation = self._generate_completion_continuation(
                plan=plan,
                current_text=previous_text,
                instruction=decision.continuation_instruction,
                now=now,
            )
            continuation = continuation.strip()
            if not continuation:
                break

            # No-progress guard: a model that repeats the same promise must not
            # create an endless self-continuation loop.
            normalized_old = re.sub(r"\s+", "", previous_text)
            normalized_new = re.sub(r"\s+", "", continuation)
            if not normalized_new or normalized_new in normalized_old:
                break

            remaining = self.completion_max_chars - len(previous_text)
            if remaining <= 0:
                break
            continuation = continuation[:remaining].rstrip()
            if not continuation:
                break

            # Merge into the final already-selected bubble. This preserves the
            # user's “一次性发给我” expectation and cannot be truncated by the
            # ReplyBundle maximum_messages policy.
            selected[-1].content = (
                selected[-1].content.rstrip()
                + "\n\n"
                + continuation
            )
            selected[-1].validate()
            previous_text = bundle.joined_text().strip()

        return bundle

    def _generate_completion_continuation(
        self,
        *,
        plan: ConversationPlan,
        current_text: str,
        instruction: str,
        now: datetime,
    ) -> str:
        system = (
            self.prompt_builder.persona_path.read_text(encoding="utf-8")
            + "\n\n## 同轮续写规则\n"
            + "你正在补完同一个用户回合，不是在开启新一轮对话。\n"
            + "当前回复被判定为没有完成用户请求。只补缺失的主体内容，不重复寒暄、承诺、道歉或已经说过的句子。\n"
            + "完成后自然停住，不要问‘要不要继续’，不要为了续写而续写。\n"
            + "若用户要求一次性、完整、全文或连带翻译，本次续写必须尽量一次补齐。\n"
            + "QQ/即时聊天普通陈述句末尾不保留全角句号。\n"
            + f"当前时间：{now.isoformat(timespec='seconds')}"
        )
        payload = (
            "用户请求：\n" + plan.user_input
            + "\n\n已经发出的内容：\n" + current_text
            + "\n\n需要补完：\n"
            + (instruction or "直接补齐尚未交付的内容并完成请求。")
        )
        try:
            response = self.llm.complete(
                system=system,
                messages=[ChatMessage(role="user", content=payload)],
                tools=None,
            )
        except LLMServiceError:
            return ""
        return companionship_language_guard(
            response.text.strip(),
            relationship_mode=str(
                plan.metadata.get("relationship_mode", "companionship")
                if isinstance(plan.metadata, dict)
                else "companionship"
            ),
            user_input=plan.user_input,
        )

    def _parse_llm_bundle(
        self,
        text: str,
        plan: ConversationPlan,
    ) -> ReplyBundle:
        cleaned = text.strip()
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

        data: dict[str, Any] | None = None
        try:
            parsed = json.loads(
                cleaned
            )
            if isinstance(
                parsed,
                dict,
            ):
                data = parsed
        except json.JSONDecodeError:
            decoder = (
                json.JSONDecoder()
            )
            start = cleaned.find("{")
            if start >= 0:
                try:
                    parsed, _ = (
                        decoder.raw_decode(
                            cleaned[start:]
                        )
                    )
                    if isinstance(
                        parsed,
                        dict,
                    ):
                        data = parsed
                except json.JSONDecodeError:
                    data = None

        if data is None:
            return self._bundle_from_text(
                cleaned,
                plan,
            )

        raw_messages = data.get(
            "messages",
            [],
        )
        if not isinstance(
            raw_messages,
            list,
        ):
            raise ValueError(
                "messages 必须是数组"
            )

        messages: list[
            OutboundMessage
        ] = []
        fallback_weight = max(
            goal.weight
            for goal in (
                plan.response_goals
            )
        )

        for index, item in enumerate(
            raw_messages
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            content = str(
                item.get(
                    "content",
                    "",
                )
            ).strip()
            relationship_mode = str(
                plan.metadata.get(
                    "relationship_mode",
                    "companionship",
                )
                if isinstance(plan.metadata, dict)
                else "companionship"
            )
            content = companionship_language_guard(
                content,
                relationship_mode=relationship_mode,
                user_input=plan.user_input,
            )
            if not content:
                continue

            messages.append(
                OutboundMessage(
                    content=content,
                    weight=int(
                        item.get(
                            "weight",
                            fallback_weight,
                        )
                    ),
                    category=str(
                        item.get(
                            "category",
                            "conversation",
                        )
                    ),
                    source="interactive",
                    sequence=int(
                        item.get(
                            "sequence",
                            index,
                        )
                    ),
                    delay_seconds=(
                        plan.delivery_policy
                        .message_gap_seconds
                    ),
                    goal_kinds=[
                        str(value)
                        for value in item.get(
                            "goal_kinds",
                            [],
                        )
                    ],
                )
            )

        if not messages:
            return self._bundle_from_text(
                cleaned,
                plan,
            )

        return ReplyBundle(
            messages=messages,
            minimum_weight=(
                plan.delivery_policy
                .minimum_weight
            ),
            maximum_messages=(
                plan.delivery_policy
                .maximum_messages
            ),
        )

    def _bundle_from_text(
        self,
        text: str,
        plan: ConversationPlan,
    ) -> ReplyBundle:
        relationship_mode = str(
            plan.metadata.get(
                "relationship_mode",
                "companionship",
            )
            if isinstance(plan.metadata, dict)
            else "companionship"
        )
        parts = [
            companionship_language_guard(
                part.strip(),
                relationship_mode=relationship_mode,
                user_input=plan.user_input,
            )
            for part in re.split(
                r"\n\s*\n+",
                text,
            )
            if part.strip()
        ]
        parts = [part for part in parts if part.strip()]
        if not parts:
            parts = [
                "嗯，我在听。"
            ]

        weight = max(
            goal.weight
            for goal in (
                plan.response_goals
            )
        )
        messages = [
            OutboundMessage(
                content=part,
                weight=weight,
                category=(
                    "conversation"
                ),
                source="interactive",
                sequence=index,
                delay_seconds=(
                    plan.delivery_policy
                    .message_gap_seconds
                ),
                goal_kinds=[
                    goal.kind
                    for goal in (
                        plan.response_goals
                    )
                ],
            )
            for index, part in enumerate(
                parts
            )
        ]

        return ReplyBundle(
            messages=messages,
            minimum_weight=(
                plan.delivery_policy
                .minimum_weight
            ),
            maximum_messages=(
                plan.delivery_policy
                .maximum_messages
            ),
        )

    def _render_local(
        self,
        *,
        plan: ConversationPlan,
        tool_results: list[
            ToolExecutionResult
        ],
        now: datetime,
    ) -> ReplyBundle:
        messages: list[
            OutboundMessage
        ] = []
        sequence = 0

        for goal in (
            plan.response_goals
        ):
            content = (
                self._render_goal(
                    goal=goal,
                    plan=plan,
                    tool_results=(
                        tool_results
                    ),
                    now=now,
                )
            )
            if not content:
                continue

            messages.append(
                OutboundMessage(
                    content=content,
                    weight=goal.weight,
                    category=goal.kind,
                    source="interactive",
                    sequence=sequence,
                    delay_seconds=(
                        plan.delivery_policy
                        .message_gap_seconds
                    ),
                    goal_kinds=[
                        goal.kind
                    ],
                )
            )
            sequence += 1

        if not messages:
            messages.append(
                OutboundMessage(
                    content="嗯，我在听。",
                    weight=70,
                    category=(
                        "conversation"
                    ),
                    source="interactive",
                )
            )

        return ReplyBundle(
            messages=messages,
            minimum_weight=(
                plan.delivery_policy
                .minimum_weight
            ),
            maximum_messages=(
                plan.delivery_policy
                .maximum_messages
            ),
        )

    def _render_commitment_goal(
        self,
        *,
        goal: ResponseGoal,
        plan: ConversationPlan,
        now: datetime,
        casual_alias: str,
    ) -> str:
        info: dict[str, object] = {}
        if isinstance(plan.metadata, dict):
            raw = plan.metadata.get("commitment", {})
            if isinstance(raw, dict):
                info = raw

        fallback_text = str(
            info.get("fallback_text", "") or goal.source_text or ""
        ).strip()
        if not fallback_text:
            fallback_text = "嗯，我记下了"

        facts = info.get("facts", {})
        if not isinstance(facts, dict):
            facts = {}
        scene = str(info.get("scene", "") or "commitment_confirm")
        relation_mode = str(info.get("relation_mode", "companionship"))
        raw_required = info.get("required_tokens", [])
        required: tuple[str, ...] = ()
        if isinstance(raw_required, (list, tuple)):
            required = tuple(str(item) for item in raw_required if str(item).strip())

        if self.speech is None:
            return fallback_text
        try:
            result = self.speech.compose(
                scene=scene,
                facts=facts,
                fallback=fallback_text,
                required_tokens=required,
                relation_mode=relation_mode,
                at=now,
            )
        except Exception:  # noqa: BLE001 - 兜底文案永远可用
            return fallback_text
        return (result.text or fallback_text).strip()

    def _render_goal(
        self,
        *,
        goal: ResponseGoal,
        plan: ConversationPlan,
        tool_results: list[
            ToolExecutionResult
        ],
        now: datetime,
    ) -> str:
        kind = goal.kind
        preferred_name = (
            self.profile
            .preferred_name()
        )
        casual_alias = (
            self.profile
            .casual_alias()
        )

        cognition_context = (
            plan.metadata.get("cognition_context", {})
            if isinstance(plan.metadata, dict)
            else {}
        )
        if not isinstance(cognition_context, dict):
            cognition_context = {}

        # Lv27: 长期承诺相关话术。事实由 CommitmentService 算死，
        # 这里只决定"怎么说"：优先用语料库 + 模型重写，护栏不过就用
        # 确定性兜底文案，绝不让模型自己编时间和周次。
        if kind in {
            "commitment_clarify_question",
            "confirm_commitment",
            "commitment_status",
            "commitment_finish",
            "commitment_update_result",
        }:
            return self._render_commitment_goal(
                goal=goal,
                plan=plan,
                now=now,
                casual_alias=casual_alias,
            )

        if kind == "relationship_accountability":
            intent = cognition_context.get("intent", {})
            if not isinstance(intent, dict):
                intent = {}
            failure = intent.get("commitment", {})
            if not isinstance(failure, dict):
                failure = {}
            title = str(
                failure.get(
                    "commitment_title",
                    "之前想坚持的事",
                )
            )
            stance = str(
                intent.get(
                    "stance",
                    plan.metadata.get(
                        "accountability_stance",
                        "understanding_support",
                    ),
                )
            )
            if stance == "firm_support":
                return (
                    "这次我不替你找借口，玩过头就是玩过头。"
                    f"你之前把‘{title}’交给我监督，所以我会认真说你一句；"
                    "我认真不是想管你，是因为我真的在意你能不能做到自己想做的事。"
                    "不过我还是站你这边，今天能补一点就补一点，别直接摆烂。"
                )
            return (
                f"‘{title}’这次没做到，我知道了。"
                "如果是身体、突发事情或者真的被现实拖住，这种原因我能理解，"
                "不用为了向我交差硬撑。"
                "我会盯着是因为你之前把这份关心交给了我；我还是站你这边，状态回来我们再续上。"
            )

        if kind == "repair_user_model":
            return (
                "嗯，这里是我理解错了。"
                "你刚说的我会按新的理解来，不拿之前那个判断继续套你。"
            )

        if kind == "share_own_life":
            events = cognition_context.get("recent_events", [])
            if isinstance(events, list):
                candidates = [
                    item
                    for item in events
                    if isinstance(item, dict)
                    and item.get("shareable", True)
                ]
                if candidates:
                    event = next(
                        (item for item in reversed(candidates) if not item.get("shared_at")),
                        candidates[-1],
                    )
                    summary = str(event.get("summary", "")).strip()
                    detail = str(event.get("detail", "")).strip()
                    if summary and detail:
                        return f"今天嘛，{summary}{detail}"
                    if summary:
                        return f"今天嘛，{summary}"
            return "今天还行。我没一直等在聊天框里，自己也折腾了点东西。"

        if kind == "defer_own_story":
            return (
                "我本来还有件小事想跟你说。"
                "不过你先讲，你这边更要紧；等你缓过来我再说。"
            )

        if kind == "personal_perspective":
            return (
                "我先说我的感觉：这件事我不会只按一张利弊表替你算。"
                "我更在意它是不是已经持续让你难受、有没有把你真正想要的生活挤掉。"
                "这是我的判断，不是标准答案；我看偏了你就纠正我。"
            )

        if kind == "acknowledge_context":
            return (
                self._render_context_ack(
                    goal.source_text
                )
            )

        if (
            kind
            == "acknowledge_user_state"
        ):
            return (
                self._render_user_state_ack(
                    goal.source_text
                )
            )

        if kind == "answer_weather":
            result = self._tool_result(
                tool_results,
                "weather_lookup",
            )
            if (
                result is None
                or not result.ok
                or not isinstance(result.content, dict)
                or not result.content.get("available")
            ):
                return (
                    "天气接口刚才没连上，我暂时拿不到可靠结果。"
                    "先不乱猜，等它恢复再告诉你。"
                )
            summary = str(
                result.content.get(
                    "summary",
                    "",
                )
            ).strip()
            return summary or "我拿到天气了，不过这次结果不完整。"

        if kind in {
            "confirm_home_location",
            "confirm_temporary_location",
            "confirm_temporary_location_cleared",
            "confirm_weather_preferences",
        }:
            expected_action = {
                "confirm_home_location": "set_home_location",
                "confirm_temporary_location": "set_temporary_location",
                "confirm_temporary_location_cleared": "clear_temporary_location",
                "confirm_weather_preferences": "set_weather_preferences",
            }[kind]
            result = self._tool_result_matching(
                tool_results,
                "world_context_update",
                lambda item: isinstance(item.content, dict)
                and item.content.get("action") == expected_action,
            )
            if (
                result is None
                or not result.ok
                or not isinstance(result.content, dict)
            ):
                return "这次没改成功，我先不假装已经记住。"
            content = result.content
            if kind == "confirm_home_location":
                location = content.get("location", {})
                display = str(location.get("display_name", goal.source_text))
                return f"好，以后就看{display}的天气。"
            if kind == "confirm_temporary_location":
                location = content.get("location", {})
                display = str(location.get("display_name", goal.source_text))
                ends_at = str(location.get("ends_at", ""))
                try:
                    end = datetime.fromisoformat(ends_at).astimezone(now.tzinfo)
                    end_text = end.strftime("%m月%d日")
                except ValueError:
                    end_text = "这段时间结束"
                return (
                    f"知道了，这段时间先看{display}。"
                    f"到{end_text}以后再自动回到常用地点。"
                )
            if kind == "confirm_temporary_location_cleared":
                home = content.get("home_location", {})
                display = str(home.get("display_name", "原来的常用地点")) if isinstance(home, dict) else "原来的常用地点"
                return f"好，临时地点清掉了，之后继续看{display}。"
            prefs = content.get("preferences", {})
            if isinstance(prefs, dict):
                if not prefs.get("enabled", True):
                    return "好，天气这部分先关掉。你主动问的时候我再查。"
                if not prefs.get("daily_brief_enabled", True) and prefs.get("rain_alerts", False):
                    return "好，不每天播天气了。下雨或者天气明显不对劲时我再提醒你。"
            return "好，天气提醒按你刚说的来。"

        if kind == "confirm_interaction_preferences":
            result = self._tool_result(
                tool_results,
                "interaction_preferences_set",
            )
            if result is None or not result.ok or not isinstance(result.content, dict):
                return "这次主动联系设置没改成功，我先不乱承诺。"
            prefs = result.content.get("preferences", {})
            updated_keys = set(result.content.get("updated_keys", []))
            if not isinstance(prefs, dict):
                return "好，主动联系按你刚说的调整。"
            if "event_follow_up_enabled" in updated_keys:
                if prefs.get("event_follow_up_enabled", True):
                    return "好，之后你提到重要的事，我会在合适的时候问问结果。"
                return "好，之后我不再自动追问事情的结果，已经记着的这类回访也取消了。"
            if "weekend_suggestions_enabled" in updated_keys:
                return (
                    "好，周末我可以顺手给你一点轻量建议。"
                    if prefs.get("weekend_suggestions_enabled", True)
                    else "好，周末我不再主动给活动建议。"
                )
            if "memory_callback_enabled" in updated_keys:
                return (
                    "好，合适的时候我可以自然接回我们之前聊过的话题。"
                    if prefs.get("memory_callback_enabled", True)
                    else "好，我不再主动翻以前的话题。"
                )
            quiet_until = prefs.get("quiet_until")
            mode = str(prefs.get("proactive_frequency_mode", "normal"))
            if quiet_until:
                try:
                    until = datetime.fromisoformat(str(quiet_until)).astimezone(now.tzinfo)
                    return f"好，{until.strftime('%H:%M')}之前我不主动打扰你。"
                except ValueError:
                    return "好，这段时间我先安静一点。"
            if mode == "low":
                return "知道了，这几天我少主动找你一点。正式提醒还是会照常发。"
            if mode == "high":
                return "好，那我会比平时更主动一点，不过不会一直刷屏。"
            return "好，主动联系频率恢复平常。"

        if kind == "confirm_event_follow_up":
            result = self._tool_result(
                tool_results,
                "event_follow_up_create",
            )
            if (
                result is None
                or not result.ok
                or not isinstance(result.content, dict)
            ):
                return "我本来想之后问问你，不过这次没有真正记下来。"
            label = str(result.content.get("metadata", {}).get("event_label", goal.source_text))
            due_at = str(result.content.get("due_at", ""))
            when = self._friendly_due(due_at, now)
            return f"知道了。{when}等你忙完，我来问问{label}怎么样。"

        if kind == "confirm_event_follow_up_cancel":
            result = self._tool_result(
                tool_results,
                "plan_cancel",
            )
            cancelled = []
            if result is not None and result.ok and isinstance(result.content, dict):
                cancelled = result.content.get("cancelled", [])
            if cancelled:
                return "好，这件事我不再主动追问了。"
            return "好，我不会再主动问这件事。"

        if (
            kind
            == "confirm_preferred_name"
        ):
            name = (
                goal.source_text
                or preferred_name
            )
            return (
                f"好，我记下了。"
                f"以后叫你{name}。"
            )

        if (
            kind
            == "confirm_time_preference"
        ):
            result = self._tool_result(
                tool_results,
                "time_preferences_set",
            )
            if (
                result is not None
                and result.ok
                and isinstance(
                    result.content,
                    dict,
                )
            ):
                slot = str(
                    result.content.get(
                        "slot",
                        "",
                    )
                )
                settings = (
                    result.content.get(
                        "settings",
                        {},
                    )
                )
                time_value = str(
                    settings.get(
                        "time",
                        "",
                    )
                )
                model_meta = (
                    plan.metadata.get(
                        "model_schedule_judgement",
                        {},
                    )
                    or {}
                )
                purpose = str(
                    model_meta.get(
                        "purpose",
                        "",
                    )
                )
                if (
                    slot == "evening"
                    and (
                        "晚饭" in purpose
                        or "晚饭" in goal.source_text
                        or "吃饭" in purpose
                    )
                ):
                    return (
                        f"好，晚饭提醒改到 "
                        f"{time_value}。"
                        "到点我会叫你吃饭。"
                    )

                label = {
                    "morning": "早上",
                    "noon": "中午",
                    "evening": "晚上",
                }.get(
                    slot,
                    "那个时间",
                )
                return (
                    f"好，{label}的主动提醒"
                    f"改到 {time_value}。"
                )
            return (
                "这个时间我没改成功，"
                "你再告诉我一次。"
            )

        if kind == "confirm_schedule":
            result = self._tool_result(
                tool_results,
                "plan_create",
            )
            if (
                result is not None
                and result.ok
                and isinstance(
                    result.content,
                    dict,
                )
            ):
                raw_title = str(
                    result.content.get(
                        "title",
                        goal.source_text,
                    )
                )
                title = (
                    clean_schedule_title(
                        raw_title
                    )
                    or raw_title
                )
                due_at = str(
                    result.content.get(
                        "due_at",
                        "",
                    )
                )
                recurrence = str(
                    result.content.get(
                        "recurrence",
                        "none",
                    )
                )
                when = (
                    self._friendly_due(
                        due_at,
                        now,
                    )
                )
                clock = self._clock_from_due(
                    due_at,
                    now,
                )
                weekday = self._weekday_from_due(
                    due_at,
                    now,
                )
                return render_schedule_confirmation(
                    title=title,
                    due_at=due_at,
                    now=now,
                    recurrence=recurrence,
                    friendly_due=when,
                    clock=clock,
                    weekday=weekday,
                )
            return (
                "我想记下来，"
                "但计划没有保存成功。"
            )

        if kind == "clarify_schedule":
            return (
                goal.source_text
                or "你希望我具体什么时候提醒？"
            )

        if (
            kind
            == "cannot_confirm_future_message"
        ):
            return (
                "这次提醒没有真正设好，"
                "我不先假装答应。"
                "告诉我明确时间，我再记下来。"
            )

        if (
            kind
            == "clarify_schedule"
        ):
            return (
                goal.source_text
                or (
                    "告诉我具体什么时候提醒，"
                    "我再把它设好。"
                )
            )

        if kind == "list_plans":
            result = self._tool_result(
                tool_results,
                "plan_list",
            )
            plans = []
            if (
                result is not None
                and result.ok
                and isinstance(
                    result.content,
                    dict,
                )
            ):
                plans = (
                    result.content.get(
                        "plans",
                        [],
                    )
                )
            if not plans:
                return (
                    "现在没有需要我"
                    "主动提醒的计划。"
                )

            items = []
            for item in plans[:3]:
                due = self._friendly_due(
                    str(
                        item.get(
                            "due_at",
                            "",
                        )
                    ),
                    now,
                )
                items.append(
                    f"{due}{item.get('title', '未命名计划')}"
                )
            return (
                "我记着这些："
                + "；".join(items)
                + "。"
            )

        if (
            kind
            == "confirm_plan_cancel"
        ):
            result = self._tool_result(
                tool_results,
                "plan_cancel",
            )
            cancelled = []
            if (
                result is not None
                and result.ok
                and isinstance(
                    result.content,
                    dict,
                )
            ):
                cancelled = (
                    result.content.get(
                        "cancelled",
                        [],
                    )
                )
            if cancelled:
                return (
                    "好，相关提醒"
                    "已经取消了。"
                )
            return (
                "我没找到对应的提醒，"
                "可能已经取消过了。"
            )

        if kind == "answer_self_qq_nickname":
            nickname = str(
                self.agent_identity
                .qq_profile()
                .get("nickname", "正在等你说早安")
            )
            return f"我的 QQ 昵称是“{nickname}”。"

        if kind == "answer_self_qq_signature":
            signature = str(
                self.agent_identity
                .qq_profile()
                .get(
                    "signature",
                    "正在改写现实，先给你开个后门。本账号不支持注销，终身绑定你",
                )
            )
            return f"我的 QQ 签名是“{signature}”。"

        if kind == "answer_self_qq_account":
            qq = self.agent_identity.qq_profile()
            nickname = str(
                qq.get("nickname", "正在等你说早安")
            )
            if re.search(r"(?:QQ号|QQ账号|号码|多少)", goal.source_text):
                return (
                    "我有自己的 QQ，不过人设里没有配置可公开的具体号码，"
                    f"所以我不乱猜。昵称是“{nickname}”。"
                )
            return f"有呀。这个 QQ 就是我的，昵称是“{nickname}”。"

        if (
            kind
            == "answer_self_identity"
        ):
            return "我是银狼。"

        if (
            kind
            == "answer_self_zodiac"
        ):
            return "我是双子座。"

        if (
            kind
            == "answer_self_next_birthday_age"
        ):
            next_birthday = (
                self.agent_identity
                .next_birthday(
                    now.date()
                )
            )
            next_age = (
                self.agent_identity
                .age_after_next_birthday(
                    now.date()
                )
            )
            return (
                f"到{next_birthday.year}年"
                f"{next_birthday.month}月"
                f"{next_birthday.day}日生日，"
                f"我就{next_age}岁了。"
            )

        if (
            kind
            == "answer_self_birthday"
        ):
            birthday = (
                self.agent_identity
                .birthday_display()
            )
            return (
                f"我的生日是{birthday}。"
            )

        if (
            kind
            == "answer_self_age"
        ):
            age = (
                self.agent_identity
                .age_on(
                    now.date()
                )
            )
            next_birthday = (
                self.agent_identity
                .next_birthday(
                    now.date()
                )
            )
            next_age = (
                self.agent_identity
                .age_after_next_birthday(
                    now.date()
                )
            )

            if (
                now.date()
                == next_birthday
            ):
                return (
                    f"今天刚好是我生日。"
                    f"我已经{age}岁了。"
                )

            return (
                f"我现在{age}岁。"
                f"到{next_birthday.year}年"
                f"{next_birthday.month}月"
                f"{next_birthday.day}日生日，"
                f"就{next_age}岁了。"
            )

        if (
            kind
            == "answer_address_preference"
        ):
            return (
                f"平时叫你"
                f"{preferred_name}。"
                "想亲近一点的时候，"
                f"就叫你{casual_alias}。"
            )

        if (
            kind
            == "confirm_identity_memory"
        ):
            previous = int(
                plan.metadata.get(
                    "previous_identity_checks",
                    0,
                )
            )
            if previous == 0:
                return (
                    f"当然记得你，"
                    f"{preferred_name}。"
                    "我怎么会忘。"
                )
            if previous == 1:
                return (
                    f"刚问过呀，"
                    f"{casual_alias}。"
                    "我当然记得。"
                )
            return (
                f"还在确认啊，"
                f"{preferred_name}？"
                "我没忘。"
                "怎么突然这么不放心？"
            )

        if (
            kind
            == "answer_message_time"
        ):
            result = self._tool_result(
                tool_results,
                "conversation_history_lookup",
            )
            if (
                result is None
                or not result.ok
                or not isinstance(
                    result.content,
                    dict,
                )
                or not result.content.get(
                    "found"
                )
            ):
                return (
                    "我没找到那条消息的"
                    "精确时间，所以不乱猜。"
                )

            user_at = str(
                result.content.get(
                    "user_at",
                    "",
                )
            )
            try:
                timestamp = (
                    datetime.fromisoformat(
                        user_at
                    )
                )
                time_text = (
                    timestamp.strftime(
                        "%H:%M:%S"
                    )
                )
            except ValueError:
                time_text = user_at

            mode = str(
                result.content.get(
                    "mode",
                    "",
                )
            )
            keyword = str(
                result.content.get(
                    "keyword",
                    "",
                )
            )
            if (
                mode == "keyword"
                and keyword
            ):
                return (
                    f"你开始{keyword}那条"
                    f"消息是在 {time_text} "
                    "发的。"
                )

            return (
                "你刚才那条消息是在 "
                f"{time_text} 发的。"
            )

        if kind == "answer_calendar_query":
            result = self._tool_result(
                tool_results,
                "calendar_query",
            )
            return self._calendar_answer(
                result=result,
                plan=plan,
            )

        if (
            kind
            == "answer_current_time"
        ):
            time_value = (
                self._time_value(
                    tool_results
                )
            )
            previous = int(
                plan.metadata.get(
                    "previous_time_questions",
                    0,
                )
            )
            if previous == 0:
                return (
                    f"现在 {time_value}。"
                )
            if previous == 1:
                return (
                    f"还是 {time_value}，"
                    f"{casual_alias}。"
                )
            return (
                "时间没跑那么快，"
                f"还是 {time_value}。"
            )

        if kind in {
            "answer_past_event",
            "answer_profile_details",
            "continue_conversation",
        }:
            return ""

        return ""

    @staticmethod
    def _tool_result_matching(
        results: list[ToolExecutionResult],
        name: str,
        predicate,
    ) -> ToolExecutionResult | None:
        for result in results:
            if result.name == name and predicate(result):
                return result
        return None

    @staticmethod
    def _tool_result(
        results: list[
            ToolExecutionResult
        ],
        name: str,
    ) -> ToolExecutionResult | None:
        for result in results:
            if result.name == name:
                return result
        return None

    @staticmethod
    def _calendar_answer(
        *,
        result: ToolExecutionResult | None,
        plan: ConversationPlan,
    ) -> str:
        if (
            result is None
            or not result.ok
            or not isinstance(result.content, dict)
        ):
            return "这次日期没有解析成功，我先不乱猜。"

        content = result.content
        query_kind = str(content.get("query_kind", ""))
        relation = str(content.get("relation_label", "")).strip()
        year = int(content.get("year", 0))
        month = int(content.get("month", 0))
        day = int(content.get("day", 0))
        weekday = str(content.get("weekday", "")).strip()
        include_year = bool(content.get("include_year", False))

        temporal = plan.metadata.get("temporal_query")
        if isinstance(temporal, dict):
            relation = str(temporal.get("relation_label", relation)).strip()
            include_year = bool(temporal.get("include_year", include_year))

        natural_subject = (
            relation
            if relation and not re.search(r"\d", relation)
            else ""
        )
        date_text = (
            f"{year}年{month}月{day}日"
            if include_year
            else f"{month}月{day}日"
        )

        if query_kind == "weekday":
            if natural_subject:
                return f"{natural_subject}是{weekday}。"
            return f"{date_text}是{weekday}。"

        if query_kind == "date":
            if natural_subject:
                return f"{natural_subject}是{date_text}。"
            return f"是{date_text}。"

        if natural_subject:
            return f"{natural_subject}是{date_text}，{weekday}。"
        return f"{date_text}是{weekday}。"

    @staticmethod
    def _time_value(
        results: list[
            ToolExecutionResult
        ],
    ) -> str:
        result = (
            ConversationExecutor
            ._tool_result(
                results,
                "time_now",
            )
        )
        if (
            result is not None
            and result.ok
            and isinstance(
                result.content,
                dict,
            )
        ):
            value = result.content.get(
                "time"
            )
            if isinstance(
                value,
                str,
            ):
                return value[:5]
        return "刚才这个时间"

    @staticmethod
    def _clock_from_due(
        due_at: str,
        now: datetime,
    ) -> str:
        try:
            due = datetime.fromisoformat(
                due_at
            )
        except ValueError:
            return "到点"

        if due.tzinfo is None:
            due = due.replace(
                tzinfo=now.tzinfo
            )
        return due.astimezone(
            now.tzinfo
        ).strftime("%H:%M")

    @staticmethod
    def _weekday_from_due(
        due_at: str,
        now: datetime,
    ) -> str:
        labels = (
            "一",
            "二",
            "三",
            "四",
            "五",
            "六",
            "日",
        )
        try:
            due = datetime.fromisoformat(
                due_at
            )
        except ValueError:
            return ""

        if due.tzinfo is None:
            due = due.replace(
                tzinfo=now.tzinfo
            )
        return labels[
            due.astimezone(
                now.tzinfo
            ).weekday()
        ]

    @staticmethod
    def _friendly_due(
        due_at: str,
        now: datetime,
    ) -> str:
        try:
            due = datetime.fromisoformat(
                due_at
            )
        except ValueError:
            return "到时候"

        if due.tzinfo is None:
            due = due.replace(
                tzinfo=now.tzinfo
            )
        due = due.astimezone(
            now.tzinfo
        )

        delta_days = (
            due.date()
            - now.date()
        ).days
        time_text = due.strftime(
            "%H:%M"
        )

        if delta_days == 0:
            return (
                f"今天 {time_text} "
            )
        if delta_days == 1:
            if due.hour < 11:
                return "明天早上"
            return (
                f"明天 {time_text} "
            )
        if delta_days == 2:
            return (
                f"后天 {time_text} "
            )
        return (
            due.strftime(
                "%m月%d日 %H:%M "
            )
        )

    @staticmethod
    def _render_user_state_ack(
        state_text: str,
    ) -> str:
        if (
            "睡" in state_text
            and re.search(
                r"(不错|很好|舒服|踏实|香)",
                state_text,
            )
        ):
            return (
                "听起来这次午觉"
                "睡得挺舒服的。"
            )

        if (
            re.search(
                r"(开发|写代码|做项目)",
                state_text,
            )
            and re.search(
                r"(忘记|晕|累|困|烦)",
                state_text,
            )
        ):
            return (
                "一直盯着开发确实容易"
                "把脑子绕晕。先缓一下，"
                "别硬撑。"
            )

        if re.search(
            r"(晕|不舒服|头疼|生病)",
            state_text,
        ):
            return (
                "听着状态不太舒服。"
                "先缓一缓，别勉强自己。"
            )

        if re.search(
            r"(累|困|压力|焦虑|烦)",
            state_text,
        ):
            return (
                "听起来有点累了。"
                "先让自己喘口气。"
            )

        if re.search(
            r"(开心|不错|舒服|放松)",
            state_text,
        ):
            return (
                "那挺好的。"
                "听你这么说，我也放心些。"
            )

        return (
            "嗯，我听到了。"
            "这部分我不会当成"
            "无关前缀跳过去。"
        )

    @staticmethod
    def _render_context_ack(
        context_text: str,
    ) -> str:
        if (
            "吃过" in context_text
            and (
                "睡" in context_text
                or "午觉"
                in context_text
            )
        ):
            return (
                "好吧，是我没跟上。"
                "你都吃过饭、"
                "连午觉都睡完了。"
            )
        if "只是" in context_text:
            return (
                "懂了，是我刚才"
                "想多了。"
            )
        return (
            "嗯，我知道了。"
            "刚才是我判断得太快。"
        )
