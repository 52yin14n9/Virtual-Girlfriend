from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.cognition import CognitiveStateManager
from silverwolf_agent.commitment import CommitmentStore
from silverwolf_agent.llm.base import BaseLLMClient
from silverwolf_agent.memory import ShortTermMemory
from silverwolf_agent.memory.rag import JsonlRAGStore
from silverwolf_agent.memory.reflection import ReflectionEngine
from silverwolf_agent.models import LLMResponse
from silverwolf_agent.proactive import ProactiveStateStore
from silverwolf_agent.proactive.contracts import RoutineEvent
from silverwolf_agent.proactive.planner import ProactivePlanner
from silverwolf_agent.memory import UserProfileManager

ZONE = ZoneInfo("Asia/Shanghai")
SUNDAY_NIGHT = datetime(2026, 10, 18, 21, 30, tzinfo=ZONE)  # 周日 21:30
TUESDAY = datetime(2026, 10, 13, 12, 0, tzinfo=ZONE)


class FixedLLM(BaseLLMClient):
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self.payload)


def _profile(root: Path) -> UserProfileManager:
    default_profile = root / "default_user_profile.json"
    shutil.copy2(
        PROJECT_ROOT / "config" / "default_user_profile.json",
        default_profile,
    )
    return UserProfileManager(
        path=root / "profile.json",
        default_path=default_profile,
    )


def _add_doc(
    rag: JsonlRAGStore,
    text: str,
    *,
    now: datetime,
    days_ago: float = 1,
    importance: int = 7,
) -> str:
    doc_id = uuid.uuid4().hex
    created = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    payload = {
        "id": doc_id,
        "text": text,
        "metadata": {"kind": "event", "importance": importance},
        "created_at": created,
    }
    with rag.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return doc_id


def _engine(root: Path, llm: BaseLLMClient | None = None, **kwargs):
    rag = JsonlRAGStore(path=root / "rag.jsonl")
    cognition = CognitiveStateManager(path=root / "cognition.json")
    memory = ShortTermMemory(path=root / "short.json")
    store = CommitmentStore(root / "commitments.json")
    engine = ReflectionEngine(
        rag=rag,
        cognition=cognition,
        memory=memory,
        commitment_store=store,
        llm=llm,
        **kwargs,
    )
    return engine, rag, cognition


def test_weekly_trigger_runs_once_per_day() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        engine, rag, _ = _engine(Path(temp_dir))
        _add_doc(rag, "这周聊到了课程安排", now=SUNDAY_NIGHT)

        assert engine.due(SUNDAY_NIGHT) == "weekly"
        result = engine.run(SUNDAY_NIGHT)
        assert result.ran is True
        assert result.trigger == "weekly"
        # 同一天不再重复
        assert engine.due(SUNDAY_NIGHT + timedelta(hours=1)) == ""


def test_threshold_trigger_before_weekend() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        engine, rag, _ = _engine(Path(temp_dir), importance_threshold=20)
        for index in range(3):
            _add_doc(
                rag,
                f"第 {index} 条很重要的记录",
                now=TUESDAY,
                days_ago=index,
                importance=8,
            )
        assert engine.due(TUESDAY) == "threshold"


def test_observation_without_evidence_is_dropped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _add_doc(JsonlRAGStore(path=root / "rag.jsonl"), "占位", now=SUNDAY_NIGHT)
        payload = json.dumps(
            {
                "week_summary": "这周聊得不少",
                "observations": [
                    {"claim": "他最近在想换工作", "confidence": 0.6, "evidence_doc_ids": []}
                ],
                "open_threads": [],
            },
            ensure_ascii=False,
        )
        engine, rag, cognition = _engine(root, llm=FixedLLM(payload))
        result = engine.run(SUNDAY_NIGHT)
        assert result.ran is True
        assert result.observations == ()
        assert result.dropped >= 1
        assert cognition.prompt_view(SUNDAY_NIGHT)["user_model"]["beliefs_as_hypotheses"] == []


def test_hallucinated_evidence_id_is_dropped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rag = JsonlRAGStore(path=root / "rag.jsonl")
        _add_doc(rag, "真实存在的一条记录", now=SUNDAY_NIGHT)
        payload = json.dumps(
            {
                "week_summary": "这周还行",
                "observations": [
                    {
                        "claim": "他最近在准备考试",
                        "confidence": 0.6,
                        "evidence_doc_ids": ["made-up-id"],
                    }
                ],
                "open_threads": [],
            },
            ensure_ascii=False,
        )
        engine, _, cognition = _engine(root, llm=FixedLLM(payload))
        result = engine.run(SUNDAY_NIGHT)
        assert result.observations == ()
        assert result.dropped >= 1
        assert cognition.prompt_view(SUNDAY_NIGHT)["user_model"]["beliefs_as_hypotheses"] == []


