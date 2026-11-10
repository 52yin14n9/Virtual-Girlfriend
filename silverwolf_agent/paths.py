from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

PERSONA_PATH = (
    CONFIG_DIR
    / "persona"
    / "silverwolf_lv33.md"
)
# Lv27: 语料库目录与语料使用记录
CORPUS_DIR = CONFIG_DIR / "corpus"
# Lv30: persona 世界书模块目录
PERSONA_MODULES_DIR = (
    CONFIG_DIR / "persona" / "modules"
)
DEFAULT_PROFILE_PATH = (
    CONFIG_DIR
    / "default_user_profile.json"
)
DEFAULT_AGENT_PROFILE_PATH = (
    CONFIG_DIR
    / "default_agent_profile.json"
)

MEMORY_DIR = DATA_DIR / "memory"
RAG_DIR = DATA_DIR / "rag"
SUMMARY_DIR = DATA_DIR / "summaries"
PROFILE_DIR = DATA_DIR / "profile"
SCHEDULER_DIR = DATA_DIR / "scheduler"
WEATHER_DIR = DATA_DIR / "weather"
COGNITION_DIR = DATA_DIR / "cognition"
CORPUS_STATE_DIR = DATA_DIR / "corpus"

SHORT_MEMORY_PATH = (
    MEMORY_DIR / "short_term.json"
)
RAG_PATH = RAG_DIR / "documents.jsonl"
DAILY_STATE_PATH = (
    SUMMARY_DIR / "daily_state.json"
)
USER_PROFILE_PATH = (
    PROFILE_DIR / "user_profile.json"
)

TIME_PREFERENCES_PATH = (
    SCHEDULER_DIR
    / "time_preferences.json"
)
SCHEDULED_PLANS_PATH = (
    SCHEDULER_DIR
    / "scheduled_plans.json"
)
PROACTIVE_STATE_PATH = (
    SCHEDULER_DIR
    / "proactive_state.json"
)
WEATHER_CACHE_PATH = (
    WEATHER_DIR / "weather_cache.json"
)
COGNITION_STATE_PATH = (
    COGNITION_DIR / "cognitive_state.json"
)

# Lv27: 长期任务承诺（课程/习惯类多周任务）
COMMITMENTS_PATH = (
    SCHEDULER_DIR / "commitments.json"
)
COMMITMENT_CLARIFY_PATH = (
    SCHEDULER_DIR
    / "commitment_clarification.json"
)
# Lv27: 语料使用冷却记录
CORPUS_USAGE_PATH = (
    CORPUS_STATE_DIR / "corpus_usage.json"
)
# Lv28: 记忆召回统计（与 documents.jsonl 分离，避免每轮重写大文件）
RECALL_STATS_PATH = (
    RAG_DIR / "recall_stats.json"
)
# Lv29: 语料自我生长（待审候选 / 已转正 / 审计）
CORPUS_CANDIDATES_PATH = (
    CORPUS_DIR / "candidates.jsonl"
)
CORPUS_LEARNED_PATH = (
    CORPUS_DIR / "learned.jsonl"
)
CORPUS_AUDIT_PATH = (
    CORPUS_STATE_DIR / "corpus_audit.jsonl"
)
# Lv32: 语料隐式正向信号（继续聊 = 弱正向，只影响排序）
CORPUS_SIGNALS_PATH = (
    CORPUS_STATE_DIR / "corpus_signals.json"
)


def ensure_directories() -> None:
    for path in (
        MEMORY_DIR,
        RAG_DIR,
        SUMMARY_DIR,
        PROFILE_DIR,
        SCHEDULER_DIR,
        WEATHER_DIR,
        COGNITION_DIR,
        CORPUS_STATE_DIR,
    ):
        path.mkdir(
            parents=True,
            exist_ok=True,
        )
