from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent import __version__
from silverwolf_agent.dialogue.persona import PersonaLibrary
from silverwolf_agent.paths import PERSONA_MODULES_DIR, PERSONA_PATH
from silverwolf_agent.prompts import PromptBuilder

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 20, 0, tzinfo=ZONE)


def _names(library: PersonaLibrary, text: str) -> list[str]:
    selection = library.select(user_input=text)
    return [str(item["name"]) for item in selection.modules]


def test_version_and_core_file() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"
    assert PERSONA_MODULES_DIR.exists()
    library = PersonaLibrary()
    stats = library.stats()
    assert stats["core_chars"] <= 4000
    assert stats["modules"] >= 9
    assert set(stats["resident"]) == {"relation", "style"}


def test_resident_modules_are_always_injected() -> None:
    library = PersonaLibrary()
    for text in ("今天好累", "晚上提醒我吃药", "", "随便聊聊"):
        names = _names(library, text)
        assert "relation" in names
        assert "style" in names


def test_modules_are_selected_by_trigger() -> None:
    library = PersonaLibrary()
    assert "reminder" in _names(library, "晚上提醒我吃药")
    assert "commitment" in _names(library, "我以后每周的周末要学创新课")
    assert "schedule" in _names(library, "今天星期几")
    assert "identity" in _names(library, "你现在多大了")
    assert "memory" in _names(library, "你还记得我上次说的吗")


def test_chat_does_not_pull_irrelevant_modules() -> None:
    library = PersonaLibrary()
    names = _names(library, "今天好累")
    for unwanted in ("commitment", "schedule", "reminder", "identity"):
        assert unwanted not in names


def test_goals_can_select_modules_without_keywords() -> None:
    library = PersonaLibrary()
    selection = library.select(
        user_input="嗯",
        goal_kinds=("confirm_schedule",),
    )
    names = [str(item["name"]) for item in selection.modules]
    assert "reminder" in names


def test_token_saving_is_real() -> None:
    library = PersonaLibrary()
    full = len(library.full_text())
    casual = library.select(user_input="今天好累").total_chars
    assert casual < full * 0.6, (casual, full)


def test_budget_trims_modules() -> None:
    library = PersonaLibrary(budget_chars=3500)
    selection = library.select(user_input="晚上提醒我吃药")
    assert selection.skipped, "预算不足时必须跳过模块"
    assert selection.total_chars <= library.budget_chars


def test_missing_modules_dir_falls_back_to_core() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        library = PersonaLibrary(modules_dir=Path(temp_dir) / "nope")
        selection = library.select(user_input="提醒我吃药")
        assert selection.fallback == "no_modules"
        assert selection.text
        assert "身份与关系" in selection.text


def test_missing_core_falls_back_to_previous_persona() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        library = PersonaLibrary(core_path=Path(temp_dir) / "missing.md")
        selection = library.select(user_input="今天好累")
        assert selection.text
        # 退回历史整份人设里至少要有身份段
        assert "银狼" in selection.text


def test_no_rule_was_lost_in_the_split() -> None:
    merged = PersonaLibrary().full_text()
    keys = (
        "我是银狼",
        "陪伴模式与监督模式分流",
        "日程创建确认只说一次",
        "Lv27 长期任务承诺",
        "Lv28 记忆与反思",
        "Lv29 语料生长",
        "该睡觉啦",
        "别让快递等你",
    )
    for key in keys:
        assert key in merged, key


def test_prompt_builder_injects_only_needed_modules() -> None:
    builder = PromptBuilder()
    packet = {
        "schema_version": "2.0",
        "plan": {
            "user_input": "晚上提醒我吃药",
            "response_goals": [{"kind": "confirm_schedule"}],
        },
        "tool_results": [],
        "short_memory": "",
        "rag_context": "",
        "profile_context": "",
        "cognition_context": {},
    }
    system = builder.pae_executor_prompt(
        now=NOW,
        execution_packet_json=json.dumps(packet, ensure_ascii=False),
    )
    assert "提醒说话方式" in system          # reminder 模块进来了
    assert "Lv27 长期任务承诺" not in system  # commitment 模块没进来
    selection = builder.last_persona_selection
    assert selection["total_chars"] <= 8000
    assert any(
        item["name"] == "reminder"
        for item in selection["modules"]
    )


def main() -> None:
    test_version_and_core_file()
    test_resident_modules_are_always_injected()
    test_modules_are_selected_by_trigger()
    test_chat_does_not_pull_irrelevant_modules()
    test_goals_can_select_modules_without_keywords()
    test_token_saving_is_real()
    test_budget_trims_modules()
    test_missing_modules_dir_falls_back_to_core()
    test_missing_core_falls_back_to_previous_persona()
    test_no_rule_was_lost_in_the_split()
    test_prompt_builder_injects_only_needed_modules()
    print("lv30 persona layering tests: PASS")


if __name__ == "__main__":
    main()
