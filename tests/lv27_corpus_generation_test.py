from __future__ import annotations

from datetime import datetime
import json
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
from silverwolf_agent.dialogue.corpus import CorpusStore, overlap_ratio
from silverwolf_agent.dialogue.speech import SpeechComposer
from silverwolf_agent.llm.base import BaseLLMClient
from silverwolf_agent.memory import ShortTermMemory, UserProfileManager
from silverwolf_agent.models import LLMResponse
from silverwolf_agent.pae.planner import ConversationPlanner
from silverwolf_agent.proactive import PlanManager, TimeManager

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 5, 20, 0, tzinfo=ZONE)

FORBIDDEN = (
    "提醒你一下",
    "我记着呢",
    "系统",
    "档案",
    "存档",
    "已创建",
    "任务已",
)


class FixedLLM(BaseLLMClient):
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.last_system = ""

    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        self.last_system = system
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return LLMResponse(text=self.outputs[index])


def _corpus(root: Path) -> CorpusStore:
    return CorpusStore(usage_path=root / "usage.json", cooldown=6)


def test_corpus_files_load_and_cover_scenes() -> None:
    stats = CorpusStore(usage_path=Path(tempfile.gettempdir()) / "lv27_usage_probe.json").stats()
    assert stats["total"] >= 200
    scenes = stats["by_scene"]
    for scene in (
        "commitment_question",
        "commitment_confirm",
        "commitment_due",
        "commitment_finish",
        "commitment_update",
        "reminder_due",
        "schedule_confirm",
        "chat_general",
        "care",
    ):
        assert scenes.get(scene, 0) >= 10, scene


def test_corpus_samples_are_not_repeated_immediately() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        first = corpus.samples("commitment_due", k=3)
        assert len(first) == 3
        corpus.record_use(
            sample_ids=[item.sample_id for item in first],
            text="随便一句已发送的话",
            at=NOW,
        )
        second = corpus.samples("commitment_due", k=3)
        assert first and second
        assert {item.sample_id for item in first}.isdisjoint(
            {item.sample_id for item in second}
        )


def test_overlap_ratio_detects_copying() -> None:
    assert overlap_ratio("周末要过完了该学一会儿了", "周末要过完了该学一会儿了") == 1.0
    assert overlap_ratio("周末要过完了该学一会儿了", "今天下午三点开会记得带电脑") < 0.15


def test_no_llm_uses_deterministic_text() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        composer = SpeechComposer(llm=None, corpus=_corpus(Path(temp_dir)))
        result = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="宝，该创新创业基础的视频学习啦",
        )
        assert result.source == "deterministic"
        assert result.text == "宝，该创新创业基础的视频学习啦"


def test_corpus_rewrite_is_used_when_it_passes_guards() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        llm = FixedLLM(["行，创新创业基础的视频学习时间到了"])
        composer = SpeechComposer(llm=llm, corpus=corpus)
        result = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="宝，该创新创业基础的视频学习啦",
            required_tokens=("创新创业基础的视频学习",),
            at=NOW,
        )
        assert result.source == "corpus_llm"
        assert result.text == "行，创新创业基础的视频学习时间到了"
        assert llm.calls == 1
        # 系统提示里必须带上语料风格与禁止项
        assert "参考语料风格" in llm.last_system
        assert "禁止" in llm.last_system


def test_forbidden_notification_voice_falls_back() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        llm = FixedLLM(["提醒你一下，创新创业基础的视频学习该开始了"])
        composer = SpeechComposer(llm=llm, corpus=corpus)
        result = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="宝，该创新创业基础的视频学习啦",
            required_tokens=("创新创业基础的视频学习",),
            at=NOW,
        )
        assert result.text == "宝，该创新创业基础的视频学习啦"
        assert result.source.startswith("guard_failed")


def test_verbatim_corpus_copy_falls_back() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        sample = corpus.samples("commitment_due", k=1)[0]
        llm = FixedLLM([sample.text])
        composer = SpeechComposer(llm=llm, corpus=corpus)
        result = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="宝，该创新创业基础的视频学习啦",
            at=NOW,
        )
        assert result.text == "宝，该创新创业基础的视频学习啦"


