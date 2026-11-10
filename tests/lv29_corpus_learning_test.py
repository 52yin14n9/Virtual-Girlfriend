from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.dialogue.corpus import CorpusStore
from silverwolf_agent.dialogue.corpus_learn import CorpusLearner
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_PATH

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 20, 21, 0, tzinfo=ZONE)

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
    {
        "id": "hw_03",
        "scene": "chat_general",
        "text": "那就别熬那么晚了，早点睡",
        "semantic_tags": ["关心"],
        "relation_mode": "companionship",
        "register": "casual",
        "notes": "",
    },
    {
        "id": "hw_04",
        "scene": "care",
        "text": "先别管那么多，缓过来再说",
        "semantic_tags": ["安抚"],
        "relation_mode": "companionship",
        "register": "gentle",
        "notes": "",
    },
)


def _setup(root: Path) -> tuple[CorpusStore, CorpusLearner, Path]:
    corpus_dir = root / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    handwritten = corpus_dir / "handwritten.jsonl"
    handwritten.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in HANDWRITTEN) + "\n",
        encoding="utf-8",
    )
    corpus = CorpusStore(
        corpus_dir=corpus_dir,
        usage_path=root / "usage.json",
        learned_path=corpus_dir / "learned.jsonl",
        learned_share=0.3,
    )
    learner = CorpusLearner(
        corpus=corpus,
        candidates_path=corpus_dir / "candidates.jsonl",
        learned_path=corpus_dir / "learned.jsonl",
        audit_path=root / "audit.jsonl",
    )
    return corpus, learner, handwritten


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    # Lv30: 人设已拆成核心 + 世界书模块，断言改为在「整份人设」上检查
    persona = PersonaLibrary().full_text()
    assert "Lv29 语料生长" in persona
    assert "不要主动说“我学会了这句”" in persona


def test_fact_bearing_text_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        _, learner, _ = _setup(Path(temp_dir))
        assert learner.guard("三点的时候提醒你", kind="style").reason.startswith(
            "contains_fact"
        )
        assert learner.guard("12 点开会别忘了", kind="style").reason.startswith(
            "contains_fact"
        )
        assert learner.guard("第 3 周再接着做", kind="style").reason.startswith(
            "contains_fact"
        )


def test_privacy_is_blocked_and_audited() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _, learner, _ = _setup(root)
        cases = {
            "我的号是 123456789": "privacy",
            "发到 someone@example.com 吧": "privacy",
            "服务器 192.168.1.10 挂了": "privacy",
            "我在那个大学读书": "privacy",
        }
        for text, expected in cases.items():
            result = learner.guard(text, kind="style")
            assert not result.ok
            assert result.reason.startswith(expected), (text, result.reason)

        outcome = learner.consider_assistant_text(
            "我的号是 123456789",
            scene="chat_general",
            now=NOW,
        )
        assert outcome["accepted"] is False
        audit = (root / "audit.jsonl").read_text(encoding="utf-8")
        assert "privacy_blocked" in audit
        # 审计不能记录原句
        assert "123456789" not in audit


def test_tone_and_personality_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        _, learner, _ = _setup(Path(temp_dir))
        assert learner.guard("提醒你一下该起床了").reason == "notification_tone"
        assert learner.guard("你就是太懒了").reason == "personality_label"


def test_shape_and_length_guards() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        _, learner, _ = _setup(Path(temp_dir))
        assert learner.guard("嗯").reason == "too_short"
        assert learner.guard("“带引号的句子不该进池子”").reason == "bad_shape"
        assert learner.guard("一句话。又一句话").reason == "not_single_sentence"


def test_near_duplicate_of_handwritten_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        _, learner, _ = _setup(Path(temp_dir))
        duplicated = HANDWRITTEN[0]["text"]
        assert learner.guard(duplicated).reason == "too_close_to_corpus"


