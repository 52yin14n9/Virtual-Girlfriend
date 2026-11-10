from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.delivery import OutboundMessage
from silverwolf_agent.proactive.contracts import ScheduledPlan
from silverwolf_agent.proactive.plan_manager import PlanManager
from silverwolf_agent.proactive.planner import ProactivePlanner
from silverwolf_agent.proactive.reminder_language import (
    normalize_reminder_action,
    render_due_reminder,
    render_schedule_confirmation,
    spoken_action,
)
from silverwolf_agent.proactive.schedule_intent import clean_schedule_title
from silverwolf_agent.tools.plan_tools import PlanCreateTool

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 8, 8, 50, tzinfo=ZONE)


FORBIDDEN_NOTIFICATION_PHRASES = (
    "提醒你一下",
    "早上提醒",
    "我记着呢",
    "今天要我",
    "系统",
    "任务已",
)


def test_legacy_first_person_title_is_normalized() -> None:
    assert clean_schedule_title("我到工作室") == "到工作室"
    assert normalize_reminder_action("提醒我到工作室") == "到工作室"
    assert spoken_action("我到工作室") == "去工作室"
    # Family/possessive noun phrases must not be blindly stripped.
    assert clean_schedule_title("我妈生日") == "我妈生日"


def test_due_reminders_sound_like_a_person() -> None:
    cases = {
        "提醒睡觉": "宝，该睡觉啦",
        "我到工作室": "宝，该去工作室啦",
        "学习pandas": "宝，该学习pandas啦",
        "吃药": "宝，该吃药啦",
        "开会": "宝，该开会啦",
    }
    for title, expected in cases.items():
        actual = render_due_reminder(title=title, casual_alias="宝")
        assert actual == expected
        assert not any(bad in actual for bad in FORBIDDEN_NOTIFICATION_PHRASES)
        assert "提醒" not in actual
        assert not actual.endswith("。")


def test_proactive_plan_uses_natural_renderer_for_morning_case() -> None:
    plan = ScheduledPlan.create(
        title="我到工作室",
        details="",
        due_at=datetime(2026, 8, 8, 9, 0, tzinfo=ZONE).isoformat(timespec="seconds"),
        importance=90,
        source_text="早上九点提醒我到工作室",
    )
    actual = ProactivePlanner._plan_content(
        plan=plan,
        now=datetime(2026, 8, 8, 9, 0, tzinfo=ZONE),
        casual_alias="宝",
    )
    assert actual == "宝，该去工作室啦"
    assert "早上提醒你一下" not in actual
    assert "我记着呢" not in actual
    assert "今天要我" not in actual


def test_schedule_confirmation_avoids_notification_voice() -> None:
    once = render_schedule_confirmation(
        title="我到工作室",
        due_at="2026-08-08T09:00:00+08:00",
        now=NOW,
        recurrence="none",
        friendly_due="今天 09:00 ",
        clock="09:00",
        weekday="",
    )
    assert once == "好，今天 09:00 我来喊你去工作室"
    assert "提醒" not in once
    assert "我记着" not in once

    daily = render_schedule_confirmation(
        title="睡觉",
        due_at="2026-08-08T23:30:00+08:00",
        now=NOW,
        recurrence="daily",
        friendly_due="今天 23:30 ",
        clock="23:30",
        weekday="",
    )
    # The existing good bedtime confirmation remains intact after delivery punctuation normalization.
    msg = OutboundMessage(
        content=daily,
        weight=90,
        category="conversation",
        source="interactive",
    )
    assert msg.content == "好啊，以后每天 23:30 我叫你睡觉。到点就别再偷偷熬夜了"


def test_plan_create_normalizes_title_before_persisting() -> None:
    with tempfile.TemporaryDirectory() as value:
        manager = PlanManager(path=Path(value) / "plans.json")
        result = PlanCreateTool(manager).run(
            {
                "title": "我到工作室",
                "details": "",
                "due_at": "2026-08-08T09:00:00+08:00",
                "importance": 90,
                "recurrence": "none",
                "source_text": "早上九点提醒我到工作室",
            }
        )
        assert result.ok is True
        assert result.content["title"] == "到工作室"
        saved = manager.list_plans(active_only=True)
        assert len(saved) == 1
        assert saved[0].title == "到工作室"


def run() -> None:
    test_legacy_first_person_title_is_normalized()
    test_due_reminders_sound_like_a_person()
    test_proactive_plan_uses_natural_renderer_for_morning_case()
    test_schedule_confirmation_avoids_notification_voice()
    test_plan_create_normalizes_title_before_persisting()
    print("lv23_reminder_language_test: OK")


if __name__ == "__main__":
    run()
