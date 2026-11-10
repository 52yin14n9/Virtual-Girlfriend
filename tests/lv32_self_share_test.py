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

from silverwolf_agent import __version__  # noqa: E402
from silverwolf_agent.cognition import CognitiveStateManager  # noqa: E402
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager  # noqa: E402
from silverwolf_agent.dialogue.speech import SpeechComposer  # noqa: E402
from silverwolf_agent.dialogue.corpus import CorpusStore  # noqa: E402
from silverwolf_agent.llm.base import BaseLLMClient  # noqa: E402
from silverwolf_agent.models import LLMResponse  # noqa: E402
from silverwolf_agent.paths import PERSONA_PATH  # noqa: E402
from silverwolf_agent.proactive import ProactiveStateStore  # noqa: E402
from silverwolf_agent.proactive.contracts import RoutineEvent  # noqa: E402
from silverwolf_agent.proactive.planner import ProactivePlanner  # noqa: E402

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 8, 5, tzinfo=ZONE)


class FixedLLM(BaseLLMClient):
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self.output)


def _events(now: datetime) -> list[dict]:
    def event(event_id: str, days_ago: int, kind: str, summary: str) -> dict:
        day = (now - timedelta(days=days_ago)).date().isoformat()
        return {
            "event_id": event_id,
            "date": day,
            "kind": kind,
            "summary": summary,
            "detail": "",
            "shareable": True,
            "shared_at": None,
            "continuity_scope": "persona_offscreen_life",
        }

    return [
        event("life_old", 20, "gaming", "很久以前的一局游戏"),
        event("life_mid", 4, "tinkering", "折腾了一小会儿脚本"),
        event("life_new", 2, "music", "反复听同一首歌"),
        event("life_today", 0, "archive", "今天整理了点东西"),
        {
            "event_id": "life_hidden",
            "date": (now - timedelta(days=3)).date().isoformat(),
            "kind": "gaming",
            "summary": "不可分享的事",
            "detail": "",
            "shareable": False,
            "shared_at": None,
            "continuity_scope": "persona_offscreen_life",
        },
    ]