def test_missing_required_fact_falls_back() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        llm = FixedLLM(["到点啦，动起来"])
        composer = SpeechComposer(llm=llm, corpus=corpus)
        result = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="宝，该创新创业基础的视频学习啦",
            required_tokens=("创新创业基础的视频学习",),
            at=NOW,
        )
        assert result.text == "宝，该创新创业基础的视频学习啦"
        assert "missing_token" in result.source


def test_repeated_identical_output_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        corpus = _corpus(Path(temp_dir))
        llm = FixedLLM(["行，创新创业基础的视频学习时间到了"])
        composer = SpeechComposer(llm=llm, corpus=corpus)
        first = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="兜底文案A",
            required_tokens=("创新创业基础的视频学习",),
            at=NOW,
        )
        assert first.source == "corpus_llm"
        second = composer.compose(
            scene="commitment_due",
            facts={"title": "创新创业基础的视频学习"},
            fallback="兜底文案B",
            required_tokens=("创新创业基础的视频学习",),
            at=NOW,
        )
        assert second.text == "兜底文案B"


def test_planner_routes_commitment_to_local_single_message() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        default_profile = root / "default_user_profile.json"
        shutil.copy2(
            PROJECT_ROOT / "config" / "default_user_profile.json",
            default_profile,
        )
        plan_manager = PlanManager(path=root / "plans.json")
        service = CommitmentService(
            plan_manager=plan_manager,
            store=CommitmentStore(root / "commitments.json"),
            clarify_store=ClarificationStore(root / "clarify.json"),
        )
        planner = ConversationPlanner(
            profile=UserProfileManager(
                path=root / "profile.json",
                default_path=default_profile,
            ),
            memory=ShortTermMemory(path=root / "short.json"),
            time_manager=TimeManager(timezone="Asia/Shanghai", path=root / "time.json"),
            plan_manager=plan_manager,
            message_gap_seconds=0.0,
            schedule_judge=None,
            commitment_service=service,
        )

        plan = planner.plan(
            "我以后每周的周末打算完成创新创业基础的视频学习",
            NOW,
        )
        kinds = [goal.kind for goal in plan.response_goals]
        assert "commitment_clarify_question" in kinds
        assert "confirm_schedule" not in kinds
        assert plan.render_mode == "local"
        assert plan.delivery_policy.maximum_messages == 1
        payload = plan.metadata["commitment"]
        assert payload["scene"] == "commitment_question"
        assert payload["fallback_text"]
        # 澄清阶段绝不能偷偷建计划
        assert plan_manager.list_plans(active_only=True) == []

        confirm = planner.plan("这周开始，周六十点，先来八周", NOW)
        kinds = [goal.kind for goal in confirm.response_goals]
        assert "confirm_commitment" in kinds
        assert confirm.metadata["commitment"]["scene"] == "commitment_confirm"
        assert confirm.delivery_policy.maximum_messages == 1
        assert len(plan_manager.list_plans(active_only=True)) > 0


def test_prompt_builder_injects_style_block() -> None:
    from silverwolf_agent.prompts import PromptBuilder

    builder = PromptBuilder()
    plain = builder.pae_executor_prompt(
        now=NOW,
        execution_packet_json="{}",
    )
    styled = builder.pae_executor_prompt(
        now=NOW,
        execution_packet_json="{}",
        style_block="- 周末要过完了",
    )
    assert "语气参考" not in plain
    assert "语气参考" in styled
    assert "周末要过完了" in styled
    assert "Lv27 长期承诺" in styled


def main() -> None:
    test_corpus_files_load_and_cover_scenes()
    test_corpus_samples_are_not_repeated_immediately()
    test_overlap_ratio_detects_copying()
    test_no_llm_uses_deterministic_text()
    test_corpus_rewrite_is_used_when_it_passes_guards()
    test_forbidden_notification_voice_falls_back()
    test_verbatim_corpus_copy_falls_back()
    test_missing_required_fact_falls_back()
    test_repeated_identical_output_is_rejected()
    test_planner_routes_commitment_to_local_single_message()
    test_prompt_builder_injects_style_block()
    print("lv27 corpus generation tests: PASS")


if __name__ == "__main__":
    main()
