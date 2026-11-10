from __future__ import annotations

import asyncio
from datetime import (
    datetime,
    timedelta,
)
import json
import re

from .config import AppConfig
from .cognition import (
    CognitiveStateManager,
)
from .commitment import (
    CommitmentService,
    CommitmentStore,
    ClarificationStore,
)
from .dialogue.corpus import CorpusStore
from .dialogue.corpus_learn import CorpusLearner
from .dialogue.persona import PersonaLibrary
from .dialogue.speech import SpeechComposer
from .diagnostics import Doctor
from .delivery import (
    MessageDispatcher,
    MessageSink,
    OutboundMessage,
    ReplyBundle,
)
from .llm import (
    AnthropicCompatibleClient,
    BaseLLMClient,
    EchoLLMClient,
)
from .memory import (
    AgentIdentityManager,
    DailySummaryManager,
    JsonlRAGStore,
    ReflectionEngine,
    ShortTermMemory,
    UserProfileManager,
)
from .models import ChatMessage
from .pae import (
    ConversationExecutor,
    ConversationPlanner,
    ModelScheduleJudge,
)
from .proactive import (
    AsyncProactiveScheduler,
    PlanManager,
    ProactiveExecutor,
    ProactivePlanner,
    ProactiveStateStore,
    TimeManager,
)
from .prompts import PromptBuilder
from .reply_gate import ReplyDecisionAgent
from .reply_gate.contracts import ReplyDecision
from .response_completion import ResponseCompletionAgent
from .world import (
    ContextualCareComposer,
    Lv17IntentAnalyzer,
    OpenMeteoWeatherProvider,
    WeatherService,
    WorldContextManager,
)
from .tools import (
    CalendarQueryTool,
    ConversationHistoryLookupTool,
    CurrentTimeTool,
    PlanCancelTool,
    PlanCreateTool,
    PlanListTool,
    PreferredNameTool,
    ProfileUpdateTool,
    TimePreferencesGetTool,
    TimePreferencesSetTool,
    ToolRegistry,
    EventFollowUpCreateTool,
    InteractionPreferencesSetTool,
    WeatherLookupTool,
    WorldContextGetTool,
    WorldContextUpdateTool,
)


