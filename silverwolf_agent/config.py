from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from zoneinfo import (
    ZoneInfo,
    ZoneInfoNotFoundError,
)

from .paths import PROJECT_ROOT


def _load_dotenv_fallback(
    path: Path,
) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = (
            value.strip()
            .strip('"')
            .strip("'")
        )
        if key and key not in os.environ:
            os.environ[key] = value


def _env_bool(
    name: str,
    default: bool,
) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(
            env_path,
            override=True,
        )
    except ImportError:
        _load_dotenv_fallback(
            env_path
        )


@dataclass(frozen=True)
class AppConfig:
    api_key: str | None
    base_url: str
    model: str
    timezone: str
    max_tokens: int
    temperature: float
    max_retries: int
    retry_base_seconds: float
    scheduler_poll_seconds: float
    message_gap_seconds: float
    planner_llm_enabled: bool = True
    planner_min_confidence: float = 0.72
    planner_max_tokens: int = 700
    planner_temperature: float = 0.1
    proactive_follow_up_enabled: bool = False
    proactive_follow_up_seconds: int = 900
    proactive_follow_up_expiry_seconds: int = 3600
    proactive_template_history_limit: int = 6
    weather_cache_minutes: int = 30
    weather_http_timeout_seconds: float = 10.0
    reply_gate_enabled: bool = True
    reply_gate_llm_enabled: bool = True
    reply_gate_min_silence_confidence: float = 0.78
    reply_gate_max_tokens: int = 220
    reply_gate_temperature: float = 0.0
    reply_gate_context_messages: int = 8
    reply_gate_model: str | None = None
    completion_agent_enabled: bool = True
    completion_llm_enabled: bool = True
    completion_max_rounds: int = 2
    completion_min_incomplete_confidence: float = 0.72
    completion_max_chars: int = 12000
    # Lv27: 长期任务承诺（澄清问答 + 周期提醒）
    commitment_enabled: bool = True
    commitment_clarify_max_questions: int = 2
    commitment_clarify_expiry_hours: int = 24
    commitment_default_clock: str = "10:00"
    commitment_max_weeks: int = 52
    commitment_soft_weekend: bool = True
    # Lv27: 语料库驱动生成
    corpus_enabled: bool = True
    corpus_samples: int = 3
    corpus_chat_samples: int = 2
    corpus_max_overlap: float = 0.35
    corpus_cooldown: int = 8
    corpus_temperature: float = 0.85
    # Lv28: 记忆加权与遗忘曲线
    memory_decay_enabled: bool = True
    memory_weight_relevance: float = 0.55
    memory_weight_importance: float = 0.25
    memory_weight_recency: float = 0.20
    memory_stability_base_days: float = 14.0
    rag_importance_llm_enabled: bool = False
    # Lv28: 每周反思
    reflection_enabled: bool = True
    reflection_weekday: int = 6
    reflection_hour: int = 21
    reflection_importance_threshold: int = 150
    reflection_max_evidence: int = 12
    # Lv28: 沉默后的续接式回归
    silence_return_hours: float = 18.0
    # Lv29: 语料自我生长
    corpus_learning_enabled: bool = True
    corpus_learn_from_user: bool = False
    corpus_phrase_mode: bool = False
    corpus_candidate_min_chars: int = 5
    corpus_candidate_max_chars: int = 30
    corpus_learned_share: float = 0.3
    corpus_retire_days: int = 90
    corpus_scene_limit: int = 120
    corpus_privacy_filter: bool = True
    # Lv30: persona 分层与世界书
    persona_layers_enabled: bool = True
    persona_core_max_chars: int = 4000
    persona_budget_chars: int = 8000
    # Lv30: 概率化主动时机（仅关系型关心）
    proactive_jitter_enabled: bool = True
    proactive_jitter_minutes: int = 10
    proactive_pinned_days: int = 7
    # Lv31: 主动消息语料化
    proactive_speech_enabled: bool = True
    proactive_speech_timeout_seconds: float = 8.0
    proactive_speech_max_chars: int = 80
    proactive_speech_scenes: str = "morning,noon,evening,callback,follow_up,self_share"
    proactive_speech_samples: int = 3
    # Lv32: 她自己的事（自我分享）
    self_share_enabled: bool = True
    self_share_per_week: int = 2
    self_share_min_age_days: int = 1
    self_share_max_age_days: int = 10
    self_share_setback_days: int = 10
    # Lv32: 语料隐式正向信号
    corpus_implicit_signal_enabled: bool = True
    corpus_implicit_window_minutes: int = 10
    # Lv33: 体检与生活事件冷却
    doctor_stale_days: int = 3
    self_share_kind_cooldown_days: int = 30

    @classmethod
    def from_env(
        cls,
    ) -> "AppConfig":
        load_project_env()
        return cls(
            api_key=(
                os.getenv(
                    "ANTHROPIC_API_KEY"
                )
                or None
            ),
            base_url=os.getenv(
                "ANTHROPIC_BASE_URL",
                "https://api.anthropic.com",
            ),
            model=os.getenv(
                "SILVERWOLF_MODEL",
                "deepseek-v4-flash",
            ),
            timezone=os.getenv(
                "SILVERWOLF_TIMEZONE",
                "Asia/Shanghai",
            ),
            max_tokens=int(
                os.getenv(
                    "SILVERWOLF_MAX_TOKENS",
                    "1000",
                )
            ),
            temperature=float(
                os.getenv(
                    "SILVERWOLF_TEMPERATURE",
                    "0.8",
                )
            ),
            max_retries=int(
                os.getenv(
                    "SILVERWOLF_MAX_RETRIES",
                    "3",
                )
            ),
            retry_base_seconds=float(
                os.getenv(
                    "SILVERWOLF_RETRY_BASE_SECONDS",
                    "1.5",
                )
            ),
            scheduler_poll_seconds=float(
                os.getenv(
                    "SILVERWOLF_SCHEDULER_POLL_SECONDS",
                    "5",
                )
            ),
            message_gap_seconds=float(
                os.getenv(
                    "SILVERWOLF_MESSAGE_GAP_SECONDS",
                    "0.9",
                )
            ),
            planner_llm_enabled=_env_bool(
                "SILVERWOLF_PLANNER_LLM_ENABLED",
                True,
            ),
            planner_min_confidence=float(
                os.getenv(
                    "SILVERWOLF_PLANNER_MIN_CONFIDENCE",
                    "0.72",
                )
            ),
            planner_max_tokens=int(
                os.getenv(
                    "SILVERWOLF_PLANNER_MAX_TOKENS",
                    "700",
                )
            ),
            planner_temperature=float(
                os.getenv(
                    "SILVERWOLF_PLANNER_TEMPERATURE",
                    "0.1",
                )
            ),
            proactive_follow_up_enabled=_env_bool(
                "SILVERWOLF_PROACTIVE_FOLLOW_UP_ENABLED",
                False,
            ),
            proactive_follow_up_seconds=max(
                10,
                int(
                    os.getenv(
                        "SILVERWOLF_PROACTIVE_FOLLOW_UP_SECONDS",
                        "900",
                    )
                ),
            ),
            proactive_follow_up_expiry_seconds=max(
                60,
                int(
                    os.getenv(
                        "SILVERWOLF_PROACTIVE_FOLLOW_UP_EXPIRY_SECONDS",
                        "3600",
                    )
                ),
            ),
            proactive_template_history_limit=max(
                1,
                int(
                    os.getenv(
                        "SILVERWOLF_PROACTIVE_TEMPLATE_HISTORY_LIMIT",
                        "6",
                    )
                ),
            ),
            weather_cache_minutes=max(
                5,
                int(os.getenv("SILVERWOLF_WEATHER_CACHE_MINUTES", "30")),
            ),
            weather_http_timeout_seconds=max(
                2.0,
                float(os.getenv("SILVERWOLF_WEATHER_HTTP_TIMEOUT_SECONDS", "10")),
            ),
            reply_gate_enabled=_env_bool(
                "SILVERWOLF_REPLY_GATE_ENABLED",
                True,
            ),
            reply_gate_llm_enabled=_env_bool(
                "SILVERWOLF_REPLY_GATE_LLM_ENABLED",
                True,
            ),
            reply_gate_min_silence_confidence=max(
                0.0,
                min(
                    1.0,
                    float(
                        os.getenv(
                            "SILVERWOLF_REPLY_GATE_MIN_SILENCE_CONFIDENCE",
                            "0.78",
                        )
                    ),
                ),
            ),
            reply_gate_max_tokens=max(
                80,
                int(os.getenv("SILVERWOLF_REPLY_GATE_MAX_TOKENS", "220")),
            ),
            reply_gate_temperature=max(
                0.0,
                min(
                    1.0,
                    float(os.getenv("SILVERWOLF_REPLY_GATE_TEMPERATURE", "0.0")),
                ),
            ),
            reply_gate_context_messages=max(
                2,
                int(os.getenv("SILVERWOLF_REPLY_GATE_CONTEXT_MESSAGES", "8")),
            ),
            reply_gate_model=(
                os.getenv("SILVERWOLF_REPLY_GATE_MODEL")
                or None
            ),
            completion_agent_enabled=_env_bool(
                "SILVERWOLF_COMPLETION_AGENT_ENABLED",
                True,
            ),
            completion_llm_enabled=_env_bool(
                "SILVERWOLF_COMPLETION_LLM_ENABLED",
                True,
            ),
            completion_max_rounds=max(
                0,
                min(
                    4,
                    int(os.getenv("SILVERWOLF_COMPLETION_MAX_ROUNDS", "2")),
                ),
            ),
            completion_min_incomplete_confidence=max(
                0.0,
                min(
                    1.0,
                    float(os.getenv("SILVERWOLF_COMPLETION_MIN_INCOMPLETE_CONFIDENCE", "0.72")),
                ),
            ),
            completion_max_chars=max(
                1000,
                int(os.getenv("SILVERWOLF_COMPLETION_MAX_CHARS", "12000")),
            ),
            commitment_enabled=_env_bool(
                "SILVERWOLF_COMMITMENT_ENABLED",
                True,
            ),
            commitment_clarify_max_questions=max(
                1,
                min(
                    3,
                    int(
                        os.getenv(
                            "SILVERWOLF_COMMITMENT_CLARIFY_MAX_QUESTIONS",
                            "2",
                        )
                    ),
                ),
            ),
            commitment_clarify_expiry_hours=max(
                1,
                int(
                    os.getenv(
                        "SILVERWOLF_COMMITMENT_CLARIFY_EXPIRY_HOURS",
                        "24",
                    )
                ),
            ),
            commitment_default_clock=(
                os.getenv(
                    "SILVERWOLF_COMMITMENT_DEFAULT_CLOCK",
                    "10:00",
                ).strip()
                or "10:00"
            ),
            commitment_max_weeks=max(
                1,
                min(
                    104,
                    int(
                        os.getenv(
                            "SILVERWOLF_COMMITMENT_MAX_WEEKS",
                            "52",
                        )
                    ),
                ),
            ),
            commitment_soft_weekend=_env_bool(
                "SILVERWOLF_COMMITMENT_SOFT_WEEKEND",
                True,
            ),
            corpus_enabled=_env_bool(
                "SILVERWOLF_CORPUS_ENABLED",
                True,
            ),
            corpus_samples=max(
                0,
                min(
                    8,
                    int(os.getenv("SILVERWOLF_CORPUS_SAMPLES", "3")),
                ),
            ),
            corpus_chat_samples=max(
                0,
                min(
                    6,
                    int(os.getenv("SILVERWOLF_CORPUS_CHAT_SAMPLES", "2")),
                ),
            ),
            corpus_max_overlap=max(
                0.05,
                min(
                    0.9,
                    float(
                        os.getenv(
                            "SILVERWOLF_CORPUS_MAX_OVERLAP",
                            "0.35",
                        )
                    ),
                ),
            ),
            corpus_cooldown=max(
                1,
                int(os.getenv("SILVERWOLF_CORPUS_COOLDOWN", "8")),
            ),
            corpus_temperature=max(
                0.0,
                min(
                    1.2,
                    float(
                        os.getenv(
                            "SILVERWOLF_CORPUS_TEMPERATURE",
                            "0.85",
                        )
                    ),
                ),
            ),
            memory_decay_enabled=_env_bool(
                "SILVERWOLF_MEMORY_DECAY_ENABLED",
                True,
            ),
            memory_weight_relevance=max(
                0.0,
                float(
                    os.getenv(
                        "SILVERWOLF_MEMORY_WEIGHT_RELEVANCE",
                        "0.55",
                    )
                ),
            ),
            memory_weight_importance=max(
                0.0,
                float(
                    os.getenv(
                        "SILVERWOLF_MEMORY_WEIGHT_IMPORTANCE",
                        "0.25",
                    )
                ),
            ),
            memory_weight_recency=max(
                0.0,
                float(
                    os.getenv(
                        "SILVERWOLF_MEMORY_WEIGHT_RECENCY",
                        "0.20",
                    )
                ),
            ),
            memory_stability_base_days=max(
                1.0,
                float(
                    os.getenv(
                        "SILVERWOLF_MEMORY_STABILITY_BASE_DAYS",
                        "14",
                    )
                ),
            ),
            rag_importance_llm_enabled=_env_bool(
                "SILVERWOLF_RAG_IMPORTANCE_LLM_ENABLED",
                False,
            ),
            reflection_enabled=_env_bool(
                "SILVERWOLF_REFLECTION_ENABLED",
                True,
            ),
            reflection_weekday=max(
                0,
                min(
                    6,
                    int(
                        os.getenv(
                            "SILVERWOLF_REFLECTION_WEEKDAY",
                            "6",
                        )
                    ),
                ),
            ),
            reflection_hour=max(
                0,
                min(
                    23,
                    int(
                        os.getenv(
                            "SILVERWOLF_REFLECTION_HOUR",
                            "21",
                        )
                    ),
                ),
            ),
            reflection_importance_threshold=max(
                20,
                int(
                    os.getenv(
                        "SILVERWOLF_REFLECTION_IMPORTANCE_THRESHOLD",
                        "150",
                    )
                ),
            ),
            reflection_max_evidence=max(
                3,
                min(
                    30,
                    int(
                        os.getenv(
                            "SILVERWOLF_REFLECTION_MAX_EVIDENCE",
                            "12",
                        )
                    ),
                ),
            ),
            silence_return_hours=max(
                1.0,
                float(
                    os.getenv(
                        "SILVERWOLF_SILENCE_RETURN_HOURS",
                        "18",
                    )
                ),
            ),
            corpus_learning_enabled=_env_bool(
                "SILVERWOLF_CORPUS_LEARNING_ENABLED",
                True,
            ),
            corpus_learn_from_user=_env_bool(
                "SILVERWOLF_CORPUS_LEARN_FROM_USER",
                False,
            ),
            corpus_phrase_mode=_env_bool(
                "SILVERWOLF_CORPUS_PHRASE_MODE",
                False,
            ),
            corpus_candidate_min_chars=max(
                2,
                int(
                    os.getenv(
                        "SILVERWOLF_CORPUS_CANDIDATE_MIN_CHARS",
                        "5",
                    )
                ),
            ),
            corpus_candidate_max_chars=max(
                8,
                int(
                    os.getenv(
                        "SILVERWOLF_CORPUS_CANDIDATE_MAX_CHARS",
                        "30",
                    )
                ),
            ),
            corpus_learned_share=max(
                0.0,
                min(
                    0.9,
                    float(
                        os.getenv(
                            "SILVERWOLF_CORPUS_LEARNED_SHARE",
                            "0.3",
                        )
                    ),
                ),
            ),
            corpus_retire_days=max(
                7,
                int(
                    os.getenv(
                        "SILVERWOLF_CORPUS_RETIRE_DAYS",
                        "90",
                    )
                ),
            ),
            corpus_scene_limit=max(
                10,
                int(
                    os.getenv(
                        "SILVERWOLF_CORPUS_SCENE_LIMIT",
                        "120",
                    )
                ),
            ),
            corpus_privacy_filter=_env_bool(
                "SILVERWOLF_CORPUS_PRIVACY_FILTER",
                True,
            ),
            persona_layers_enabled=_env_bool(
                "SILVERWOLF_PERSONA_LAYERS_ENABLED",
                True,
            ),
            persona_core_max_chars=max(
                500,
                int(
                    os.getenv(
                        "SILVERWOLF_PERSONA_CORE_MAX_CHARS",
                        "4000",
                    )
                ),
            ),
            persona_budget_chars=max(
                1000,
                int(
                    os.getenv(
                        "SILVERWOLF_PERSONA_BUDGET_CHARS",
                        "8000",
                    )
                ),
            ),
            proactive_jitter_enabled=_env_bool(
                "SILVERWOLF_PROACTIVE_JITTER_ENABLED",
                True,
            ),
            proactive_jitter_minutes=max(
                0,
                min(
                    120,
                    int(
                        os.getenv(
                            "SILVERWOLF_PROACTIVE_JITTER_MINUTES",
                            "10",
                        )
                    ),
                ),
            ),
            proactive_pinned_days=max(
                0,
                int(
                    os.getenv(
                        "SILVERWOLF_PROACTIVE_PINNED_DAYS",
                        "7",
                    )
                ),
            ),
            proactive_speech_enabled=_env_bool(
                "SILVERWOLF_PROACTIVE_SPEECH_ENABLED",
                True,
            ),
            proactive_speech_timeout_seconds=max(
                1.0,
                min(
                    60.0,
                    float(
                        os.getenv(
                            "SILVERWOLF_PROACTIVE_SPEECH_TIMEOUT_SECONDS",
                            "8",
                        )
                    ),
                ),
            ),
            proactive_speech_max_chars=max(
                20,
                min(
                    300,
                    int(
                        os.getenv(
                            "SILVERWOLF_PROACTIVE_SPEECH_MAX_CHARS",
                            "80",
                        )
                    ),
                ),
            ),
            proactive_speech_scenes=(
                os.getenv(
                    "SILVERWOLF_PROACTIVE_SPEECH_SCENES",
                    "morning,noon,evening,callback,follow_up",
                ).strip()
                or "morning,noon,evening,callback,follow_up"
            ),
            proactive_speech_samples=max(
                0,
                min(
                    8,
                    int(
                        os.getenv(
                            "SILVERWOLF_PROACTIVE_SPEECH_SAMPLES",
                            "3",
                        )
                    ),
                ),
            ),
            self_share_enabled=_env_bool(
                "SILVERWOLF_SELF_SHARE_ENABLED",
                True,
            ),
            self_share_per_week=max(
                0,
                min(
                    7,
                    int(
                        os.getenv(
                            "SILVERWOLF_SELF_SHARE_PER_WEEK",
                            "2",
                        )
                    ),
                ),
            ),
            self_share_min_age_days=max(
                0,
                int(
                    os.getenv(
                        "SILVERWOLF_SELF_SHARE_MIN_AGE_DAYS",
                        "1",
                    )
                ),
            ),
            self_share_max_age_days=max(
                1,
                int(
                    os.getenv(
                        "SILVERWOLF_SELF_SHARE_MAX_AGE_DAYS",
                        "10",
                    )
                ),
            ),
            self_share_setback_days=max(
                0,
                int(
                    os.getenv(
                        "SILVERWOLF_SELF_SHARE_SETBACK_DAYS",
                        "10",
                    )
                ),
            ),
            corpus_implicit_signal_enabled=_env_bool(
                "SILVERWOLF_CORPUS_IMPLICIT_SIGNAL_ENABLED",
                True,
            ),
            corpus_implicit_window_minutes=max(
                1,
                min(
                    120,
                    int(
                        os.getenv(
                            "SILVERWOLF_CORPUS_IMPLICIT_WINDOW_MINUTES",
                            "10",
                        )
                    ),
                ),
            ),
            doctor_stale_days=max(
                1,
                int(os.getenv("SILVERWOLF_DOCTOR_STALE_DAYS", "3")),
            ),
            self_share_kind_cooldown_days=max(
                0,
                int(
                    os.getenv(
                        "SILVERWOLF_SELF_SHARE_KIND_COOLDOWN_DAYS",
                        "30",
                    )
                ),
            ),
        )

    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(
                self.timezone
            )
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
