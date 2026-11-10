from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.proactive import PlanManager, ProactiveStateStore, TimeManager

ZONE = ZoneInfo("Asia/Shanghai")
DAY = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)


def _manager(root: Path, **kwargs) -> TimeManager:
    return TimeManager(
        path=root / "time.json",
        timezone="Asia/Shanghai",
        **kwargs,
    )


def test_jitter_is_deterministic_within_a_day() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir))
        slot = manager.slot("morning")
        scheduled = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)
        first = manager.apply_jitter(
            scheduled,
            key="morning",
            slot=slot,
            now=DAY,
        )
        second = manager.apply_jitter(
            scheduled,
            key="morning",
            slot=slot,
            now=DAY,
        )
        assert first == second


def test_jitter_varies_across_days() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir))
        base = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)
        offsets = set()
        for day_offset in range(7):
            scheduled = base + timedelta(days=day_offset)
            jittered = manager.apply_jitter(
                scheduled,
                key="morning",
                slot={"time": "08:00", "window_minutes": 60},
                now=scheduled,
            )
            offsets.add(int((jittered - scheduled).total_seconds() // 60))
        assert len(offsets) >= 2, "七天里触发时刻不应完全一样"


def test_jitter_stays_within_limit() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir), jitter_minutes=10)
        base = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)
        for day_offset in range(30):
            scheduled = base + timedelta(days=day_offset)
            jittered = manager.apply_jitter(
                scheduled,
                key="morning",
                slot={"time": "08:00"},
                now=scheduled,
            )
            delta = abs((jittered - scheduled).total_seconds() / 60)
            assert delta <= 10


def test_user_changed_slot_is_pinned() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir), jitter_minutes=10, pinned_days=7)
        manager.set_slot("morning", "09:00")
        slot = manager.slot("morning")
        assert slot.get("updated_at")

        scheduled = datetime(2026, 10, 21, 9, 0, tzinfo=ZONE)
        jittered = manager.apply_jitter(
            scheduled,
            key="morning",
            slot=slot,
            now=datetime.now(ZONE),
        )
        assert jittered == scheduled, "刚改过的时间必须准点"


def test_pinned_days_zero_disables_pinning() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir), jitter_minutes=10, pinned_days=0)
        manager.set_slot("morning", "09:00")
        slot = manager.slot("morning")
        base = datetime(2026, 10, 21, 9, 0, tzinfo=ZONE)
        offsets = set()
        for day_offset in range(10):
            scheduled = base + timedelta(days=day_offset)
            jittered = manager.apply_jitter(
                scheduled,
                key="morning",
                slot=slot,
                now=scheduled,
            )
            offsets.add(int((jittered - scheduled).total_seconds() // 60))
        assert len(offsets) >= 2


def test_disabled_jitter_keeps_exact_time() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = _manager(Path(temp_dir), jitter_enabled=False)
        scheduled = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)
        jittered = manager.apply_jitter(
            scheduled,
            key="morning",
            slot={"time": "08:00"},
            now=scheduled,
        )
        assert jittered == scheduled


def test_formal_reminder_due_time_is_untouched() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manager = _manager(root, jitter_minutes=10)
        # 正式提醒（计划）由 PlanManager 直接写入 due_at，不经过抖动
        plan_manager = PlanManager(path=root / "plans.json")
        due_at = "2026-10-21T09:00:00+08:00"
        plan = plan_manager.create(
            title="吃药",
            details="",
            due_at=due_at,
            importance=90,
        )
        assert plan.due_at == due_at

        # 时间槽的默认到期时间也不抖动
        default_due = manager.default_due_time(DAY, "morning")
        assert default_due == datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)


def test_due_routines_respect_window_after_jitter() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        manager = _manager(root, jitter_minutes=10)
        state = ProactiveStateStore(path=root / "state.json")
        slot = manager.slot("morning")
        scheduled = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)
        jittered = manager.apply_jitter(
            scheduled,
            key="morning",
            slot=slot,
            now=scheduled,
        )

        # 抖动前的一分钟不该触发
        before = manager.due_routines(jittered - timedelta(minutes=1), state)
        assert all(event.key != "morning" for event in before)
        # 抖动后的时刻应该触发
        after = manager.due_routines(jittered, state)
        assert any(event.key == "morning" for event in after)


def main() -> None:
    test_jitter_is_deterministic_within_a_day()
    test_jitter_varies_across_days()
    test_jitter_stays_within_limit()
    test_user_changed_slot_is_pinned()
    test_pinned_days_zero_disables_pinning()
    test_disabled_jitter_keeps_exact_time()
    test_formal_reminder_due_time_is_untouched()
    test_due_routines_respect_window_after_jitter()
    print("lv30 proactive jitter tests: PASS")


if __name__ == "__main__":
    main()
