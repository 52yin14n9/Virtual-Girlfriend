from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.clean_history import HistoryCleaner, backup_data  # noqa: E402

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=ZONE)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build(root: Path) -> Path:
    data = root / "data"
    (data / "rag").mkdir(parents=True, exist_ok=True)
    docs = [
        {"id": "a", "text": "第一天的总结（短）", "metadata": {"date": "2026-09-01"}, "created_at": "2026-09-01T22:00:00"},
        {"id": "b", "text": "第一天的总结（长一些，信息更多）", "metadata": {"date": "2026-09-01"}, "created_at": "2026-09-01T23:00:00"},
        {"id": "c", "text": "", "metadata": {"date": "2026-09-02"}, "created_at": "2026-09-02T22:00:00"},
        {"id": "d", "text": "第二天的总结", "metadata": {"date": "2026-09-03"}, "created_at": "2026-09-03T22:00:00"},
    ]
    (data / "rag" / "documents.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
        encoding="utf-8",
    )
    _write(
        data / "memory" / "short_term.json",
        {
            "recent_turns": [
                {"user": "", "assistant": "主动消息", "user_at": "2026-09-11T12:00:00"},
                {"user": "在干嘛", "assistant": "折腾脚本", "user_at": "2026-09-11T13:00:00"},
            ],
            "summary": "旧的压缩摘要",
        },
    )
    _write(
        data / "scheduler" / "scheduled_plans.json",
        {
            "schema_version": 1,
            "plans": [
                {"plan_id": "old", "title": "提醒睡觉", "status": "pending", "due_at": "2026-09-05T23:30:00+08:00"},
                {"plan_id": "future", "title": "吃药", "status": "pending", "due_at": "2026-12-01T09:00:00+08:00"},
                {"plan_id": "done", "title": "取快递", "status": "completed", "due_at": "2026-08-19T08:00:00+08:00"},
            ],
        },
    )
    _write(
        data / "scheduler" / "proactive_state.json",
        {
            "schema_version": 7,
            "last_user_activity_at": "2026-09-11T17:46:55+08:00",
            "proactive_template_history": [{"template_id": "x"}, {"template_id": "y"}],
            "engagement": {"relationship_sent": 99, "replies_after_proactive": 53, "consecutive_unanswered": 0},
            "routine_sent": {"morning": "2026-09-11"},
        },
    )
    _write(
        data / "cognition" / "cognitive_state.json",
        {
            "schema_version": 22,
            "relationship_state": {
                "interaction_count": 178,
                "familiarity": 1.0,
                "trust": 0.58,
            },
            "life": {
                "events": [
                    {"event_id": "life_1", "kind": "gaming", "summary": "打了几局游戏", "shareable": True, "shared_at": None}
                ]
            },
            "reflections": [],
        },
    )
    _write(data / "profile" / "user_profile.json", {"schema_version": 19, "stable": {"identity": "大学生"}})
    return data


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_dry_run_does_not_modify_anything() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data = _build(Path(temp_dir))
        before = {
            str(p): p.read_bytes()
            for p in data.rglob("*")
            if p.is_file()
        }
        report = HistoryCleaner(data_dir=data, apply=False, now=NOW).run()
        after = {
            str(p): p.read_bytes()
            for p in data.rglob("*")
            if p.is_file()
        }
        assert before == after, "dry-run 不允许改任何文件"
        assert report["details"]["rag_empty_removed"] == 1
        assert report["details"]["rag_duplicate_removed"] == 1
        assert report["details"]["short_term_empty_user_turns"] == 1
        assert report["details"]["plans_expired_cancelled"] == 1


def test_apply_cleans_noise_and_keeps_useful_memory() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data = _build(Path(temp_dir))
        HistoryCleaner(data_dir=data, apply=True, now=NOW).run()

        lines = [
            json.loads(line)
            for line in (data / "rag" / "documents.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 2, lines
        # 同一天保留信息量更大的那条
        assert lines[0]["text"] == "第一天的总结（长一些，信息更多）"
        assert lines[1]["text"] == "第二天的总结"

        short = _load(data / "memory" / "short_term.json")
        assert short["recent_turns"] == []
        assert short["summary"] == ""

        plans = {p["plan_id"]: p for p in _load(data / "scheduler" / "scheduled_plans.json")["plans"]}
        assert plans["old"]["status"] == "cancelled"
        assert plans["old"]["metadata"]["cleanup_reason"] == "expired_before_cleanup"
        assert plans["future"]["status"] == "pending", "未来计划不能被误取消"
        assert plans["done"]["status"] == "completed"

        state = _load(data / "scheduler" / "proactive_state.json")
        assert state["proactive_template_history"] == []
        assert state["last_user_activity_at"] is None
        assert state["engagement"]["relationship_sent"] == 0

        cog = _load(data / "cognition" / "cognitive_state.json")
        assert cog["relationship_state"]["interaction_count"] == 0
        assert abs(cog["relationship_state"]["familiarity"] - 0.48) < 1e-6


def test_profile_and_life_events_are_untouched() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data = _build(Path(temp_dir))
        profile_before = (data / "profile" / "user_profile.json").read_bytes()
        cog_before = _load(data / "cognition" / "cognitive_state.json")["life"]

        HistoryCleaner(data_dir=data, apply=True, now=NOW).run()

        assert (data / "profile" / "user_profile.json").read_bytes() == profile_before
        assert _load(data / "cognition" / "cognitive_state.json")["life"] == cog_before


def test_second_run_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data = _build(Path(temp_dir))
        HistoryCleaner(data_dir=data, apply=True, now=NOW).run()
        second = HistoryCleaner(data_dir=data, apply=True, now=NOW).run()
        details = second["details"]
        assert details["rag_empty_removed"] == 0
        assert details["rag_duplicate_removed"] == 0
        assert details["plans_expired_cancelled"] == 0
        assert second["changed_items"] == 0


def test_keep_rag_days_limits_retention() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data = _build(Path(temp_dir))
        cleaner = HistoryCleaner(
            data_dir=data,
            apply=True,
            keep_rag_days=1,
            now=NOW,
        )
        cleaner.run()
        remaining = [
            line
            for line in (data / "rag" / "documents.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # 2026-09-01 / 09-03 都超过 1 天，应被清空
        assert remaining == []


def test_backup_creates_zip_with_data() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data = _build(root)
        target = backup_data(data, root / "bak")
        assert target.exists()
        import zipfile

        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
        assert any("user_profile.json" in name for name in names)


def main() -> None:
    test_dry_run_does_not_modify_anything()
    test_apply_cleans_noise_and_keeps_useful_memory()
    test_profile_and_life_events_are_untouched()
    test_second_run_is_idempotent()
    test_keep_rag_days_limits_retention()
    test_backup_creates_zip_with_data()
    print("lv33 clean history tests: PASS")


if __name__ == "__main__":
    main()
