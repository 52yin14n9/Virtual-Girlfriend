from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.cognition import CognitiveStateManager
from silverwolf_agent.commitment import (
    ClarificationStore,
    CommitmentService,
    CommitmentStore,
)
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager
from silverwolf_agent.proactive import PlanManager, ProactiveStateStore
from silverwolf_agent.proactive.contracts import RoutineEvent
from silverwolf_agent.proactive.planner import ProactivePlanner
from silverwolf_agent.world import ContextualCareComposer

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=ZONE)


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


def _routine(now: datetime) -> RoutineEvent:
    return RoutineEvent(
        key="morning",
        scheduled_at=now.isoformat(timespec="seconds"),
        weight=72,
        window_minutes=60,
    )


def _service(root: Path, now: datetime) -> CommitmentService:
    service = CommitmentService(
        plan_manager=PlanManager(path=root / "plans.json"),
        store=CommitmentStore(root / "commitments.json"),
        clarify_store=ClarificationStore(root / "clarify.json"),
    )
    service.handle("我以后每周的周末打算完成创新创业基础的视频学习", now)
    service.handle("这周开始，周六十点，先来八周", now)
    return service


def _planner(root: Path, service: CommitmentService | None) -> ProactivePlanner:
    return ProactivePlanner(
        profile=_profile(root),
        memory=ShortTermMemory(path=root / "short.json"),
        state=ProactiveStateStore(path=root / "state.json"),
        cognition=CognitiveStateManager(path=root / "cognition.json"),
        commitment_service=service,
        silence_return_hours=18.0,
    )


def _contents(plan_json: str) -> str:
    data = json.loads(plan_json)
    messages = data.get("planned_messages", data.get("messages", []))
    return "\n".join(str(item.get("content", "")) for item in messages)


def test_continuation_prefers_open_thread() -> None:
    composer = ContextualCareComposer()
    line = composer.silence_continuation(
        "",
        open_threads=["创新创业基础的视频学习"],
    )
    assert "创新创业基础的视频学习" in line
    assert line.startswith("上次说的")


def test_continuation_falls_back_to_topic_memory() -> None:
    composer = ContextualCareComposer()
    line = composer.silence_continuation(
        "最近还在折腾 NapCat 部署，服务器老是掉线",
        open_threads=[],
    )
    assert "部署" in line


def test_compose_replaces_greeting_after_silence() -> None:
    composer = ContextualCareComposer()
    base = "早，星。醒了吗？今天准备从哪件事开始？"
    content, metadata = composer.compose(
        base=base,
        routine_key="morning",
        now=NOW,
        recent_user_text="",
        weather_result=None,
        memory_callback_enabled=True,
        weekend_suggestions_enabled=False,
        silence_return=True,
        open_threads=["创新创业基础的视频学习"],
    )
    assert metadata.get("silence_return") is True
    assert content != base
    assert "创新创业基础的视频学习" in content
    assert "醒了吗" not in content


def test_compose_keeps_greeting_without_silence() -> None:
    composer = ContextualCareComposer()
    base = "早，星。醒了吗？今天准备从哪件事开始？"
    content, metadata = composer.compose(
        base=base,
        routine_key="morning",
        now=NOW,
        recent_user_text="",
        weather_result=None,
        memory_callback_enabled=False,
        weekend_suggestions_enabled=False,
    )
    assert content == base
    assert "silence_return" not in metadata


def test_planner_uses_silence_return_after_18_hours() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        service = _service(root, NOW)
        planner = _planner(root, service)
        # 用户 20 小时没说话
        planner.state.note_user_activity(NOW - timedelta(hours=20))

        text = _contents(
            planner.plan_json(
                now=NOW,
                routines=[_routine(NOW)],
                due_plans=[],
            )
        )
        assert "创新创业基础的视频学习" in text
        assert "上次说的" in text


def test_planner_keeps_normal_greeting_within_18_hours() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        service = _service(root, NOW)
        planner = _planner(root, service)
        planner.state.note_user_activity(NOW - timedelta(hours=3))

        text = _contents(
            planner.plan_json(
                now=NOW,
                routines=[_routine(NOW)],
                due_plans=[],
            )
        )
        assert "上次说的" not in text


def test_formal_commitment_reminder_is_untouched_by_silence() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        service = _service(root, NOW)
        planner = _planner(root, service)
        plan_manager = service.plan_manager
        plans = sorted(
            plan_manager.list_plans(active_only=True),
            key=lambda item: item.due_at,
        )
        assert plans

        content = planner._render_due_content(
            plan=plans[0],
            now=datetime.fromisoformat(plans[0].due_at),
            casual_alias="宝",
        )
        assert "创新创业基础的视频学习" in content
        assert "上次说的" not in content


def main() -> None:
    test_continuation_prefers_open_thread()
    test_continuation_falls_back_to_topic_memory()
    test_compose_replaces_greeting_after_silence()
    test_compose_keeps_greeting_without_silence()
    test_planner_uses_silence_return_after_18_hours()
    test_planner_keeps_normal_greeting_within_18_hours()
    test_formal_commitment_reminder_is_untouched_by_silence()
    print("lv28 silence return tests: PASS")


if __name__ == "__main__":
    main()
