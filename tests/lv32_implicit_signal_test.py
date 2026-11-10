from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.dialogue.corpus import CorpusStore
from silverwolf_agent.dialogue.corpus_learn import CorpusLearner

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 21, 0, tzinfo=ZONE)

HANDWRITTEN = (
    {
        "id": "hw_01",
        "scene": "chat_general",
        "text": "行，那你自己看着办，别硬撑",
        "semantic_tags": ["关心"],
        "relation_mode": "companionship",
        "register": "casual",
        "notes": "",
    },
    {
        "id": "hw_02",
        "scene": "chat_general",
        "text": "听着挺累的，先歇一会儿再说",
        "semantic_tags": ["关心"],
        "relation_mode": "companionship",
        "register": "casual",
        "notes": "",
    },
)


def _setup(root: Path) -> tuple[CorpusStore, CorpusLearner]:
    import json

    corpus_dir = root / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "handwritten.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in HANDWRITTEN) + "\n",
        encoding="utf-8",
    )
    corpus = CorpusStore(
        corpus_dir=corpus_dir,
        usage_path=root / "usage.json",
        learned_path=corpus_dir / "learned.jsonl",
    )
    learner = CorpusLearner(
        corpus=corpus,
        candidates_path=corpus_dir / "candidates.jsonl",
        learned_path=corpus_dir / "learned.jsonl",
        audit_path=root / "audit.jsonl",
        signals_path=root / "signals.json",
        flush_threshold=1,
    )
    return corpus, learner


def test_signal_raises_candidate_priority() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, learner = _setup(root)
        first = learner.consider_assistant_text(
            "先歇会儿吧，别急着接着弄",
            scene="chat_general",
            now=NOW,
        )
        second = learner.consider_assistant_text(
            "想弄就弄一会儿，不想就算",
            scene="chat_general",
            now=NOW,
        )
        assert first["accepted"] and second["accepted"]

        before = [item["id"] for item in learner.review(limit=5)]
        # 给第二句记两次弱正向
        learner.record_implicit_signal("想弄就弄一会儿，不想就算")
        learner.record_implicit_signal("想弄就弄一会儿，不想就算")
        after = [item["id"] for item in learner.review(limit=5)]

        assert learner.implicit_score("想弄就弄一会儿，不想就算") == 2
        assert after[0] == second["candidate_id"]
        assert before[0] != second["candidate_id"]


def test_signal_never_auto_approves() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        corpus, learner = _setup(root)
        outcome = learner.consider_assistant_text(
            "这句还没被批准呢",
            scene="chat_general",
            now=NOW,
        )
        for _ in range(5):
            learner.record_implicit_signal("这句还没被批准呢")

        pending = learner.stats(NOW)["pending_candidates"]
        assert pending == 1
        assert learner.stats(NOW)["learned_active"] == 0
        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "这句还没被批准呢" not in texts
        assert outcome["accepted"] is True


def test_silence_records_nothing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, learner = _setup(root)
        learner.consider_assistant_text(
            "说了句没被回应的话",
            scene="chat_general",
            now=NOW,
        )
        # 用户没回复：不产生任何信号（既不加分也不记负面）
        assert learner.implicit_score("说了句没被回应的话") == 0
        signals = learner._read_signals()
        assert all(value >= 0 for value in signals.values())


def test_signal_persists_and_is_capped_by_text() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, learner = _setup(root)
        learner.record_implicit_signal("持久化的一句话", NOW)
        reopened = CorpusLearner(
            corpus=CorpusStore(
                corpus_dir=root / "corpus",
                usage_path=root / "usage.json",
                learned_path=root / "corpus" / "learned.jsonl",
            ),
            candidates_path=root / "corpus" / "candidates.jsonl",
            learned_path=root / "corpus" / "learned.jsonl",
            audit_path=root / "audit.jsonl",
            signals_path=root / "signals.json",
        )
        assert reopened.implicit_score("持久化的一句话") == 1
        assert reopened.implicit_score("不存在的一句话") == 0


def main() -> None:
    test_signal_raises_candidate_priority()
    test_signal_never_auto_approves()
    test_silence_records_nothing()
    test_signal_persists_and_is_capped_by_text()
    print("lv32 implicit signal tests: PASS")


if __name__ == "__main__":
    main()
