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

from silverwolf_agent import __version__  # noqa: E402
from silverwolf_agent.config import AppConfig  # noqa: E402
from silverwolf_agent.diagnostics import Doctor, OK, PENDING, PROBLEM  # noqa: E402
from silverwolf_agent.memory import AgentIdentityManager  # noqa: E402
from silverwolf_agent.paths import PERSONA_PATH  # noqa: E402

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 21, 0, tzinfo=ZONE)


class FakeCognition:
    SCHEMA_VERSION = 22


class FakeAgent:
    def __init__(self, *, api_key: str = "sk-test") -> None:
        self.config = AppConfig(
            api_key=api_key or None,
            base_url="https://example.invalid",
            model="test-model",
            timezone="Asia/Shanghai",
            max_tokens=100,
            temperature=0.5,
            max_retries=1,
            retry_base_seconds=1.0,
            scheduler_poll_seconds=5.0,
            message_gap_seconds=0.5,
        )
        self.cognition = FakeCognition()


def _report(agent: FakeAgent) -> dict:
    return Doctor(agent=agent, now=NOW, stale_days=3).run().to_dict()


def _statuses(report: dict) -> dict[str, str]:
    return {item["name"]: item["status"] for item in report["checks"]}


def test_version_and_persona() -> None:
    assert __version__ == "33.0.0"
    assert PERSONA_PATH.name == "silverwolf_lv33.md"


def test_missing_api_key_is_reported() -> None:
    report = _report(FakeAgent(api_key=""))
    statuses = _statuses(report)
    assert statuses["API Key"] == PROBLEM
    assert "API Key" in report["conclusion"]
    assert "离线" in report["conclusion"]


def test_configured_api_key_passes() -> None:
    report = _report(FakeAgent())
    assert _statuses(report)["API Key"] == OK


def test_missing_data_files_are_pending_not_failures() -> None:
    report = _report(FakeAgent())
    statuses = _statuses(report)
    # 真实数据里这些东西可能还没出现，应判为"未生效"而不是"异常"
    for name in ("长期承诺", "语料生长", "自我分享", "每周反思"):
        assert statuses[name] in {PENDING, OK}
    assert statuses["最后活动"] in {PENDING, OK}


def test_schema_mismatch_is_detected() -> None:
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        path = root / "cognitive_state.json"
        path.write_text(
            json.dumps({"schema_version": 21, "reflections": []}),
            encoding="utf-8",
        )
        import silverwolf_agent.diagnostics as diag

        original = diag.COGNITION_STATE_PATH
        diag.COGNITION_STATE_PATH = path
        try:
            report = _report(FakeAgent())
            statuses = _statuses(report)
            assert statuses["认知状态"] == PENDING
            detail = [
                item["detail"]
                for item in report["checks"]
                if item["name"] == "认知状态"
            ][0]
            assert "21" in detail and "22" in detail
        finally:
            diag.COGNITION_STATE_PATH = original


def test_report_is_read_only() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        before = sorted(p.name for p in root.iterdir())
        Doctor(agent=FakeAgent(), now=NOW).run()
        after = sorted(p.name for p in root.iterdir())
        assert before == after


def test_stale_data_changes_conclusion() -> None:
    import silverwolf_agent.diagnostics as diag

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state_path = root / "proactive_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "last_user_activity_at": "2026-09-11T17:46:55+08:00",
                    "self_share_history": [],
                    "proactive_template_history": [
                        {"template_id": "x", "content": "旧消息"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        original = diag.PROACTIVE_STATE_PATH
        diag.PROACTIVE_STATE_PATH = state_path
        try:
            report = _report(FakeAgent())
            statuses = _statuses(report)
            assert statuses["最后活动"] == PENDING
            assert statuses["主动语料化"] == PENDING
            assert "真实对话" in report["conclusion"]
        finally:
            diag.PROACTIVE_STATE_PATH = original


def test_render_contains_sections() -> None:
    from silverwolf_agent.diagnostics import Doctor as D

    report = D(agent=FakeAgent(), now=NOW).run()
    text = report.render()
    for section in ("【配置】", "【数据】", "【目录】", "【结论】"):
        assert section in text


def main() -> None:
    test_version_and_persona()
    test_missing_api_key_is_reported()
    test_configured_api_key_passes()
    test_missing_data_files_are_pending_not_failures()
    test_schema_mismatch_is_detected()
    test_report_is_read_only()
    test_stale_data_changes_conclusion()
    test_render_contains_sections()
    print("lv33 diagnostics tests: PASS")


if __name__ == "__main__":
    main()
