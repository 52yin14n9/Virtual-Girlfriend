from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__  # noqa: E402
from silverwolf_agent.dialogue.corpus import CorpusStore  # noqa: E402
from silverwolf_agent.dialogue.speech import SpeechComposer  # noqa: E402
from silverwolf_agent.dialogue.persona import PersonaLibrary  # noqa: E402
from silverwolf_agent.llm.base import BaseLLMClient  # noqa: E402
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager  # noqa: E402
from silverwolf_agent.models import LLMResponse  # noqa: E402
from silverwolf_agent.paths import PERSONA_PATH  # noqa: E402
from silverwolf_agent.proactive import PlanManager, ProactiveStateStore  # noqa: E402
from silverwolf_agent.proactive.contracts import RoutineEvent, ScheduledPlan  # noqa: E402
from silverwolf_agent.proactive.planner import ProactivePlanner  # noqa: E402

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 8, 5, tzinfo=ZONE)

FORBIDDEN = ("提醒你一下", "我记着呢", "系统", "档案", "存档", "任务已")


class FixedLLM(BaseLLMClient):
    def __init__(self, outputs: list[str], delay: float = 0.0) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.delay = delay

    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        if self.delay:
            time.sleep(self.delay)
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return LLMResponse(text=self.outputs[index])


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


def _speech(root: Path, llm: BaseLLMClient | None, **kwargs) -> SpeechComposer:
    corpus = CorpusStore(usage_path=root / "usage.json")
    return SpeechComposer(llm=llm, corpus=corpus, **kwargs)


def _planner(
    root: Path,
    speech: SpeechComposer | None,
    *,
    speech_enabled: bool = True,
    speech_scenes: tuple[str, ...] = ("morning", "noon", "evening", "callback", "follow_up"),
    speech_max_calls: int = 2,
) -> ProactivePlanner:
    return ProactivePlanner(
        profile=_profile(root),
        memory=ShortTermMemory(path=root / "short.json"),
        state=ProactiveStateStore(path=root / "state.json"),
        speech=speech,
        speech_enabled=speech_enabled,
        speech_scenes=speech_scenes,
        speech_max_calls=speech_max_calls,
        speech_timeout_seconds=1.0,
    )


def _routine(now: datetime) -> RoutineEvent:
    return RoutineEvent(
        key="morning",
        scheduled_at=now.isoformat(timespec="seconds"),
        weight=72,
        window_minutes=60,
    )


def _first_message(plan_json: str) -> dict:
    import json

    data = json.loads(plan_json)
    messages = data.get("planned_messages", data.get("messages", []))
    return messages[0] if messages else {}


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    library = PersonaLibrary()
    assert library.stats()["modules"] >= 9


def test_triggers_extended_for_real_phrasings() -> None:
    library = PersonaLibrary()
    cases = {
        "药还没吃呢": "reminder",
        "现在还差几分": "schedule",
        "连着做几周那种": "commitment",
        "上回说的事": "memory",
    }
    for text, expected in cases.items():
        names = [
            str(item["name"])
            for item in library.select(user_input=text).modules
        ]
        assert expected in names, (text, names)


def test_routine_uses_corpus_speech_when_available() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        speech = _speech(root, FixedLLM(["早，醒了就先喝口水，别急着看消息"]))
        planner = _planner(root, speech)
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert message["content"] == "早，醒了就先喝口水，别急着看消息"
        assert message["metadata"]["speech_source"] == "corpus_llm"
        assert message["metadata"]["selection_mode"] == "corpus_speech"


def test_guard_failure_falls_back_to_template() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        speech = _speech(root, FixedLLM(["提醒你一下，该起床了"]))
        planner = _planner(root, speech)
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert "提醒你一下" not in message["content"]
        assert message["metadata"]["speech_source"].startswith("guard_failed")


def test_timeout_falls_back_within_budget() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        speech = _speech(root, FixedLLM(["这句永远到不了"], delay=3.0))
        planner = _planner(root, speech)
        started = time.monotonic()
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        elapsed = time.monotonic() - started
        assert elapsed < 2.5, elapsed
        assert message["metadata"]["speech_source"] == "timeout"
        assert message["content"]


def test_model_error_falls_back_and_does_not_retry() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        class BoomLLM(BaseLLMClient):
            calls = 0

            def complete(self, *, system, messages, tools=None) -> LLMResponse:
                BoomLLM.calls += 1
                raise RuntimeError("boom")

        speech = _speech(root, BoomLLM())
        planner = _planner(root, speech)
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert message["content"]
        assert BoomLLM.calls <= 2


def test_no_due_messages_means_no_model_call() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = FixedLLM(["不该被调用"])
        speech = _speech(root, llm)
        planner = _planner(root, speech)
        planner.plan_json(now=NOW, routines=[], due_plans=[])
        assert llm.calls == 0


def test_formal_reminder_stays_deterministic() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = FixedLLM(["这句不该出现在正式提醒里"])
        speech = _speech(root, llm)
        planner = _planner(root, speech)
        plan = ScheduledPlan.create(
            title="吃药",
            details="",
            due_at=NOW.isoformat(timespec="seconds"),
            importance=95,
            source_text="提醒我吃药",
        )
        content = planner._render_due_content(
            plan=plan,
            now=NOW,
            casual_alias="宝",
        )
        assert content == "宝，该吃药啦"
        assert llm.calls == 0


def test_relationship_follow_up_is_speech_enabled() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = FixedLLM(["面试那事结束了吧，感觉如何"])
        speech = _speech(root, llm)
        planner = _planner(root, speech)
        plan = ScheduledPlan.create(
            title="面试回访",
            details="",
            due_at=NOW.isoformat(timespec="seconds"),
            importance=78,
            source_text="下午有面试",
            metadata={"kind": "relationship_event_follow_up", "event_label": "面试"},
        )
        content = planner._render_due_content(
            plan=plan,
            now=NOW,
            casual_alias="宝",
        )
        assert "面试" in content
        assert llm.calls == 1


def test_disabled_speech_matches_lv30_behaviour() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = FixedLLM(["不该被调用"])
        speech = _speech(root, llm)
        planner = _planner(root, speech, speech_enabled=False)
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert llm.calls == 0
        assert message["metadata"]["speech_source"] == "template"
        assert message["metadata"]["selection_mode"] == "contextual_template_pool"


def test_scene_filter_limits_speech_usage() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = FixedLLM(["早，先喝口水"])
        speech = _speech(root, llm)
        planner = _planner(root, speech, speech_scenes=("evening",))
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert llm.calls == 0
        assert message["metadata"]["speech_source"] == "template"


def test_offline_mode_produces_no_calls() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        speech = _speech(root, None)
        planner = _planner(root, speech)
        message = _first_message(
            planner.plan_json(now=NOW, routines=[_routine(NOW)], due_plans=[])
        )
        assert message["metadata"]["speech_source"] == "template"
        assert message["content"]


def main() -> None:
    test_version_and_persona()
    test_triggers_extended_for_real_phrasings()
    test_routine_uses_corpus_speech_when_available()
    test_guard_failure_falls_back_to_template()
    test_timeout_falls_back_within_budget()
    test_model_error_falls_back_and_does_not_retry()
    test_no_due_messages_means_no_model_call()
    test_formal_reminder_stays_deterministic()
    test_relationship_follow_up_is_speech_enabled()
    test_disabled_speech_matches_lv30_behaviour()
    test_scene_filter_limits_speech_usage()
    test_offline_mode_produces_no_calls()
    print("lv31 proactive speech tests: PASS")


if __name__ == "__main__":
    main()
