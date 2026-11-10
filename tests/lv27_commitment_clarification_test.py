from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.commitment import (
    ClarificationStore,
    CommitmentIntentAnalyzer,
    CommitmentService,
    CommitmentStore,
    resolve_start_date,
)
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_PATH
from silverwolf_agent.proactive import PlanManager

ZONE = ZoneInfo("Asia/Shanghai")
SATURDAY = datetime(2026, 9, 5, 20, 0, tzinfo=ZONE)


def _service(root: Path) -> CommitmentService:
    return CommitmentService(
        plan_manager=PlanManager(path=root / "plans.json"),
        store=CommitmentStore(root / "commitments.json"),
        clarify_store=ClarificationStore(root / "clarify.json"),
        default_clock="10:00",
    )


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    # Lv30: 人设已拆成核心 + 世界书模块，断言改为在「整份人设」上检查
    persona = PersonaLibrary().full_text()
    assert "Lv27 长期任务承诺" in persona
    assert "缺什么问什么" in persona
    assert "别像模板" in persona


def test_detects_habitual_commitment_and_asks_start_first() -> None:
    analyzer = CommitmentIntentAnalyzer()
    seed = analyzer.detect(
        "我以后每周的周末打算完成创新创业基础的视频学习",
        SATURDAY,
    )
    assert seed is not None
    assert seed.title == "创新创业基础的视频学习"
    assert seed.weekdays == (5, 6)
    assert seed.soft_weekend is True
    assert seed.clock == ""
    assert seed.weeks == 0
    # 缺的是：开始时间 / 钟点 / 周数（周几已在句子里说了）
    assert seed.missing_slots() == ["start", "clock", "weeks"]


def test_one_off_reminder_is_not_a_commitment() -> None:
    analyzer = CommitmentIntentAnalyzer()
    assert analyzer.detect("晚上提醒我取快递", SATURDAY) is None
    assert analyzer.detect("我明天可能学一会儿 pandas", SATURDAY) is None
    assert analyzer.detect("一分钟后叫我一下", SATURDAY) is None


def test_clarification_asks_only_missing_slots_and_rotates_wording() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir))

        first = service.handle(
            "我以后每周的周末打算完成创新创业基础的视频学习",
            SATURDAY,
        )
        assert first.mode == "question"
        assert first.goal_kind == "commitment_clarify_question"
        # 默认一轮问两个信息点，且只问缺的：start + clock（周几已在句子里）
        assert first.facts["slots"] == ["start", "clock"]
        assert service.has_pending_clarification(SATURDAY) is True

        # 用户只回答了钟点，周数与开始时间仍然缺；
        # 没问过的 weeks 先问，start 随后补问。
        second = service.handle("周六上午十点吧", SATURDAY)
        assert second.mode == "question"
        assert second.facts["slots"] == ["weeks", "start"]

        third = service.handle("先来八周", SATURDAY)
        assert third.mode == "question"
        assert third.facts["slots"] == ["start"]
        # 连续追问时必须换说法，不能复读
        assert third.fallback_text != second.fallback_text

        final = service.handle("这周就开始", SATURDAY)
        assert final.mode == "confirm"
        assert final.goal_kind == "confirm_commitment"
        assert final.commitment is not None
        assert final.commitment.clock == "10:00"
        assert final.commitment.total_weeks == 8
        assert service.has_pending_clarification(SATURDAY) is False


def test_single_question_mode_asks_one_slot_per_turn() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = CommitmentService(
            plan_manager=PlanManager(path=Path(temp_dir) / "plans.json"),
            store=CommitmentStore(Path(temp_dir) / "commitments.json"),
            clarify_store=ClarificationStore(Path(temp_dir) / "clarify.json"),
            max_questions=1,
        )
        turn = service.handle(
            "我以后每周的周末打算完成创新创业基础的视频学习",
            SATURDAY,
        )
        assert turn.mode == "question"
        assert turn.facts["slots"] == ["start"]


def test_merged_answer_skips_already_answered_slots() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir))
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        turn = service.handle("这周开始，周六十点，先来八周", SATURDAY)
        assert turn.mode == "confirm"
        assert turn.commitment is not None
        assert turn.commitment.weekdays == (5,)
        assert turn.commitment.total_weeks == 8


def test_user_can_abort_clarification() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir))
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        turn = service.handle("算了，先不弄了", SATURDAY)
        assert turn.mode == "update"
        assert service.has_pending_clarification(SATURDAY) is False
        assert service.store.active() == []


def test_chitchat_does_not_hijack_pending_session() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir))
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        turn = service.handle("今天好累啊", SATURDAY)
        # 岔开话题 → 正常聊天，不连环追问；会话保留到过期。
        assert turn.mode == "none"
        assert service.has_pending_clarification(SATURDAY) is True


def test_session_expires_after_deadline() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = CommitmentService(
            plan_manager=PlanManager(path=Path(temp_dir) / "plans.json"),
            store=CommitmentStore(Path(temp_dir) / "commitments.json"),
            clarify_store=ClarificationStore(Path(temp_dir) / "clarify.json"),
            clarify_expiry_hours=2,
        )
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        assert service.has_pending_clarification(SATURDAY) is True
        later = SATURDAY + timedelta(hours=3)
        assert service.has_pending_clarification(later) is False
        # 过期后同一句不会被当成答案强行确认。
        turn = service.handle("嗯", later)
        assert turn.mode == "none"


def test_resolve_start_date_respects_weekday_and_clock() -> None:
    # 周六 20:00 说“这周开始”，周六 10:00 已过 → 顺延到下周
    assert resolve_start_date(
        "this_week",
        weekdays=(5,),
        clock="10:00",
        now=SATURDAY,
    ).isoformat() == "2026-09-12"
    # 周日任务在周六说“这周开始” → 明天就能开始
    assert resolve_start_date(
        "this_week",
        weekdays=(6,),
        clock="10:00",
        now=SATURDAY,
    ).isoformat() == "2026-09-06"
    assert resolve_start_date(
        "next_week",
        weekdays=(5,),
        clock="10:00",
        now=SATURDAY,
    ).isoformat() == "2026-09-12"


def main() -> None:
    test_version_and_persona()
    test_detects_habitual_commitment_and_asks_start_first()
    test_one_off_reminder_is_not_a_commitment()
    test_clarification_asks_only_missing_slots_and_rotates_wording()
    test_single_question_mode_asks_one_slot_per_turn()
    test_merged_answer_skips_already_answered_slots()
    test_user_can_abort_clarification()
    test_chitchat_does_not_hijack_pending_session()
    test_session_expires_after_deadline()
    test_resolve_start_date_respects_weekday_and_clock()
    print("lv27 commitment clarification tests: PASS")


if __name__ == "__main__":
    main()
