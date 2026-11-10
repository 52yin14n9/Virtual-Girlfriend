from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.commitment import (
    ClarificationStore,
    CommitmentService,
    CommitmentStore,
)
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager
from silverwolf_agent.proactive import PlanManager, ProactiveStateStore
from silverwolf_agent.proactive.planner import ProactivePlanner

ZONE = ZoneInfo("Asia/Shanghai")
SATURDAY = datetime(2026, 9, 5, 20, 0, tzinfo=ZONE)
FIRST_DUE = datetime(2026, 9, 12, 10, 0, tzinfo=ZONE)

FORBIDDEN = (
    "提醒你一下",
    "我记着呢",
    "系统",
    "档案",
    "存档",
    "任务已",
    "请及时完成",
    "有进步",
    "总算",
    "汇报",
)


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


def _build(root: Path):
    plan_manager = PlanManager(path=root / "plans.json")
    service = CommitmentService(
        plan_manager=plan_manager,
        store=CommitmentStore(root / "commitments.json"),
        clarify_store=ClarificationStore(root / "clarify.json"),
        default_clock="10:00",
    )
    return plan_manager, service


def _commit(service: CommitmentService, now: datetime = SATURDAY):
    service.handle("我以后每周的周末打算完成创新创业基础的视频学习", now)
    return service.handle("这周开始，周六十点，先来八周", now)


def test_confirmation_materializes_occurrences() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        turn = _commit(service)

        assert turn.mode == "confirm"
        assert turn.commitment is not None

        plans = plan_manager.list_plans(active_only=True)
        assert len(plans) == 6  # horizon 默认 6 周先行物化
        first = sorted(plans, key=lambda item: item.due_at)[0]
        assert first.title == "创新创业基础的视频学习"
        assert first.due_at.startswith("2026-09-12T10:00")
        assert first.metadata["kind"] == "commitment_occurrence"
        assert first.metadata["week_index"] == 1
        assert first.metadata["total_weeks"] == 8


def test_occurrence_wording_carries_week_progress() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        _commit(service)

        planner = ProactivePlanner(
            profile=_profile(root),
            memory=ShortTermMemory(path=root / "short.json"),
            state=ProactiveStateStore(path=root / "state.json"),
            commitment_service=service,
        )
        plans = sorted(
            plan_manager.list_plans(active_only=True),
            key=lambda item: item.due_at,
        )
        first_text = planner._render_due_content(
            plan=plans[0],
            now=FIRST_DUE,
            casual_alias="宝",
        )
        assert "创新创业基础的视频学习" in first_text
        assert "1/8" in first_text
        third_text = planner._render_due_content(
            plan=plans[2],
            now=datetime.fromisoformat(plans[2].due_at),
            casual_alias="宝",
        )
        assert "3/8" in third_text
        assert not any(bad in first_text for bad in FORBIDDEN)


def test_soft_weekend_prefers_single_completion_per_week() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        # 不点名具体哪一天 → 柔和模式，周末做完一次即可
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        turn = service.handle("这周开始，上午十点，先来八周", SATURDAY)
        assert turn.mode == "confirm"
        assert turn.commitment is not None
        assert turn.commitment.soft_weekend is True
        assert turn.commitment.weekdays == (5, 6)

        plans = sorted(
            plan_manager.list_plans(active_only=True),
            key=lambda item: item.due_at,
        )
        primary = [item for item in plans if item.metadata["is_primary"]]
        secondary = [item for item in plans if not item.metadata["is_primary"]]
        assert primary
        assert secondary

        planner = ProactivePlanner(
            profile=_profile(root),
            memory=ShortTermMemory(path=root / "short2.json"),
            state=ProactiveStateStore(path=root / "state2.json"),
            commitment_service=service,
        )
        nudge = planner._render_due_content(
            plan=secondary[0],
            now=datetime.fromisoformat(secondary[0].due_at),
            casual_alias="宝",
        )
        assert "创新创业基础的视频学习" in nudge
        assert not any(bad in nudge for bad in FORBIDDEN)


def test_skip_and_complete_track_progress() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        _commit(service)

        skip = service.handle("这周先跳过", FIRST_DUE)
        assert skip.mode == "update"
        assert service.store.active()[0].skipped_weeks == [1]

        done = service.handle("这周做完了", FIRST_DUE + timedelta(days=7))
        assert done.mode == "status"
        commitment = service.store.active()[0]
        assert 2 in commitment.completed_weeks
        assert commitment.remaining_weeks() == 6


def test_finishing_all_weeks_closes_commitment() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        service.handle("我以后每周的周末打算完成创新创业基础的视频学习", SATURDAY)
        turn = service.handle("这周开始，周六十点，先来两周", SATURDAY)
        assert turn.commitment is not None

        service.handle("这周做完了", FIRST_DUE)
        final = service.handle("这周做完了", FIRST_DUE + timedelta(days=7))
        assert final.mode == "status"
        assert final.goal_kind == "commitment_finish"
        assert service.store.active() == []
        assert plan_manager.list_plans(active_only=True) == []


def test_cancel_stops_future_reminders() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        _commit(service)
        assert plan_manager.list_plans(active_only=True)

        turn = service.handle("把视频学习取消掉", SATURDAY + timedelta(hours=1))
        assert turn.mode == "update"
        assert service.store.active() == []
        assert plan_manager.list_plans(active_only=True) == []


def test_edit_reschedules_and_clears_old_plans() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        _commit(service)

        turn = service.handle("改成周日早上九点", SATURDAY + timedelta(hours=1))
        assert turn.mode == "update"
        commitment = service.store.active()[0]
        assert commitment.clock == "09:00"
        assert commitment.weekdays == (6,)
        active = plan_manager.list_plans(active_only=True)
        assert active
        assert all("T09:00" in plan.due_at for plan in active)


def test_sync_schedule_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        plan_manager, service = _build(root)
        _commit(service)
        before = len(plan_manager.list_plans(active_only=True))
        created = service.sync_schedule(SATURDAY)
        after = len(plan_manager.list_plans(active_only=True))
        assert created == []
        assert after == before


def main() -> None:
    test_confirmation_materializes_occurrences()
    test_occurrence_wording_carries_week_progress()
    test_soft_weekend_prefers_single_completion_per_week()
    test_skip_and_complete_track_progress()
    test_finishing_all_weeks_closes_commitment()
    test_cancel_stops_future_reminders()
    test_edit_reschedules_and_clears_old_plans()
    test_sync_schedule_is_idempotent()
    print("lv27 commitment occurrence tests: PASS")


if __name__ == "__main__":
    main()