def test_banned_personality_labels_are_dropped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rag = JsonlRAGStore(path=root / "rag.jsonl")
        doc_id = _add_doc(rag, "他这周有两天没做课程", now=SUNDAY_NIGHT)
        payload = json.dumps(
            {
                "week_summary": "这周课程有两天没做",
                "observations": [
                    {
                        "claim": "他有点懒惰，不自律",
                        "confidence": 0.6,
                        "evidence_doc_ids": [doc_id],
                    }
                ],
                "open_threads": [],
            },
            ensure_ascii=False,
        )
        engine, _, cognition = _engine(root, llm=FixedLLM(payload))
        result = engine.run(SUNDAY_NIGHT)
        assert result.observations == ()
        assert result.dropped >= 1


def test_llm_reflection_writes_capped_beliefs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        rag = JsonlRAGStore(path=root / "rag.jsonl")
        doc_id = _add_doc(rag, "他说这周要交课程作业", now=SUNDAY_NIGHT)
        payload = json.dumps(
            {
                "week_summary": "这周主要在弄课程作业",
                "observations": [
                    {
                        "claim": "他最近在赶课程作业",
                        "confidence": 0.95,
                        "evidence_doc_ids": [doc_id],
                    }
                ],
                "open_threads": ["课程还剩 6 周"],
                "tone_notes": "这周他比较紧",
                "milestones": ["第一次连续做完两周"],
            },
            ensure_ascii=False,
        )
        engine, _, cognition = _engine(root, llm=FixedLLM(payload))
        result = engine.run(SUNDAY_NIGHT)

        assert result.source == "llm"
        assert len(result.observations) == 1
        beliefs = cognition.prompt_view(SUNDAY_NIGHT)["user_model"]["beliefs_as_hypotheses"]
        assert len(beliefs) == 1
        assert beliefs[0]["source"] == "reflection"
        assert beliefs[0]["confidence"] <= 0.65
        assert beliefs[0]["evidence_doc_ids"] == [doc_id]


def test_offline_reflection_is_honest_and_writes_no_beliefs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        engine, rag, cognition = _engine(root)
        _add_doc(rag, "这周聊了课程和睡觉", now=SUNDAY_NIGHT, importance=8)
        _add_doc(rag, "他周六做了课程", now=SUNDAY_NIGHT, days_ago=2, importance=9)

        result = engine.run(SUNDAY_NIGHT)
        assert result.ran is True
        assert result.source == "statistical"
        assert result.week_summary
        assert result.observations == ()
        assert cognition.prompt_view(SUNDAY_NIGHT)["user_model"]["beliefs_as_hypotheses"] == []
        # 反思本身进 RAG，kind=reflection
        kinds = [
            doc.metadata.get("kind")
            for doc in rag.all()
        ]
        assert "reflection" in kinds


def test_reflection_never_leaks_into_proactive_message() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        engine, rag, cognition = _engine(root)
        _add_doc(rag, "这周聊了课程", now=SUNDAY_NIGHT, importance=9)
        result = engine.run(SUNDAY_NIGHT)
        assert result.week_summary

        planner = ProactivePlanner(
            profile=_profile(root),
            memory=ShortTermMemory(path=root / "short2.json"),
            state=ProactiveStateStore(path=root / "state.json"),
            cognition=cognition,
        )
        plan_json = planner.plan_json(
            now=SUNDAY_NIGHT,
            routines=[
                RoutineEvent(
                    key="evening",
                    scheduled_at=SUNDAY_NIGHT.isoformat(timespec="seconds"),
                    weight=72,
                    window_minutes=60,
                )
            ],
            due_plans=[],
        )
        data = json.loads(plan_json)
        messages = data.get("planned_messages", data.get("messages", []))
        joined = "\n".join(str(item.get("content", "")) for item in messages)
        assert messages, "evening routine should produce a message"
        assert "我整理" not in joined
        assert result.week_summary[:12] not in joined


def test_legacy_cognition_state_migrates() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        legacy_path = root / "cognition.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "schema_version": 21,
                    "identity": {"core": {"name": "银狼"}},
                    "user_model": {"beliefs": [], "corrections": []},
                    "shared_reality": {"projects": [], "milestones": [], "commitments": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cognition = CognitiveStateManager(path=legacy_path)
        snapshot = cognition.reflection_snapshot()
        assert snapshot["runs"] == 0
        assert snapshot["kept"] == 0
        raw = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == 22
        assert raw["reflections"] == []


def main() -> None:
    test_weekly_trigger_runs_once_per_day()
    test_threshold_trigger_before_weekend()
    test_observation_without_evidence_is_dropped()
    test_hallucinated_evidence_id_is_dropped()
    test_banned_personality_labels_are_dropped()
    test_llm_reflection_writes_capped_beliefs()
    test_offline_reflection_is_honest_and_writes_no_beliefs()
    test_reflection_never_leaks_into_proactive_message()
    test_legacy_cognition_state_migrates()
    print("lv28 reflection tests: PASS")


if __name__ == "__main__":
    main()
