from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.config import AppConfig
from silverwolf_agent.dialogue import (
    companionship_language_guard,
    infer_semantic_tags,
    relationship_mode_from_cognition,
)
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_PATH
from silverwolf_agent.proactive import ProactiveMessageLibrary
from silverwolf_agent.world import ContextualCareComposer, WeatherSnapshot


ZONE = ZoneInfo("Asia/Shanghai")


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    # Lv30: 人设已拆成核心 + 世界书模块，断言改为在「整份人设」上检查
    persona = PersonaLibrary().full_text()
    assert "陪伴模式与监督模式分流" in persona
    assert "relationship_mode=accountability" not in persona  # prose uses plain mode name
    assert "有进步" in persona
    assert "普通早中晚关心默认发完就自然停住" in persona


def test_production_follow_up_defaults_are_patient() -> None:
    fields = AppConfig.__dataclass_fields__
    assert fields["proactive_follow_up_enabled"].default is False
    assert fields["proactive_follow_up_seconds"].default == 900
    assert fields["proactive_follow_up_expiry_seconds"].default == 3600


def test_management_templates_removed() -> None:
    library = ProactiveMessageLibrary()
    all_text = "\n".join(
        template
        for group in library.ROUTINE_TEMPLATES.values()
        for _template_id, template, _expects_reply in group
    )
    prohibited = (
        "我来检查一下",
        "先汇报一下",
        "跟我汇报",
        "检查点到了",
    )
    for phrase in prohibited:
        assert phrase not in all_text

    follow_up_text = "\n".join(
        template
        for group in library.FOLLOW_UP_TEMPLATES.values()
        for _template_id, template, _expects_reply in group
    )
    for phrase in (
        "两分钟没动静",
        "怎么没回我消息",
        "看见了就回我一声",
        "我还等着听",
        "先告诉我",
    ):
        assert phrase not in follow_up_text


def test_companionship_guard_removes_scoring() -> None:
    source = (
        "去吧去吧，总算动起来了。今天有进步，至少我敲你的时候你还记得自己没吃饭。"
        "乖，吃完跟我说一声，不然我又得怀疑你是不是对着电脑发呆发过头了"
    )
    softened = companionship_language_guard(
        source,
        relationship_mode="companionship",
        user_input="没注意呢，现在就去吃嗷",
    )
    assert softened
    for phrase in ("总算", "有进步", "至少", "跟我说一声", "怀疑"):
        assert phrase not in softened
    assert "吃" in softened


def test_accountability_keeps_permissioned_directness() -> None:
    source = "这次有进步，不用我催就自己去做了"
    kept = companionship_language_guard(
        source,
        relationship_mode="accountability",
        user_input="今天我自己按监督计划完成了",
    )
    assert kept == source
    assert relationship_mode_from_cognition(
        {"intent": {"name": "accountability_support"}}
    ) == "accountability"
    assert relationship_mode_from_cognition(
        {"intent": {"name": "companionship"}}
    ) == "companionship"


def test_semantic_cooling_prefers_different_reaction_shape() -> None:
    library = ProactiveMessageLibrary()
    now = datetime(2026, 8, 18, 12, 10, tzinfo=ZONE)
    choice = library.select_routine(
        key="noon",
        now=now,
        preferred_name="星",
        casual_alias="宝",
        recent_text="上午一直在忙项目",
        recent_template_ids=[],
        recent_semantic_tags=["question"],
    )
    assert choice is not None
    # noon_unfed contains both questions and one-way care. If a question was
    # just used, semantic cooling should choose a non-question when available.
    assert "question" not in choice.semantic_tags
    assert infer_semantic_tags(choice.content) == choice.semantic_tags


def test_weather_is_context_not_bulletin() -> None:
    snapshot = WeatherSnapshot(
        location="南京浦口",
        latitude=32.0,
        longitude=118.7,
        timezone="Asia/Shanghai",
        fetched_at="2026-08-18T08:00:00+08:00",
        forecast_date="2026-08-18",
        condition="小毛毛雨",
        weather_code=51,
        temperature_c=25.2,
        apparent_temperature_c=26.0,
        minimum_temperature_c=25.2,
        maximum_temperature_c=31.9,
        precipitation_probability=54,
        precipitation_sum_mm=0.4,
        maximum_wind_kmh=15.0,
        rain_likely=True,
        severe=False,
    )
    composer = ContextualCareComposer()
    content, metadata = composer.compose(
        base="早，星。醒了吗？",
        routine_key="morning",
        now=datetime(2026, 8, 18, 8, 0, tzinfo=ZONE),
        recent_user_text="",
        weather_result={"available": True, "snapshot": snapshot.to_dict()},
        memory_callback_enabled=False,
        weekend_suggestions_enabled=False,
    )
    assert content.startswith("早，星。")
    assert "南京浦口" in content
    assert "25.2～31.9℃" in content
    assert "带伞" in content
    assert "降雨概率" not in content
    assert metadata["weather_context_included"] is True


def run() -> None:
    test_version_and_persona()
    test_production_follow_up_defaults_are_patient()
    test_management_templates_removed()
    test_companionship_guard_removes_scoring()
    test_accountability_keeps_permissioned_directness()
    test_semantic_cooling_prefers_different_reaction_shape()
    test_weather_is_context_not_bulletin()
    print("lv24_companionship_language_test: OK")


if __name__ == "__main__":
    run()