class SilverWolfAgent:
    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        llm: BaseLLMClient | None = None,
        planner_llm: (
            BaseLLMClient
            | None
        ) = None,
        reply_gate_llm: (
            BaseLLMClient
            | None
        ) = None,
    ) -> None:
        self.config = (
            config
            or AppConfig.from_env()
        )
        self.llm = (
            llm
            or self._build_default_llm()
        )
        self.planner_llm = (
            planner_llm
            or (
                llm
                if llm is not None
                else self._build_planner_llm()
            )
        )

        self.reply_gate_llm = (
            reply_gate_llm
            if reply_gate_llm is not None
            else self._build_reply_gate_llm()
        )

        # Lv27: 语料重写用一个独立的高温小模型客户端，避免影响主对话温度。
        self.corpus_llm = self._build_corpus_llm()

        self.profile = (
            UserProfileManager()
        )
        self.memory = (
            ShortTermMemory()
        )
        self.rag = JsonlRAGStore(
            decay_enabled=self.config.memory_decay_enabled,
            weight_relevance=self.config.memory_weight_relevance,
            weight_importance=self.config.memory_weight_importance,
            weight_recency=self.config.memory_weight_recency,
            stability_base_days=self.config.memory_stability_base_days,
        )
        self.agent_identity = (
            AgentIdentityManager()
        )
        self.cognition = (
            CognitiveStateManager()
        )
        # Lv27: 语料库 + 语料驱动的话术合成。
        self.corpus = CorpusStore(
            enabled=self.config.corpus_enabled,
            cooldown=self.config.corpus_cooldown,
            learned_share=self.config.corpus_learned_share,
        )
        self.speech = SpeechComposer(
            llm=self.corpus_llm,
            corpus=self.corpus,
            enabled=self.config.corpus_enabled,
            max_overlap=self.config.corpus_max_overlap,
            samples=self.config.corpus_samples,
            phrase_mode=self.config.corpus_phrase_mode,
        )
        # Lv29: 语料自我生长（候选 → 人工审核 → 转正 → 淘汰）
        self.corpus_learner = CorpusLearner(
            corpus=self.corpus,
            enabled=self.config.corpus_learning_enabled,
            learn_from_user=self.config.corpus_learn_from_user,
            phrase_mode=self.config.corpus_phrase_mode,
            min_chars=self.config.corpus_candidate_min_chars,
            max_chars=self.config.corpus_candidate_max_chars,
            max_overlap=self.config.corpus_max_overlap,
            retire_days=self.config.corpus_retire_days,
            scene_limit=self.config.corpus_scene_limit,
            privacy_filter=self.config.corpus_privacy_filter,
        )
        self.last_corpus_feedback: str = ""
        self.daily = DailySummaryManager(
            rag=self.rag,
            memory=self.memory,
            profile=self.profile,
        )
        # Lv30: 分层人设（核心 + 世界书模块）
        self.persona_library = PersonaLibrary(
            enabled=self.config.persona_layers_enabled,
            core_max_chars=self.config.persona_core_max_chars,
            budget_chars=self.config.persona_budget_chars,
        )
        self.prompt_builder = (
            PromptBuilder(
                agent_identity=(
                    self.agent_identity
                ),
                persona_library=(
                    self.persona_library
                ),
            )
        )

        self.reply_decider = (
            ReplyDecisionAgent(
                llm=self.reply_gate_llm,
                enabled=(
                    self.config
                    .reply_gate_enabled
                ),
                llm_enabled=(
                    self.config
                    .reply_gate_llm_enabled
                ),
                minimum_silence_confidence=(
                    self.config
                    .reply_gate_min_silence_confidence
                ),
                context_messages=(
                    self.config
                    .reply_gate_context_messages
                ),
            )
        )

        self.completion_decider = ResponseCompletionAgent(
            llm=self.planner_llm,
            enabled=self.config.completion_agent_enabled,
            llm_enabled=self.config.completion_llm_enabled,
            minimum_incomplete_confidence=(
                self.config.completion_min_incomplete_confidence
            ),
        )

        self.time_manager = (
            TimeManager(
                timezone=(
                    self.config.timezone
                ),
                jitter_enabled=(
                    self.config.proactive_jitter_enabled
                ),
                jitter_minutes=(
                    self.config.proactive_jitter_minutes
                ),
                pinned_days=(
                    self.config.proactive_pinned_days
                ),
            )
        )
        self.plan_manager = (
            PlanManager()
        )
        # Lv27: 长期任务承诺（澄清问答 + 多周提醒）。
        self.commitment_service = CommitmentService(
            plan_manager=self.plan_manager,
            store=CommitmentStore(),
            clarify_store=ClarificationStore(),
            enabled=self.config.commitment_enabled,
            default_clock=self.config.commitment_default_clock,
            max_weeks=self.config.commitment_max_weeks,
            soft_weekend=self.config.commitment_soft_weekend,
            clarify_expiry_hours=self.config.commitment_clarify_expiry_hours,
            max_questions=self.config.commitment_clarify_max_questions,
        )
        self.proactive_state = (
            ProactiveStateStore()
        )
        # Lv28: 每周反思。只影响她怎么想，不主动播报。
        self.reflection = ReflectionEngine(
            rag=self.rag,
            cognition=self.cognition,
            memory=self.memory,
            commitment_store=self.commitment_service.store,
            llm=self.planner_llm,
            enabled=self.config.reflection_enabled,
            weekday=self.config.reflection_weekday,
            hour=self.config.reflection_hour,
            importance_threshold=self.config.reflection_importance_threshold,
            max_evidence=self.config.reflection_max_evidence,
        )
        self.last_reflection_summary: str = ""
        self.weather_provider = OpenMeteoWeatherProvider(
            timeout_seconds=self.config.weather_http_timeout_seconds
        )
        self.world_context = WorldContextManager(
            self.profile,
            geocoder=self.weather_provider,
        )
        self.weather_service = WeatherService(
            context_manager=self.world_context,
            provider=self.weather_provider,
            cache_minutes=self.config.weather_cache_minutes,
        )
        self.lv17_intent_analyzer = Lv17IntentAnalyzer()

        self.tool_registry = (
            ToolRegistry()
        )
        self.tool_registry.register(
            CurrentTimeTool(
                self.config.timezone
            )
        )
        self.tool_registry.register(
            CalendarQueryTool()
        )
        self.tool_registry.register(
            ConversationHistoryLookupTool(
                self.memory
            )
        )
        self.tool_registry.register(
            ProfileUpdateTool(
                self.profile
            )
        )
        self.tool_registry.register(
            PreferredNameTool(
                self.profile
            )
        )
        self.tool_registry.register(
            PlanCreateTool(
                self.plan_manager
            )
        )
        self.tool_registry.register(
            PlanListTool(
                self.plan_manager
            )
        )
        self.tool_registry.register(
            PlanCancelTool(
                self.plan_manager
            )
        )
        self.tool_registry.register(
            TimePreferencesGetTool(
                self.time_manager
            )
        )
        self.tool_registry.register(
            TimePreferencesSetTool(
                self.time_manager
            )
        )
        self.tool_registry.register(
            WeatherLookupTool(
                self.weather_service,
                self.now,
            )
        )
        self.tool_registry.register(
            WorldContextGetTool(
                self.world_context,
                self.now,
            )
        )
        self.tool_registry.register(
            WorldContextUpdateTool(
                self.world_context
            )
        )
        self.tool_registry.register(
            InteractionPreferencesSetTool(
                self.world_context,
                self.plan_manager,
            )
        )
        self.tool_registry.register(
            EventFollowUpCreateTool(
                self.plan_manager
            )
        )

        self.schedule_judge = (
            ModelScheduleJudge(
                llm=self.planner_llm,
                enabled=(
                    self.config
                    .planner_llm_enabled
                ),
                minimum_confidence=(
                    self.config
                    .planner_min_confidence
                ),
            )
        )

        self.planner = (
            ConversationPlanner(
                profile=self.profile,
                memory=self.memory,
                time_manager=(
                    self.time_manager
                ),
                plan_manager=(
                    self.plan_manager
                ),
                message_gap_seconds=(
                    self.config
                    .message_gap_seconds
                ),
                agent_identity=(
                    self.agent_identity
                ),
                schedule_judge=(
                    self.schedule_judge
                ),
                lv17_intent_analyzer=(
                    self.lv17_intent_analyzer
                ),
                world_context=(
                    self.world_context
                ),
                cognition=(
                    self.cognition
                ),
                commitment_service=(
                    self.commitment_service
                ),
            )
        )
        self.executor = (
            ConversationExecutor(
                llm=self.llm,
                tool_registry=(
                    self.tool_registry
                ),
                profile=self.profile,
                memory=self.memory,
                rag=self.rag,
                prompt_builder=(
                    self.prompt_builder
                ),
                agent_identity=(
                    self.agent_identity
                ),
                completion_agent=self.completion_decider,
                completion_max_rounds=self.config.completion_max_rounds,
                completion_max_chars=self.config.completion_max_chars,
                speech=self.speech,
            )
        )

        self.dispatcher = (
            MessageDispatcher(
                default_gap_seconds=(
                    self.config
                    .message_gap_seconds
                )
            )
        )
        self.proactive_planner = (
            ProactivePlanner(
                profile=self.profile,
                memory=self.memory,
                message_gap_seconds=(
                    self.config
                    .message_gap_seconds
                ),
                state=(
                    self.proactive_state
                ),
                template_history_limit=(
                    self.config
                    .proactive_template_history_limit
                ),
                weather_service=(
                    self.weather_service
                ),
                world_context=(
                    self.world_context
                ),
                context_composer=(
                    ContextualCareComposer()
                ),
                cognition=(
                    self.cognition
                ),
                commitment_service=(
                    self.commitment_service
                ),
                silence_return_hours=(
                    self.config.silence_return_hours
                ),
                speech=self.speech,
                speech_enabled=(
                    self.config.proactive_speech_enabled
                ),
                speech_timeout_seconds=(
                    self.config.proactive_speech_timeout_seconds
                ),
                speech_max_chars=(
                    self.config.proactive_speech_max_chars
                ),
                speech_scenes=tuple(
                    item.strip()
                    for item in self.config.proactive_speech_scenes.split(",")
                    if item.strip()
                ),
                speech_samples=(
                    self.config.proactive_speech_samples
                ),
                self_share_enabled=(
                    self.config.self_share_enabled
                ),
                self_share_per_week=(
                    self.config.self_share_per_week
                ),
                self_share_min_age_days=(
                    self.config.self_share_min_age_days
                ),
                self_share_max_age_days=(
                    self.config.self_share_max_age_days
                ),
                self_share_setback_days=(
                    self.config.self_share_setback_days
                ),
                self_share_kind_cooldown_days=(
                    self.config.self_share_kind_cooldown_days
                ),
            )
        )
        self.proactive_executor = (
            ProactiveExecutor()
        )
        self.scheduler = (
            AsyncProactiveScheduler(
                time_manager=(
                    self.time_manager
                ),
                plan_manager=(
                    self.plan_manager
                ),
                state=(
                    self.proactive_state
                ),
                planner=(
                    self.proactive_planner
                ),
                executor=(
                    self.proactive_executor
                ),
                memory=self.memory,
                dispatcher=(
                    self.dispatcher
                ),
                now_provider=self.now,
                poll_seconds=(
                    self.config
                    .scheduler_poll_seconds
                ),
                follow_up_enabled=(
                    self.config
                    .proactive_follow_up_enabled
                ),
                follow_up_seconds=(
                    self.config
                    .proactive_follow_up_seconds
                ),
                follow_up_expiry_seconds=(
                    self.config
                    .proactive_follow_up_expiry_seconds
                ),
                commitment_service=(
                    self.commitment_service
                ),
            )
        )

        self.last_reply_decision_json = ""
        self.last_plan_json = ""
        self.last_execution_json = ""

    def _build_default_llm(
        self,
    ) -> BaseLLMClient:
        if not self.config.api_key:
            return EchoLLMClient()

        return (
            AnthropicCompatibleClient(
                api_key=(
                    self.config.api_key
                ),
                base_url=(
                    self.config.base_url
                ),
                model=self.config.model,
                max_tokens=(
                    self.config.max_tokens
                ),
                temperature=(
                    self.config.temperature
                ),
                max_retries=(
                    self.config.max_retries
                ),
                retry_base_seconds=(
                    self.config
                    .retry_base_seconds
                ),
            )
        )

    def _build_planner_llm(
        self,
    ) -> BaseLLMClient:
        if (
            not self.config.api_key
            or not self.config
            .planner_llm_enabled
        ):
            return EchoLLMClient()

        return (
            AnthropicCompatibleClient(
                api_key=(
                    self.config.api_key
                ),
                base_url=(
                    self.config.base_url
                ),
                model=self.config.model,
                max_tokens=(
                    self.config
                    .planner_max_tokens
                ),
                temperature=(
                    self.config
                    .planner_temperature
                ),
                max_retries=(
                    self.config.max_retries
                ),
                retry_base_seconds=(
                    self.config
                    .retry_base_seconds
                ),
            )
        )

    def _build_corpus_llm(
        self,
    ) -> BaseLLMClient | None:
        """Lv27: 语料重写专用客户端（高温、小 token）。

        没有 API Key 或语料功能关闭时返回 None，SpeechComposer 会直接
        使用确定性兜底文案，整条链路不依赖网络。
        """
        if (
            not self.config.api_key
            or not self.config.corpus_enabled
        ):
            return None

        return AnthropicCompatibleClient(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            model=self.config.model,
            max_tokens=200,
            temperature=self.config.corpus_temperature,
            max_retries=self.config.max_retries,
            retry_base_seconds=self.config.retry_base_seconds,
        )

    def _build_reply_gate_llm(
        self,
    ) -> BaseLLMClient | None:
        if (
            not self.config.api_key
            or not self.config
            .reply_gate_enabled
            or not self.config
            .reply_gate_llm_enabled
        ):
            return None
        return (
            AnthropicCompatibleClient(
                api_key=(
                    self.config.api_key
                ),
                base_url=(
                    self.config.base_url
                ),
                model=(
                    self.config
                    .reply_gate_model
                    or self.config.model
                ),
                max_tokens=(
                    self.config
                    .reply_gate_max_tokens
                ),
                temperature=(
                    self.config
                    .reply_gate_temperature
                ),
                max_retries=(
                    self.config.max_retries
                ),
                retry_base_seconds=(
                    self.config
                    .retry_base_seconds
                ),
            )
        )

    @property
    def offline(self) -> bool:
        return isinstance(
            self.llm,
            EchoLLMClient,
        )

    def now(self) -> datetime:
        return datetime.now(
            self.config.zoneinfo()
        )

    def _complete_text(
        self,
        prompt: str,
    ) -> str:
        response = self.llm.complete(
            system=(
                "你是负责压缩记忆的"
                "辅助模块，只忠实总结，"
                "不扮演角色。"
            ),
            messages=[
                ChatMessage(
                    role="user",
                    content=prompt,
                )
            ],
            tools=None,
        )
        return response.text

    def _compact_memory_if_needed(
        self,
    ) -> None:
        if not (
            self.memory
            .needs_compaction()
        ):
            return

        def summarize(
            source: str,
        ) -> str:
            if self.offline:
                return source[-1800:]

            return self._complete_text(
                self.prompt_builder
                .compact_memory_prompt(
                    source
                )
            )

        self.memory.compact(
            summarize
        )

    def _rollover_if_needed(
        self,
        now: datetime,
    ) -> None:
        if (
            self.daily
            .should_rollover(
                now.date()
            )
        ):
            yesterday = (
                now.date()
                - timedelta(days=1)
            )
            self.generate_daily_summary(
                target_date=yesterday
            )

        self.daily.mark_active_date(
            now.date()
        )

    def maybe_reflect(
        self,
        now: datetime | None = None,
        *,
        trigger: str = "",
        force: bool = False,
    ) -> dict:
        """Lv28: 到点就跑一次每周反思（一天最多一次）。

        反思失败绝不能影响正常聊天，因此所有异常在这里被吞掉。
        """
        engine = getattr(self, "reflection", None)
        if engine is None:
            return {"ran": False, "trigger": "", "source": "disabled"}
        moment = now or self.now()
        try:
            result = engine.run(moment, trigger=trigger, force=force)
        except Exception as exc:  # noqa: BLE001 - 反思是可选增强
            return {"ran": False, "trigger": trigger, "source": f"error:{exc}"}
        if result.ran and result.week_summary:
            self.last_reflection_summary = result.week_summary
        return result.to_dict()

    # Lv29: 语料反馈指令（控制指令，不进 PAE）
    CORPUS_APPROVE_RE = re.compile(r"(这句不错|这句挺好|就这样说|记住这句|这句我喜欢)")
    CORPUS_REJECT_RE = re.compile(r"(别这样说|别这么讲|太肉麻|别说这句|换个说法)")
    # Lv32: 用户纠正 = 不给弱正向
    CORPUS_CORRECTION_RE = re.compile(
        r"(不是这样|别这么说|你搞错了|你想错了|太肉麻|别这样说|不对吧)"
    )

    def _maybe_record_implicit_signal(
        self,
        text: str,
        now: datetime,
    ) -> None:
        """Lv32: 她说完话后你继续聊 → 给上一句记一次弱正向。

        只影响 /corpus review 的排序，绝不自动转正；
        你不回复**不**记任何负面。
        """
        if not getattr(self.config, "corpus_implicit_signal_enabled", True):
            return
        learner = getattr(self, "corpus_learner", None)
        last = getattr(self, "last_interactive_reply", None)
        if learner is None or not isinstance(last, dict):
            return
        moment = last.get("at")
        content = str(last.get("text", "") or "").strip()
        if not isinstance(moment, datetime) or not content:
            return
        if moment.tzinfo is None and now.tzinfo is not None:
            moment = moment.replace(tzinfo=now.tzinfo)
        window_minutes = int(
            getattr(self.config, "corpus_implicit_window_minutes", 10)
        )
        window = max(1, window_minutes) * 60
        if (now - moment).total_seconds() > window:
            return
        if self.CORPUS_CORRECTION_RE.search(text):
            return
        # 明确的评价指令走 approve/reject 通道，不重复记弱信号
        if self.CORPUS_APPROVE_RE.search(text) or self.CORPUS_REJECT_RE.search(text):
            return
        try:
            learner.record_implicit_signal(content)
        except Exception:  # noqa: BLE001
            pass


    def _last_assistant_text(self) -> str:
        try:
            history = self.memory.recent_chat_messages(limit=6)
        except Exception:  # noqa: BLE001
            return ""
        for item in reversed(history):
            if str(item.get("role")) == "assistant":
                return str(item.get("content", "")).strip()
        return ""

    def _corpus_ack(
        self,
        content: str,
        now: datetime,
    ) -> ReplyBundle:
        return ReplyBundle(
            messages=[
                OutboundMessage(
                    content=content,
                    weight=90,
                    category="corpus_feedback",
                    source="interactive",
                    sequence=0,
                    delay_seconds=0.0,
                    goal_kinds=["corpus_feedback"],
                )
            ]
        )

    def _handle_corpus_feedback(
        self,
        text: str,
        now: datetime,
    ) -> ReplyBundle | None:
        learner = getattr(self, "corpus_learner", None)
        if learner is None or not learner.enabled:
            return None

        approve = bool(self.CORPUS_APPROVE_RE.search(text))
        reject = bool(self.CORPUS_REJECT_RE.search(text))
        if not approve and not reject:
            return None

        last = self._last_assistant_text()
        if not last:
            self.last_corpus_feedback = "no_target"
            return self._corpus_ack("现在没有可记的上一句。", now)

        if reject:
            done = learner.reject_text(last, now)
            self.last_corpus_feedback = (
                "rejected" if done else "reject_missed"
            )
            return self._corpus_ack(
                "行，以后不这么说。" if done else "这句我本来也没在用。",
                now,
            )

        result = learner.consider_assistant_text(
            last,
            scene="chat_general",
            now=now,
            source="inline_approve",
        )
        if not result.get("accepted"):
            self.last_corpus_feedback = (
                f"approve_blocked:{result.get('reason', '')}"
            )
            return self._corpus_ack("这句没通过筛选，先不学。", now)

        entry = learner.approve(str(result["candidate_id"]), now)
        self.last_corpus_feedback = "approved" if entry else "approve_failed"
        return self._corpus_ack("好，这句我留着。", now)

    def _learn_from_reply(
        self,
        bundle: ReplyBundle,
        now: datetime,
    ) -> None:
        learner = getattr(self, "corpus_learner", None)
        if learner is None or not learner.enabled:
            return
        content = bundle.joined_text().strip()
        if not content:
            return
        try:
            learner.consider_assistant_text(
                content,
                scene="chat_general",
                now=now,
            )
        except Exception:  # noqa: BLE001 - 学习失败不影响对话
            pass

    def persona_snapshot(self, text: str = "") -> dict:
        """Lv30: 人设分层状态与本轮会注入的模块。"""
        library = getattr(self, "persona_library", None)
        if library is None:
            return {}
        base = library.stats()
        base["last_selection"] = getattr(
            self.prompt_builder,
            "last_persona_selection",
            {},
        )
        if text:
            selection = library.select(user_input=text)
            base["dry_run"] = selection.describe()
        return base

    def doctor_report(self, *, now: datetime | None = None) -> dict:
        """Lv33: 只读体检——把"跑没跑"变成确定性判定。"""
        moment = now or self.now()
        report = Doctor(
            agent=self,
            now=moment,
            stale_days=int(
                getattr(self.config, "doctor_stale_days", 3)
            ),
        ).run()
        payload = report.to_dict()
        payload["text"] = report.render()
        return payload

    def status_report(self, *, now: datetime | None = None) -> dict:
        """Lv33: 精简总览，把散落的 snapshot 合成一份。"""
        from . import __version__

        moment = now or self.now()
        memory_snapshot = self.memory.snapshot()
        turns = memory_snapshot.get("recent_turns", [])
        plans = self.plans_snapshot()
        pending_plans = [plan for plan in plans if plan.get("status") == "pending"]
        kind_count: dict[str, int] = {}
        for plan in pending_plans:
            kind = str(
                (plan.get("metadata") or {}).get("kind") or "普通计划"
            )
            kind_count[kind] = kind_count.get(kind, 0) + 1

        proactive_state = (
            self.proactive_state.snapshot()
            if hasattr(self, "proactive_state")
            else {}
        )
        shares = proactive_state.get("self_share_history", [])
        rag_stats = self.rag.stats()
        corpus_stats = self.corpus.stats()
        learning_stats = (
            self.corpus_learner.stats(moment)
            if hasattr(self, "corpus_learner")
            else {}
        )
        persona_stats = (
            self.persona_library.stats()
            if hasattr(self, "persona_library")
            else {}
        )
        selection = getattr(
            getattr(self, "prompt_builder", None),
            "last_persona_selection",
            {},
        ) or {}

        payload = {
            "version": __version__,
            "model": self.config.model,
            "timezone": self.config.timezone,
            "conversation": {
                "short_term_turns": len(turns) if isinstance(turns, list) else 0,
            },
            "plans": {
                "pending": len(pending_plans),
                "by_kind": kind_count,
            },
            "proactive": {
                "self_share_this_week": len(shares) if isinstance(shares, list) else 0,
            },
            "memory": rag_stats,
            "corpus": {**corpus_stats, **learning_stats},
            "persona": {
                "core_chars": persona_stats.get("core_chars", 0),
                "modules": persona_stats.get("modules", 0),
                "last_injected_chars": selection.get("total_chars", 0),
                "last_modules": [
                    str(item.get("name"))
                    for item in (selection.get("modules") or [])
                ],
            },
        }
        payload["text"] = self._render_status(payload)
        return payload

    @staticmethod
    def _render_status(payload: dict) -> str:
        plans = payload.get("plans", {})
        by_kind = plans.get("by_kind", {})
        kinds = " / ".join(
            f"{name} {count}" for name, count in by_kind.items()
        ) or "无"
        memory = payload.get("memory", {})
        corpus = payload.get("corpus", {})
        persona = payload.get("persona", {})
        modules = persona.get("last_modules") or []
        return "\n".join(
            [
                f"版本 {payload.get('version')} · 模型 {payload.get('model')} · 时区 {payload.get('timezone')}",
                f"对话   短期记忆 {payload.get('conversation', {}).get('short_term_turns', 0)} 轮",
                f"计划   待触发 {plans.get('pending', 0)}（{kinds}）",
                f"主动   自我分享本周 {payload.get('proactive', {}).get('self_share_this_week', 0)} 次",
                f"记忆   {memory.get('documents', 0)} 条 · 已分级 {memory.get('recalled_documents', 0)} 条被想起过 · 平均重要度 {memory.get('average_importance', 0)}",
                f"语料   手写 {corpus.get('handwritten', 0)} · 待审 {corpus.get('pending_candidates', 0)} · 已转正 {corpus.get('learned_active', 0)}",
                f"人设   核心 {persona.get('core_chars', 0)} 字 · {persona.get('modules', 0)} 个模块 · 本轮注入 {persona.get('last_injected_chars', 0)} 字"
                + (f"（{'、'.join(modules)}）" if modules else ""),
            ]
        )

    def corpus_snapshot(self) -> dict:
        learner = getattr(self, "corpus_learner", None)
        return {
            "corpus": self.corpus.stats(),
            "learning": learner.stats(self.now()) if learner is not None else {},
            "last_feedback": getattr(self, "last_corpus_feedback", ""),
        }

    def memory_snapshot(self) -> dict:
        """Lv28: 记忆健康度，供 /memory 与 /api/status 查看。"""
        engine = getattr(self, "reflection", None)
        return {
            "rag": self.rag.stats(),
            "reflection": (
                engine.snapshot(self.now())
                if engine is not None
                else {}
            ),
            "last_reflection_summary": getattr(
                self,
                "last_reflection_summary",
                "",
            ),
        }

    def chat_bundle(
        self,
        user_input: str,
        *,
        received_at: datetime | None = None,
    ) -> ReplyBundle:
        text = user_input.strip()
        if not text:
            return ReplyBundle(
                messages=[],
            )

        now = (
            received_at
            or self.now()
        )
        # “我到咯 / 面完了 / 搞定了”等完成报告会直接结束对应
        # relationship event follow-up，避免事情已经结束后还在凌晨补问。
        plan_manager = getattr(self, "plan_manager", None)
        if plan_manager is not None:
            plan_manager.resolve_relationship_followups(
                text,
                now,
            )
        self.scheduler.note_user_activity(
            now
        )
        self._rollover_if_needed(
            now
        )
        # Lv28: 反思只影响之后怎么想，不会给这一轮加话。
        self.maybe_reflect(now)

        # Lv32: 你继续聊 = 对她上一句的弱正向（只影响语料排序）
        self._maybe_record_implicit_signal(text, now)

        # Lv29: 语料反馈是控制指令（"这句不错"/"别这样说"），
        # 不进 PAE，也不需要 persona 参与措辞。
        feedback_bundle = self._handle_corpus_feedback(
            text,
            now,
        )
        if feedback_bundle is not None:
            self.memory.add_turn(
                text,
                feedback_bundle.joined_text(),
                source="interactive",
                at=now,
                assistant_at=self.now(),
            )
            return feedback_bundle

        decision = self.reply_decider.decide(
            user_input=text,
            recent_messages=(
                self.memory
                .recent_chat_messages(
                    limit=(
                        self.config
                        .reply_gate_context_messages
                    )
                )
            ),
        )
        # Lv27: 正在等用户补充长期任务参数时，"嗯""周六吧""八周" 并不是
        # 对话收尾，而是有效回答。这类消息绝不能被回复判定静默掉。
        commitment_service = getattr(
            self,
            "commitment_service",
            None,
        )
        if (
            not decision.should_reply
            and commitment_service is not None
            and commitment_service.has_pending_clarification(now)
        ):
            decision = ReplyDecision(
                should_reply=True,
                confidence=0.99,
                category="commitment_clarification_pending",
                reason="正在等待用户补齐长期任务参数，短回复可能就是答案。",
                source="commitment_gate_override",
            )
        self.last_reply_decision_json = (
            decision.to_json()
        )
        if not decision.should_reply:
            self.last_plan_json = ""
            self.last_execution_json = ""
            cognition = getattr(
                self,
                "cognition",
                None,
            )
            if cognition is not None:
                cognition.observe_silent_message(
                    text,
                    now,
                )
            self.memory.add_user_message(
                text,
                at=now,
            )
            self._compact_memory_if_needed()
            return ReplyBundle(
                messages=[],
            )

        self.profile.infer_explicit_updates(
            text
        )

        # PAE phase 1:
        # Planner -> ConversationPlan JSON.
        plan_json = (
            self.planner.plan_json(
                text,
                now,
            )
        )
        json.loads(plan_json)
        self.last_plan_json = (
            plan_json
        )

        # PAE phase 2:
        # Executor consumes JSON and
        # returns weighted ReplyBundle.
        bundle, execution_json = (
            self.executor.execute_json(
                plan_json,
                now,
            )
        )
        json.loads(execution_json)
        self.last_execution_json = (
            execution_json
        )

        assistant_at = self.now()
        self.memory.add_turn(
            text,
            bundle.joined_text(),
            source="interactive",
            at=now,
            assistant_at=assistant_at,
        )
        # Lv29: 把这一轮她说的话收进候选池（护栏全过才进，默认还不生效）
        self._learn_from_reply(bundle, now)
        # Lv32: 记住这次交互回复，供下一轮的隐式信号判断
        self.last_interactive_reply = {
            "at": assistant_at,
            "text": bundle.joined_text().strip(),
        }
        try:
            plan_data = json.loads(plan_json)
            cognition_context = (
                plan_data.get("metadata", {})
                .get("cognition_context", {})
            )
            intent_name = str(
                cognition_context.get("intent", {})
                .get("name", "")
            ) if isinstance(cognition_context, dict) else ""
        except (json.JSONDecodeError, AttributeError):
            intent_name = ""
        cognition = getattr(
            self,
            "cognition",
            None,
        )
        if cognition is not None:
            cognition.record_assistant_reply(
                bundle.joined_text(),
                assistant_at,
                intent=(intent_name or None),
            )
        self._compact_memory_if_needed()
        return bundle

    def chat(
        self,
        user_input: str,
    ) -> str:
        """
        兼容旧代码：返回合并文本。

        新项目建议使用 handle_user_message，
        这样多条消息可以真正分开发送。
        """
        return self.chat_bundle(
            user_input
        ).joined_text()

    async def handle_user_message(
        self,
        user_input: str,
        sink: MessageSink,
        *,
        received_at: datetime | None = None,
    ) -> ReplyBundle:
        message_time = (
            received_at
            or self.now()
        )

        # 用户可能正是在报告某个事件已经结束。先消解这类
        # relationship follow-up，再检查到期任务，避免临界点误发。
        plan_manager = getattr(self, "plan_manager", None)
        if plan_manager is not None:
            plan_manager.resolve_relationship_followups(
                user_input.strip(),
                message_time,
            )

        # 必须先登记用户回复，再检查追问。
        # 否则用户恰好在两分钟节点回复时，
        # 银狼会一边收到回复一边问“怎么没回我”。
        self.scheduler.note_user_activity(
            message_time
        )

        # 再补发其他已到期任务。
        # Scheduler 内部有锁，不会与后台循环重复发送。
        await self.scheduler.run_once(
            sink=sink,
            now=message_time,
        )

        # 模型 HTTP 请求是阻塞调用，
        # 放入线程，避免卡住后台 Scheduler。
        bundle = await asyncio.to_thread(
            self.chat_bundle,
            user_input,
            received_at=message_time,
        )
        await self.dispatcher.dispatch(
            bundle,
            sink,
        )
        return bundle

    async def start(
        self,
        sink: MessageSink,
    ) -> None:
        await self.scheduler.start(
            sink
        )

    async def stop(self) -> None:
        await self.scheduler.stop()

    async def run_proactive_once(
        self,
        sink: MessageSink,
        *,
        now: datetime | None = None,
    ) -> ReplyBundle | None:
        # Lv28: 常驻进程也检查一次反思触发（用户睡前可能一整天没聊天）。
        self.maybe_reflect(now)
        return await (
            self.scheduler.run_once(
                sink=sink,
                now=now,
            )
        )

    def identity_snapshot(
        self,
        *,
        at: datetime | None = None,
    ) -> dict:
        current = (
            at
            or self.now()
        )
        return (
            self.agent_identity
            .prompt_view(
                current.date()
            )
        )

    def reply_decision_snapshot(
        self,
    ) -> dict | None:
        if not self.last_reply_decision_json:
            return None
        return json.loads(
            self.last_reply_decision_json
        )

    def plans_snapshot(
        self,
    ) -> list[dict]:
        return [
            plan.to_dict()
            for plan
            in self.plan_manager
            .list_plans()
        ]

    def time_snapshot(
        self,
    ) -> dict:
        return (
            self.time_manager
            .snapshot()
        )

    def commitment_snapshot(
        self,
    ) -> dict:
        """Lv27: 长期承诺 + 澄清会话 + 语料库状态。"""
        return {
            "commitment": self.commitment_service.snapshot(),
            "corpus": self.corpus.stats(),
        }

    def pae_debug(self) -> str:
        return json.dumps(
            {
                "conversation": {
                    "reply_gate": (
                        json.loads(
                            self.last_reply_decision_json
                        )
                        if (
                            self.last_reply_decision_json
                        )
                        else None
                    ),
                    "planner": (
                        json.loads(
                            self.last_plan_json
                        )
                        if (
                            self.last_plan_json
                        )
                        else None
                    ),
                    "executor": (
                        json.loads(
                            self.last_execution_json
                        )
                        if (
                            self.last_execution_json
                        )
                        else None
                    ),
                },
                "cognition": (
                    self.cognition.snapshot()
                ),
                "proactive": {
                    "planner": (
                        json.loads(
                            self.scheduler
                            .last_plan_json
                        )
                        if (
                            self.scheduler
                            .last_plan_json
                        )
                        else None
                    ),
                    "executor": (
                        json.loads(
                            self.scheduler
                            .last_execution_json
                        )
                        if (
                            self.scheduler
                            .last_execution_json
                        )
                        else None
                    ),
                    "last_error": (
                        self.scheduler
                        .last_error
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    def generate_daily_summary(
        self,
        target_date=None,
    ) -> str:
        now = self.now()
        date_value = (
            target_date
            or now.date()
        )

        def summarize(
            source: str,
        ) -> str:
            if self.offline:
                snapshot = (
                    self.memory
                    .snapshot()
                )
                turns = snapshot.get(
                    "recent_turns",
                    [],
                )
                if not turns:
                    return (
                        f"{date_value.isoformat()}："
                        "当天没有可总结的对话。"
                    )

                lines = [
                    (
                        f"{date_value.isoformat()} "
                        "对话摘要："
                    )
                ]
                for turn in turns[-6:]:
                    lines.append(
                        "- 用户："
                        f"{turn.get('user', '')}；"
                        "银狼："
                        f"{turn.get('assistant', '')}"
                    )
                return "\n".join(
                    lines
                )

            return self._complete_text(
                self.prompt_builder
                .daily_summary_prompt(
                    source
                )
            )

        return self.daily.generate(
            target_date=date_value,
            summarizer=summarize,
        )
