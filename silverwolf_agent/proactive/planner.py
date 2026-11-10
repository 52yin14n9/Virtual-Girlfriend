from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .contracts import (
    ProactivePlan,
    RoutineEvent,
    ScheduledPlan,
)
from .message_library import (
    ProactiveMessageLibrary,
)
from .schedule_intent import clean_schedule_title
from .reminder_language import render_due_reminder
from .state import (
    ProactiveStateStore,
)
from ..dialogue.language_policy import infer_semantic_tags
from ..memory.profile import (
    UserProfileManager,
)
from ..cognition import CognitiveStateManager
from ..memory.short_term import (
    ShortTermMemory,
)
from ..world import (
    ContextualCareComposer,
    WeatherService,
    WeatherSnapshot,
    WorldContextManager,
)


class ProactivePlanner:
    """
    主动行为 Planner。

    负责：
    - 选择当前场景的主动文案组；
    - 避免重复使用最近模板；
    - 决定消息权重、顺序和是否期待回复；
    - 生成追问与计划提醒；
    - 输出 ProactivePlan JSON。
    """

    def __init__(
        self,
        profile: UserProfileManager,
        memory: ShortTermMemory,
        message_gap_seconds: float = 0.9,
        *,
        state: (
            ProactiveStateStore
            | None
        ) = None,
        message_library: (
            ProactiveMessageLibrary
            | None
        ) = None,
        template_history_limit: int = 6,
        weather_service: (
            WeatherService
            | None
        ) = None,
        world_context: (
            WorldContextManager
            | None
        ) = None,
        context_composer: (
            ContextualCareComposer
            | None
        ) = None,
        cognition: (
            CognitiveStateManager
            | None
        ) = None,
        commitment_service: object | None = None,
        silence_return_hours: float = 18.0,
        speech: object | None = None,
        speech_enabled: bool = True,
        speech_timeout_seconds: float = 8.0,
        speech_max_chars: int = 80,
        speech_scenes: tuple[str, ...] | list[str] = (
            "morning",
            "noon",
            "evening",
            "callback",
            "follow_up",
            "self_share",
        ),
        speech_max_calls: int = 2,
        speech_samples: int = 3,
        self_share_enabled: bool = True,
        self_share_per_week: int = 2,
        self_share_min_age_days: int = 1,
        self_share_max_age_days: int = 10,
        self_share_setback_days: int = 10,
        self_share_kind_cooldown_days: int = 30,
    ) -> None:
        self.profile = profile
        self.memory = memory
        self.state = state
        self.message_library = (
            message_library
            or ProactiveMessageLibrary()
        )
        self.message_gap_seconds = (
            message_gap_seconds
        )
        self.template_history_limit = max(
            1,
            int(
                template_history_limit
            ),
        )
        self.weather_service = weather_service
        self.world_context = world_context
        self.context_composer = (
            context_composer
            or ContextualCareComposer()
        )
        self.cognition = cognition
        self.commitment_service = commitment_service
        self.silence_return_hours = max(1.0, float(silence_return_hours))
        # Lv31: 主动消息语料化（关系型关心），正式提醒仍走确定性文案
        self.speech = speech
        self.speech_enabled = bool(speech_enabled)
        self.speech_timeout_seconds = max(1.0, float(speech_timeout_seconds))
        self.speech_max_chars = max(20, int(speech_max_chars))
        self.speech_scenes = tuple(
            str(item) for item in speech_scenes if str(item)
        )
        self.speech_max_calls = max(0, int(speech_max_calls))
        self.speech_samples = max(0, int(speech_samples))
        self._speech_calls = 0
        self.last_speech_sources: list[dict[str, str]] = []
        # Lv32: 她自己的事
        self.self_share_enabled = bool(self_share_enabled)
        self.self_share_per_week = max(0, int(self_share_per_week))
        self.self_share_min_age_days = max(0, int(self_share_min_age_days))
        self.self_share_max_age_days = max(1, int(self_share_max_age_days))
        self.self_share_setback_days = max(0, int(self_share_setback_days))
        # Lv33: 同类事件冷却，避免"又是打游戏"
        self.self_share_kind_cooldown_days = max(
            0, int(self_share_kind_cooldown_days)
        )
        self.last_self_share: dict[str, object] = {}

    # Lv32: 不能把角色连续生活说成真实世界事实
    WORLD_CLAIM_PATTERNS = (
        "我出门",
        "我在外面",
        "我在公司",
        "我去公司",
        "我上班",
        "现实里",
        "线下",
        "我亲眼",
    )

    def _maybe_self_share(
        self,
        *,
        now: datetime,
        casual_alias: str = "宝",
    ) -> str:
        """挑一件她自己的事，自然地说一句；没有就返回空串。"""
        self.last_self_share = {}
        if not self.self_share_enabled:
            return ""
        if self.cognition is None or self.state is None:
            return ""
        try:
            if not self.state.self_share_allowed(
                now,
                per_week=self.self_share_per_week,
            ):
                return ""
        except Exception:  # noqa: BLE001
            return ""

        picker = getattr(self.cognition, "pick_shareable_event", None)
        if not callable(picker):
            return ""
        try:
            event = picker(
                now,
                min_age_days=self.self_share_min_age_days,
                max_age_days=self.self_share_max_age_days,
                setback_days=self.self_share_setback_days,
                kind_cooldown_days=self.self_share_kind_cooldown_days,
            )
        except Exception:  # noqa: BLE001
            return ""
        if not isinstance(event, dict):
            return ""

        summary = str(event.get("summary", "")).strip()
        if not summary:
            return ""

        fallback = f"对了，{summary}"
        final, source = self._speak(
            scene_key="self_share",
            corpus_scene="self_share",
            facts={
                "kind": str(event.get("kind", "")),
                "summary": summary,
                "alias": casual_alias,
            },
            fallback=fallback,
            now=now,
        )
        text = final.strip() or fallback
        if any(pattern in text for pattern in self.WORLD_CLAIM_PATTERNS):
            text = fallback
            source = "guard_failed:world_claim"

        marker = getattr(self.cognition, "mark_event_shared", None)
        if callable(marker):
            try:
                marker(str(event.get("event_id", "")), now)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.state.record_self_share(now)
        except Exception:  # noqa: BLE001
            pass
        self.last_self_share = {
            "event_id": str(event.get("event_id", "")),
            "kind": str(event.get("kind", "")),
            "text": text,
            "source": source,
        }
        return text

    # ------------------------------------------------------------------
    # Lv31: 主动消息语料化
    # ------------------------------------------------------------------

    def _speech_allowed(self, scene_key: str) -> bool:
        if self.speech is None or not self.speech_enabled:
            return False
        if self._speech_calls >= self.speech_max_calls:
            return False
        if self.speech_scenes and scene_key not in self.speech_scenes:
            return False
        available = getattr(self.speech, "available", None)
        if callable(available) and not available():
            return False
        return True

    def _speak(
        self,
        *,
        scene_key: str,
        corpus_scene: str,
        facts: dict[str, object],
        fallback: str,
        required_tokens: tuple[str, ...] | list[str] = (),
        tags: tuple[str, ...] | list[str] = (),
        now: datetime,
    ) -> tuple[str, str]:
        """返回 (最终文案, 来源)。不满足条件时原样返回兜底文案。"""
        text = fallback.strip()
        if not self._speech_allowed(scene_key) or not text:
            return text, "template"
        try:
            compose_bounded = getattr(self.speech, "compose_bounded", None)
            if not callable(compose_bounded):
                return text, "template"
            result = compose_bounded(
                timeout_seconds=self.speech_timeout_seconds,
                scene=corpus_scene,
                facts=facts,
                fallback=text,
                required_tokens=tuple(required_tokens),
                relation_mode="companionship",
                tags=tuple(tags),
                at=now,
                max_chars=self.speech_max_chars,
                samples=self.speech_samples or None,
            )
        except Exception:  # noqa: BLE001 - 生成失败一律用兜底
            return text, "error"
        self._speech_calls += 1
        final = str(getattr(result, "text", "") or "").strip() or text
        source = str(getattr(result, "source", "") or "unknown")
        self.last_speech_sources.append(
            {"scene": corpus_scene, "source": source}
        )
        return final, source

    def _silence_hours(self, now: datetime) -> float:
        """距离用户上次说话过了多久（小时）。"""
        if self.state is None:
            return 0.0
        try:
            snapshot = self.state.snapshot()
        except Exception:  # noqa: BLE001
            return 0.0
        raw = snapshot.get("last_user_activity_at")
        if not raw:
            return 0.0
        try:
            last = datetime.fromisoformat(str(raw))
        except ValueError:
            return 0.0
        if last.tzinfo is None and now.tzinfo is not None:
            last = last.replace(tzinfo=now.tzinfo)
        return max(0.0, (now - last).total_seconds() / 3600.0)

    def _open_threads(self) -> list[str]:
        """还没结束的事：优先取活跃长期承诺的标题。"""
        service = self.commitment_service
        if service is None:
            return []
        try:
            return [item.title for item in service.store.active()[:2]]
        except Exception:  # noqa: BLE001
            return []

    def plan_json(
        self,
        *,
        now: datetime,
        routines: list[
            RoutineEvent
        ],
        due_plans: list[
            ScheduledPlan
        ],
        follow_up: (
            dict[str, object]
            | None
        ) = None,
    ) -> str:
        messages: list[
            dict[str, object]
        ] = []
        sequence = 0
        # Lv31: 每轮规划重置语料化调用计数（不发就不调）
        self._speech_calls = 0
        self.last_speech_sources = []
        cognitive_context = (
            self.cognition.prepare_proactive(now)
            if self.cognition is not None
            else {}
        )

        preferred_name = (
            self.profile
            .preferred_name()
        )
        casual_alias = (
            self.profile
            .casual_alias()
        )
        recent_text = (
            self.memory
            .recent_user_text(
                limit=30
            )
        )
        interaction_prefs: dict[str, Any] = {}
        weather_prefs: dict[str, Any] = {}
        # Lv28: 沉默回归。只改变措辞，不改变发送时机。
        silence_hours = self._silence_hours(now)
        silence_return = bool(
            silence_hours >= self.silence_return_hours
        )
        open_threads = self._open_threads() if silence_return else []
        if self.world_context is not None:
            interaction_prefs = (
                self.world_context
                .interaction_preferences(now)
            )
            weather_prefs = (
                self.world_context
                .weather_preferences()
            )

        date_value = now.date().isoformat()
        memory_callback_allowed = bool(
            interaction_prefs.get("memory_callback_enabled", True)
            and not (
                self.state
                and self.state.memory_callback_sent(date_value)
            )
        )
        weekend_suggestion_allowed = bool(
            interaction_prefs.get("weekend_suggestions_enabled", True)
            and now.weekday() >= 5
            and not (
                self.state
                and self.state.weekend_suggestion_sent(date_value)
            )
        )

        weather_result: dict[str, Any] | None = None
        weather_already_sent = bool(
            self.state
            and self.state.weather_sent(
                now.date().isoformat()
            )
        )
        should_check_weather = bool(
            routines
            and self.weather_service is not None
            and weather_prefs.get("enabled", True)
            and not weather_already_sent
            and (
                weather_prefs.get("daily_brief_enabled", True)
                or weather_prefs.get("rain_alerts", True)
                or weather_prefs.get("severe_weather_alerts", True)
                or weather_prefs.get("temperature_change_alerts", True)
            )
        )
        if should_check_weather:
            weather_result = self.weather_service.lookup(
                now=now
            )

        weather_alert_content: str | None = None
        weather_attached = False
        if weather_result and weather_result.get("available"):
            raw_snapshot = weather_result.get("snapshot")
            if isinstance(raw_snapshot, dict):
                snapshot_value = WeatherSnapshot.from_dict(raw_snapshot)
                alert_allowed = bool(
                    (
                        snapshot_value.severe
                        and weather_prefs.get("severe_weather_alerts", True)
                    )
                    or (
                        snapshot_value.rain_likely
                        and weather_prefs.get("rain_alerts", True)
                    )
                )
                if alert_allowed:
                    weather_alert_content = self.context_composer.weather_alert(
                        snapshot=snapshot_value
                    )
                elif (
                    weather_result.get("temperature_change_significant")
                    and weather_prefs.get("temperature_change_alerts", True)
                ):
                    change = float(weather_result.get("temperature_change_c", 0.0))
                    direction = "升温" if change > 0 else "降温"
                    weather_alert_content = (
                        f"{snapshot_value.location}今天会明显{direction}，"
                        f"体感大概差{abs(change):g}℃。出门前把衣服调整一下。"
                    )

        for event in routines:
            if not self._allow_routine(
                event.key,
                now=now,
                interaction_prefs=interaction_prefs,
            ):
                continue
            choice = (
                self.message_library
                .select_routine(
                    key=event.key,
                    now=now,
                    preferred_name=(
                        preferred_name
                    ),
                    casual_alias=(
                        casual_alias
                    ),
                    recent_text=recent_text,
                    recent_template_ids=(
                        self._recent_template_ids(
                            group_prefix=(
                                event.key
                            )
                        )
                    ),
                    recent_semantic_tags=(
                        self._recent_semantic_tags(
                            group_prefix=(
                                event.key
                            )
                        )
                    ),
                )
            )
            if choice is None:
                continue

            contextual_weather = None
            if weather_result and weather_result.get("available") and not weather_attached:
                include_daily_brief = bool(
                    event.key == "morning"
                    and weather_prefs.get("daily_brief_enabled", True)
                    and weather_prefs.get("mention_in_morning_message", True)
                )
                if include_daily_brief or weather_alert_content:
                    contextual_weather = weather_result
                    weather_attached = True


            composed_content, context_metadata = (
                self.context_composer.compose(
                    base=choice.content,
                    routine_key=event.key,
                    now=now,
                    recent_user_text=recent_text,
                    weather_result=contextual_weather,
                    memory_callback_enabled=memory_callback_allowed,
                    weekend_suggestions_enabled=weekend_suggestion_allowed,
                    silence_return=silence_return,
                    open_threads=open_threads,
                )
            )

            # Lv31: 关系型关心改由语料 + 模型重写，事实与兜底仍然确定性
            required: list[str] = []
            weather_location = str(
                context_metadata.get("weather_location", "") or ""
            )
            if weather_location:
                required.append(weather_location)
            final_content, speech_source = self._speak(
                scene_key=event.key,
                corpus_scene=f"proactive_{event.key}",
                facts={
                    "routine": event.key,
                    "alias": casual_alias,
                    "weather_location": weather_location,
                    "has_memory_callback": bool(
                        context_metadata.get("memory_callback")
                    ),
                    "silence_return": bool(silence_return),
                },
                fallback=composed_content,
                required_tokens=tuple(required),
                tags=choice.semantic_tags,
                now=now,
            )

            # Lv32: 偶尔顺口讲讲她自己的事（并入同一条消息，不新增条数）
            self_share_text = self._maybe_self_share(
                now=now,
                casual_alias=casual_alias or "宝",
            )
            if self_share_text:
                final_content = f"{final_content} {self_share_text}".strip()[:420]

            messages.append(
                {
                    "content": (
                        final_content
                    ),
                    "weight": (
                        event.weight
                    ),
                    "category": (
                        f"routine_{event.key}"
                    ),
                    "source": "proactive",
                    "sequence": sequence,
                    "delay_seconds": (
                        self.message_gap_seconds
                    ),
                    "goal_kinds": [
                        "relationship_care"
                    ],
                    "metadata": {
                        "routine_key": (
                            event.key
                        ),
                        "expects_reply": (
                            choice.expects_reply
                        ),
                        # A question may invite a reply without creating an
                        # obligation to answer. Secondary follow-up timing is
                        # a scheduler/user preference, not a template fact.
                        "secondary_follow_up": "configured_optional",
                        "semantic_tags": list(choice.semantic_tags),
                        "template_id": (
                            choice.template_id
                        ),
                        "template_group": (
                            choice.template_group
                        ),
                        "selection_mode": (
                            "corpus_speech"
                            if speech_source == "corpus_llm"
                            else "contextual_template_pool"
                        ),
                        "speech_source": speech_source,
                        # Lv32: 这条消息里是否包含她自己的事
                        "self_share": bool(self_share_text),
                        "self_share_kind": (
                            str(self.last_self_share.get("kind", ""))
                            if self_share_text
                            else ""
                        ),
                        **context_metadata,
                    },
                }
            )
            sequence += 1

        if weather_alert_content and not weather_attached:
            messages.append(
                {
                    "content": weather_alert_content,
                    "weight": 98,
                    "category": "weather_alert",
                    "source": "proactive",
                    "sequence": sequence,
                    "delay_seconds": self.message_gap_seconds,
                    "goal_kinds": ["weather_safety_alert"],
                    "metadata": {
                        "expects_reply": False,
                        "weather_context_included": True,
                        "weather_alert_only": True,
                        "selection_mode": "weather_alert",
                    },
                }
            )
            sequence += 1

        if follow_up is not None:
            routine_key = str(
                follow_up.get(
                    "routine_key",
                    "",
                )
            )
            choice = (
                self.message_library
                .select_follow_up(
                    routine_key=(
                        routine_key
                    ),
                    now=now,
                    preferred_name=(
                        preferred_name
                    ),
                    casual_alias=(
                        casual_alias
                    ),
                    original_content=str(
                        follow_up.get(
                            "original_content",
                            "",
                        )
                    ),
                    recent_template_ids=(
                        self._recent_template_ids(
                            group_prefix=(
                                "follow_up_"
                                + routine_key
                            )
                        )
                    ),
                    recent_semantic_tags=(
                        self._recent_semantic_tags(
                            group_prefix=(
                                "follow_up_"
                                + routine_key
                            )
                        )
                    ),
                )
            )
            messages.append(
                {
                    "content": (
                        choice.content
                    ),
                    "weight": 78,
                    "category": (
                        "relationship_follow_up"
                    ),
                    "source": "proactive",
                    "sequence": sequence,
                    "delay_seconds": (
                        self.message_gap_seconds
                    ),
                    "goal_kinds": [
                        "relationship_follow_up"
                    ],
                    "metadata": {
                        "expects_reply": False,
                        "is_follow_up": True,
                        "routine_key": (
                            routine_key
                        ),
                        "original_message_id": str(
                            follow_up.get(
                                "original_message_id",
                                "",
                            )
                        ),
                        "semantic_tags": list(choice.semantic_tags),
                        "template_id": (
                            choice.template_id
                        ),
                        "template_group": (
                            choice.template_group
                        ),
                        "selection_mode": (
                            "contextual_template_pool"
                        ),
                    },
                }
            )
            sequence += 1

        for scheduled_plan in sorted(
            due_plans,
            key=lambda item: (
                -item.importance,
                item.due_at,
            ),
        )[:3]:
            messages.append(
                {
                    "content": (
                        self._render_due_content(
                            plan=(
                                scheduled_plan
                            ),
                            now=now,
                            casual_alias=(casual_alias or "宝"),
                        )
                    ),
                    "weight": max(
                        80,
                        scheduled_plan
                        .importance,
                    ),
                    "category": (
                        "relationship_event_follow_up"
                        if scheduled_plan.metadata.get("kind")
                        == "relationship_event_follow_up"
                        else "scheduled_reminder"
                    ),
                    "source": "proactive",
                    "sequence": sequence,
                    "delay_seconds": (
                        self.message_gap_seconds
                    ),
                    "goal_kinds": [
                        (
                            "relationship_event_follow_up"
                            if scheduled_plan.metadata.get("kind")
                            == "relationship_event_follow_up"
                            else "scheduled_reminder"
                        )
                    ],
                    "metadata": {
                        "plan_id": (
                            scheduled_plan
                            .plan_id
                        ),
                        "title": (
                            scheduled_plan
                            .title
                        ),
                        "expects_reply": bool(
                            scheduled_plan.metadata.get(
                                "expects_reply",
                                False,
                            )
                        ),
                        "no_secondary_follow_up": bool(
                            scheduled_plan.metadata.get(
                                "no_secondary_follow_up",
                                False,
                            )
                        ),
                        "event_label": str(
                            scheduled_plan.metadata.get(
                                "event_label",
                                "",
                            )
                        ),
                        "selection_mode": (
                            "relationship_event_follow_up"
                            if scheduled_plan.metadata.get("kind")
                            == "relationship_event_follow_up"
                            else "scheduled_plan_renderer"
                        ),
                    },
                }
            )
            sequence += 1

        plan = ProactivePlan.create(
            planned_messages=messages,
            routine_keys=[
                event.key
                for event in routines
            ],
            scheduled_plan_ids=[
                scheduled_plan.plan_id
                for scheduled_plan
                in due_plans
            ],
            metadata={
                "planned_at": (
                    now.isoformat(
                        timespec="seconds"
                    )
                ),
                "minimum_weight": 50,
                "maximum_messages": 3,
                "contains_follow_up": (
                    follow_up is not None
                ),
                "template_history_limit": (
                    self.template_history_limit
                ),
                "recent_context_turns": 30,
                "cognition_context": cognitive_context,
            },
        )
        return plan.to_json()

    def _allow_routine(
        self,
        routine_key: str,
        *,
        now: datetime,
        interaction_prefs: dict[str, Any],
    ) -> bool:
        quiet_until = interaction_prefs.get("quiet_until")
        if quiet_until:
            try:
                quiet = datetime.fromisoformat(str(quiet_until))
                if quiet.tzinfo is None:
                    quiet = quiet.replace(tzinfo=now.tzinfo)
                if now < quiet:
                    return False
            except ValueError:
                pass

        mode = str(
            interaction_prefs.get(
                "proactive_frequency_mode",
                "normal",
            )
        )
        if mode == "low" and routine_key == "noon":
            return False
        if mode == "high":
            return True

        if (
            interaction_prefs.get(
                "adaptive_proactive_frequency",
                True,
            )
            and self.state is not None
        ):
            engagement = (
                self.state.snapshot()
                .get("engagement", {})
            )
            unanswered = int(
                engagement.get(
                    "consecutive_unanswered",
                    0,
                )
                or 0
            )
            if unanswered >= 4:
                return routine_key == "evening"
            if unanswered >= 2 and routine_key == "noon":
                return False
        return True

    def _recent_template_ids(
        self,
        *,
        group_prefix: str,
    ) -> list[str]:
        if self.state is None:
            return []

        snapshot = (
            self.state.snapshot()
        )
        history = snapshot.get(
            "proactive_template_history",
            [],
        )
        values: list[str] = []

        for item in reversed(
            history
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue
            group = str(
                item.get(
                    "template_group",
                    "",
                )
            )
            if not (
                group == group_prefix
                or group.startswith(
                    group_prefix + "_"
                )
            ):
                continue

            template_id = str(
                item.get(
                    "template_id",
                    "",
                )
            )
            if (
                template_id
                and template_id
                not in values
            ):
                values.append(
                    template_id
                )
            if len(values) >= (
                self.template_history_limit
            ):
                break

        return values

    def _recent_semantic_tags(
        self,
        *,
        group_prefix: str,
        message_limit: int = 2,
    ) -> list[str]:
        if self.state is None:
            return []

        snapshot = self.state.snapshot()
        history = snapshot.get(
            "proactive_template_history",
            [],
        )
        values: list[str] = []
        matched_messages = 0
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            group = str(item.get("template_group", ""))
            if not (
                group == group_prefix
                or group.startswith(group_prefix + "_")
            ):
                continue
            raw_tags = item.get("semantic_tags", [])
            if isinstance(raw_tags, list):
                tags = [str(tag) for tag in raw_tags if str(tag)]
            else:
                tags = []
            if not tags:
                tags = list(
                    infer_semantic_tags(
                        str(item.get("content", ""))
                    )
                )
            for tag in tags:
                if tag not in values:
                    values.append(tag)
            matched_messages += 1
            if matched_messages >= max(1, int(message_limit)):
                break
        return values

    def _render_due_content(
        self,
        *,
        plan: ScheduledPlan,
        now: datetime,
        casual_alias: str = "宝",
    ) -> str:
        """Lv27: 长期承诺的到期播报需要带周次，其余仍走原提醒语言层。"""
        if (
            plan.metadata.get("kind") == "commitment_occurrence"
            and self.commitment_service is not None
        ):
            try:
                return self.commitment_service.plan_wording(
                    plan.metadata,
                    title=plan.title,
                    alias=casual_alias,
                )
            except Exception:  # noqa: BLE001 - 兜底到通用提醒
                pass

        base_content = self._plan_content(
            plan=plan,
            now=now,
            casual_alias=casual_alias,
        )
        # Lv31: 只有"关系型回访"走语料化；正式提醒（吃药/睡觉/日程）保持确定性
        if plan.metadata.get("kind") == "relationship_event_follow_up":
            event_label = str(
                plan.metadata.get("event_label", "") or ""
            )
            final, _source = self._speak(
                scene_key="follow_up",
                corpus_scene="care",
                facts={
                    "event": event_label,
                    "alias": casual_alias,
                },
                fallback=base_content,
                required_tokens=(event_label,) if event_label else (),
                now=now,
            )
            return final
        return base_content

    @staticmethod
    def _plan_content(
        *,
        plan: ScheduledPlan,
        now: datetime,
        casual_alias: str = "宝",
    ) -> str:
        due = datetime.fromisoformat(
            plan.due_at
        )
        if due.tzinfo is None:
            due = due.replace(
                tzinfo=now.tzinfo
            )
        due = due.astimezone(
            now.tzinfo
        )

        if (
            plan.metadata.get("kind")
            == "relationship_event_follow_up"
        ):
            label = str(
                plan.metadata.get(
                    "event_label",
                    "那件事",
                )
            )
            return (
                f"{label}应该差不多结束了吧。"
                "感觉怎么样？"
            )

        # 正式提醒使用独立的自然语言渲染层。不要把内部 title 直接拼进
        # “提醒你一下 / 今天要…… / 我记着呢”这类系统通知模板。
        return render_due_reminder(
            title=plan.title,
            casual_alias=casual_alias,
        )