def test_pending_candidate_is_not_used_for_sampling() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus, learner, _ = _setup(Path(temp_dir))
        outcome = learner.consider_assistant_text(
            "这句新学的话先放在待审里",
            scene="chat_general",
            now=NOW,
        )
        assert outcome["accepted"] is True
        assert learner.stats(NOW)["pending_candidates"] == 1

        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "这句新学的话先放在待审里" not in texts


def test_approve_makes_it_usable_and_reject_blocks_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus, learner, _ = _setup(Path(temp_dir))
        first = learner.consider_assistant_text(
            "这句新学的话先放在待审里",
            scene="chat_general",
            now=NOW,
        )
        entry = learner.approve(first["candidate_id"], NOW)
        assert entry is not None

        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "这句新学的话先放在待审里" in texts

        second = learner.consider_assistant_text(
            "另一句想学的话也放进来",
            scene="chat_general",
            now=NOW,
        )
        assert learner.reject(second["candidate_id"], NOW) is True
        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "另一句想学的话也放进来" not in texts

        # 「别这样说」按文本撤回已转正条目
        assert learner.reject_text("这句新学的话先放在待审里", NOW) is True
        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "这句新学的话先放在待审里" not in texts


def test_learned_share_is_capped() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus, learner, _ = _setup(Path(temp_dir))
        candidates = [
            "这句话学下来还挺自然的啊",
            "再学一句比较随口的说法",
            "这句也想留在池子里试试",
            "还有一句偶尔用一下就好",
        ]
        for text in candidates:
            outcome = learner.consider_assistant_text(
                text,
                scene="chat_general",
                now=NOW,
            )
            if outcome.get("accepted"):
                learner.approve(str(outcome["candidate_id"]), NOW)

        stats = corpus.stats()
        assert stats["learned"] >= 1

        picked = corpus.samples("chat_general", k=3)
        learned_picked = [item for item in picked if item.source == "learned"]
        # k=3、share=0.3 → 最多 1 条学来的
        assert len(learned_picked) <= 1


def test_maintain_retires_stale_entries_and_keeps_handwritten() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus, learner, handwritten = _setup(Path(temp_dir))
        before = handwritten.read_text(encoding="utf-8")

        outcome = learner.consider_assistant_text(
            "很早以前学会的一句话",
            scene="chat_general",
            now=NOW - timedelta(days=200),
        )
        entry = learner.approve(str(outcome["candidate_id"]), NOW - timedelta(days=200))
        assert entry is not None

        result = learner.maintain(NOW)
        assert result["retired"] >= 1
        stats = learner.stats(NOW)
        assert stats["learned_active"] == 0
        assert stats["learned_retired"] >= 1

        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "很早以前学会的一句话" not in texts

        # 手写语料一行都不能变
        assert handwritten.read_text(encoding="utf-8") == before
        assert corpus.stats()["handwritten"] == len(HANDWRITTEN)


def test_manual_add_can_skip_review_with_all_guards() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus, learner, _ = _setup(Path(temp_dir))
        blocked = learner.add_manual(
            "我的号是 123456789",
            scene="chat_general",
            now=NOW,
            approve=True,
        )
        assert blocked["accepted"] is False

        ok = learner.add_manual(
            "这句是我自己加进去的",
            scene="chat_general",
            now=NOW,
            approve=True,
        )
        assert ok["accepted"] is True and ok["approved"] is True
        texts = [item.text for item in corpus.samples("chat_general", k=5)]
        assert "这句是我自己加进去的" in texts


def main() -> None:
    test_version_and_persona()
    test_fact_bearing_text_is_rejected()
    test_privacy_is_blocked_and_audited()
    test_tone_and_personality_are_rejected()
    test_shape_and_length_guards()
    test_near_duplicate_of_handwritten_is_rejected()
    test_pending_candidate_is_not_used_for_sampling()
    test_approve_makes_it_usable_and_reject_blocks_it()
    test_learned_share_is_capped()
    test_maintain_retires_stale_entries_and_keeps_handwritten()
    test_manual_add_can_skip_review_with_all_guards()
    print("lv29 corpus learning tests: PASS")


if __name__ == "__main__":
    main()