def _cognition(root: Path, now: datetime = NOW) -> CognitiveStateManager:
    path = root / "cognition.json"
    payload = {
        "schema_version": 22,
        "life": {
            "last_advanced_date": now.date().isoformat(),
            "events": _events(now),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return CognitiveStateManager(path=path)


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


def _planner(
    root: Path,
    cognition: CognitiveStateManager,
    *,
    enabled: bool = True,
    per_week: int = 2,
    speech: SpeechComposer | None = None,
) -> ProactivePlanner:
    return ProactivePlanner(
        profile=_profile(root),
        memory=ShortTermMemory(path=root / "short.json"),
        state=ProactiveStateStore(path=root / "state.json"),
        cognition=cognition,
        speech=speech,
        self_share_enabled=enabled,
        self_share_per_week=per_week,
        self_share_min_age_days=1,
        self_share_max_age_days=10,
        self_share_setback_days=10,
    )


def _routine(now: datetime) -> RoutineEvent:
    return RoutineEvent(
        key="morning",
        scheduled_at=now.isoformat(timespec="seconds"),
        weight=72,
        window_minutes=60,
    )


def _messages(plan_json: str) -> list[dict]:
    data = json.loads(plan_json)
    return data.get("planned_messages", data.get("messages", []))


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"


def test_picks_recent_shareable_event_within_window() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cognition = _cognition(Path(temp_dir))
        picked = cognition.pick_shareable_event(
            NOW,
            min_age_days=1,
            max_age_days=10,
        )
        assert picked is not None
        # 窗口内最老的优先：4 天前那条
        assert picked["event_id"] == "life_mid"
        assert picked["shareable"] is True


def test_today_and_too_old_events_are_excluded() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cognition = _cognition(Path(temp_dir))
        for _ in range(4):
            picked = cognition.pick_shareable_event(
                NOW,
                min_age_days=1,
                max_age_days=10,
            )
            if picked is None:
                break
            assert picked["event_id"] not in {"life_today", "life_old"}
            cognition.mark_event_shared(str(picked["event_id"]), NOW)


def test_shared_event_is_never_repeated() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cognition = _cognition(Path(temp_dir))
        first = cognition.pick_shareable_event(NOW, min_age_days=1, max_age_days=10)
        assert first is not None
        assert cognition.mark_event_shared(str(first["event_id"]), NOW) is True
        second = cognition.pick_shareable_event(NOW, min_age_days=1, max_age_days=10)
        assert second is not None
        assert second["event_id"] != first["event_id"]
        snapshot = cognition.share_snapshot()
        assert snapshot["shared"] == 1


def test_setback_events_are_rate_limited() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cognition = _cognition(root)
        # 手工把一条 failed_plan 设为刚刚分享过
        path = root / "cognition.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for event in data["life"]["events"]:
            if event["event_id"] == "life_mid":
                event["kind"] = "failed_plan"
                event["shared_at"] = NOW.isoformat(timespec="seconds")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        cognition = CognitiveStateManager(path=path)

        # 再放一条没分享过的 failed_plan
        picked_ids = []
        for _ in range(3):
            picked = cognition.pick_shareable_event(
                NOW,
                min_age_days=1,
                max_age_days=10,
                setback_days=10,
            )
            if picked is None:
                break
            picked_ids.append(picked["event_id"])
            cognition.mark_event_shared(str(picked["event_id"]), NOW)
        assert "life_mid" not in picked_ids


def test_weekly_cap_limits_sharing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state = ProactiveStateStore(path=root / "state.json")
        assert state.self_share_allowed(NOW, per_week=2) is True
        state.record_self_share(NOW)
        state.record_self_share(NOW)
        assert state.self_share_allowed(NOW, per_week=2) is False
        assert state.self_share_allowed(NOW + timedelta(days=8), per_week=2) is True


def test_routine_message_includes_self_share() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cognition = _cognition(root)
        planner = _planner(root, cognition)
        messages = _messages(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert messages
        message = messages[0]
        assert message["metadata"]["self_share"] is True
        assert message["metadata"]["self_share_kind"]
        # 内容里带上了她自己的事
        assert "对了" in message["content"] or message["content"]
        shared = cognition.share_snapshot()
        assert shared["shared"] == 1


def test_disabled_self_share_matches_lv31() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cognition = _cognition(root)
        planner = _planner(root, cognition, enabled=False)
        messages = _messages(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert messages[0]["metadata"]["self_share"] is False
        assert cognition.share_snapshot()["shared"] == 0


def test_no_share_when_no_candidate() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        path = root / "cognition.json"
        path.write_text(
            json.dumps({"schema_version": 22, "life": {"events": []}}),
            encoding="utf-8",
        )
        cognition = CognitiveStateManager(path=path)
        planner = _planner(root, cognition)
        messages = _messages(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert messages[0]["metadata"]["self_share"] is False


def test_world_claim_output_falls_back() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cognition = _cognition(root)
        llm = FixedLLM(["我出门的时候还顺手买了点东西"])
        speech = SpeechComposer(
            llm=llm,
            corpus=CorpusStore(usage_path=root / "usage.json"),
        )
        planner = _planner(root, cognition, speech=speech)
        messages = _messages(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        content = messages[0]["content"]
        assert "我出门" not in content
        assert messages[0]["metadata"]["self_share"] is True


def main() -> None:
    test_version_and_persona()
    test_picks_recent_shareable_event_within_window()
    test_today_and_too_old_events_are_excluded()
    test_shared_event_is_never_repeated()
    test_setback_events_are_rate_limited()
    test_weekly_cap_limits_sharing()
    test_routine_message_includes_self_share()
    test_disabled_self_share_matches_lv31()
    test_no_share_when_no_candidate()
    test_world_claim_output_falls_back()
    print("lv32 self share tests: PASS")


if __name__ == "__main__":
    main()
