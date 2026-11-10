from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.memory.rag import JsonlRAGStore, score_importance
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_PATH

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 18, 10, 0, tzinfo=ZONE)


def _store(root: Path, **kwargs) -> JsonlRAGStore:
    return JsonlRAGStore(path=root / "rag.jsonl", **kwargs)


def _append(
    store: JsonlRAGStore,
    text: str,
    *,
    days_ago: float,
    importance: int,
    now: datetime = NOW,
) -> str:
    doc_id = uuid.uuid4().hex
    created = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    payload = {
        "id": doc_id,
        "text": text,
        "metadata": {"kind": "event", "importance": importance},
        "created_at": created,
    }
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return doc_id


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    # Lv30: 人设已拆成核心 + 世界书模块，断言改为在「整份人设」上检查
    persona = PersonaLibrary().full_text()
    assert "Lv28 记忆与反思" in persona
    assert "不要主动播报" in persona


def test_importance_rules_are_deterministic() -> None:
    plain, reason = score_importance("天气不错")
    assert plain == 5
    assert reason == "基线"

    with_time, time_reason = score_importance("昨天那顿饭挺好吃")
    assert with_time == 6
    assert "含具体时间" in time_reason

    commitment, reason = score_importance("以后每周六提醒我学创新创业基础")
    assert commitment >= 7
    assert "含承诺或计划" in reason

    explicit, _ = score_importance("我生日是四月十五号")
    assert explicit >= 7

    bounded_high, _ = score_importance(
        "以后每周提醒我学习，我生日是四月十五号，最近很累，周六要考试"
    )
    assert bounded_high <= 10


def test_legacy_documents_without_importance_still_work() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = _store(Path(temp_dir))
        legacy = {
            "id": "legacy-1",
            "text": "以前那种没有重要度字段的记忆",
            "metadata": {},
            "created_at": NOW.isoformat(timespec="seconds"),
        }
        with store.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(legacy, ensure_ascii=False) + "\n")

        docs = store.all()
        assert len(docs) == 1
        assert docs[0].importance == 5
        scored = store.search_scored("记忆", top_k=3, now=NOW)
        assert scored
        assert scored[0][1]["importance"] == 5.0


def test_important_memory_outranks_trivial_one() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = _store(Path(temp_dir))
        # 同样是这句话（relevance 完全相同），只比重要度与新旧
        text = "关于那件事的聊天记录"
        important_id = _append(store, text, days_ago=60, importance=10)
        trivial_id = _append(store, text, days_ago=1, importance=2)

        docs = store.search("那件事", top_k=5, now=NOW)
        order = [doc.id for doc in docs]
        assert order.index(important_id) < order.index(trivial_id)


def test_old_trivial_memory_sinks_to_the_bottom() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = _store(Path(temp_dir))
        text = "关于那件事的聊天记录"
        old_id = _append(store, text, days_ago=300, importance=2)
        recent_id = _append(store, text, days_ago=1, importance=2)

        docs = store.search("那件事", top_k=5, now=NOW)
        order = [doc.id for doc in docs]
        assert order.index(recent_id) < order.index(old_id)


def test_recall_slows_down_forgetting() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = _store(Path(temp_dir))
        doc_id = _append(store, "一起做课程项目的记录", days_ago=90, importance=5)

        before = store.search_scored("课程项目", top_k=1, now=NOW)[0][1]
        store.mark_recalled([doc_id], NOW)
        store.mark_recalled([doc_id], NOW)
        store.mark_recalled([doc_id], NOW)
        after = store.search_scored("课程项目", top_k=1, now=NOW)[0][1]

        assert store.recall_count(doc_id) == 3
        assert after["recall_count"] == 3.0
        assert after["recency"] > before["recency"]
        assert after["final"] > before["final"]


def test_decay_can_be_disabled_to_match_lv27() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = _store(Path(temp_dir), decay_enabled=False)
        text = "关于那件事的聊天记录"
        _append(store, text, days_ago=300, importance=10)
        _append(store, text, days_ago=1, importance=1)

        scored = store.search_scored("那件事", top_k=5, now=NOW)
        assert len(scored) == 2
        for _, detail in scored:
            # 关闭衰减后只剩词法相关性
            assert detail["recency"] == 1.0
            assert detail["final"] == detail["relevance"]


def test_recall_stats_persist_and_survive_reload() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = _store(root)
        doc_id = _append(store, "持久化测试记录", days_ago=2, importance=6)
        store.mark_recalled([doc_id], NOW)

        reopened = JsonlRAGStore(path=root / "rag.jsonl")
        assert reopened.recall_count(doc_id) == 1
        stats = reopened.stats()
        assert stats["documents"] == 1
        assert stats["recalled_documents"] == 1
        assert stats["decay_enabled"] is True


def main() -> None:
    test_version_and_persona()
    test_importance_rules_are_deterministic()
    test_legacy_documents_without_importance_still_work()
    test_important_memory_outranks_trivial_one()
    test_old_trivial_memory_sinks_to_the_bottom()
    test_recall_slows_down_forgetting()
    test_decay_can_be_disabled_to_match_lv27()
    test_recall_stats_persist_and_survive_reload()
    print("lv28 memory decay tests: PASS")


if __name__ == "__main__":
    main()
