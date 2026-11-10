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

from silverwolf_agent.cognition import CognitiveStateManager

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 8, 0, tzinfo=ZONE)


def _cognition(root: Path, events: list[dict] | None = None) -> CognitiveStateManager:
    path = root / "cognition.json"
    payload = {
        "schema_version": 22,
        "life": {
            "last_advanced_date": NOW.date().isoformat(),
            "events": events or [],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return CognitiveStateManager(path=path)


def _event(
    event_id: str,
    *,
    days_ago: int,
    kind: str,
    shared_at: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "date": (NOW - timedelta(days=days_ago)).date().isoformat(),
        "kind": kind,
        "summary": f"{kind} 的一条记录",
        "detail": "",
        "shareable": True,
        "shared_at": shared_at,
        "continuity_scope": "persona_offscreen_life",
    }


def test_catalog_has_24_kinds() -> None:
    catalog = CognitiveStateManager.LIFE_CATALOG
    assert len(catalog) >= 24
    kinds = {item[0] for item in catalog}
    assert len(kinds) >= 24
    for kind, summary, detail in catalog:
        assert kind.strip()
        assert len(summary) >= 8
        assert summary != detail
        # 不含阿拉伯数字（避免被当成真实世界事实）
        assert not any(ch.isdigit() for ch in summary)
        assert not any(ch.isdigit() for ch in detail)


def test_life_events_use_the_wider_catalog() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cognition = _cognition(root)
        kinds = set()
        for offset in range(24):
            day = NOW.date() + timedelta(days=offset)
            event = cognition._build_life_event(day)
            kinds.add(event["kind"])
        # 24 天里应覆盖到远多于原来的 5 种
        assert len(kinds) >= 10


def test_kind_cooldown_blocks_recently_shared_kind() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        events = [
            _event("g1", days_ago=5, kind="gaming"),
            _event("g2", days_ago=4, kind="gaming"),
            _event("m1", days_ago=4, kind="music"),
            _event(
                "g0",
                days_ago=6,
                kind="gaming",
                shared_at=(NOW - timedelta(days=2)).isoformat(timespec="seconds"),
            ),
        ]
        cognition = _cognition(root, events)
        picked = cognition.pick_shareable_event(
            NOW,
            min_age_days=1,
            max_age_days=10,
            kind_cooldown_days=30,
        )
        assert picked is not None
        # gaming 刚讲过（2 天前），冷却 30 天 → 只能选 music
        assert picked["kind"] == "music"


def test_kind_cooldown_zero_restores_old_behaviour() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        events = [
            _event("g1", days_ago=5, kind="gaming"),
            _event("m1", days_ago=4, kind="music"),
        ]
        cognition = _cognition(root, events)
        picked = cognition.pick_shareable_event(
            NOW,
            min_age_days=1,
            max_age_days=10,
            kind_cooldown_days=0,
        )
        assert picked is not None
        # 没有冷却时回到 Lv32 行为：最老优先
        assert picked["event_id"] == "g1"


def test_kind_cooldown_respects_last_shared_kind_even_when_disabled() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        events = [
            _event("g1", days_ago=5, kind="gaming"),
            _event("m1", days_ago=4, kind="music"),
            _event(
                "g0",
                days_ago=6,
                kind="gaming",
                shared_at=(NOW - timedelta(days=2)).isoformat(timespec="seconds"),
            ),
        ]
        cognition = _cognition(root, events)
        picked = cognition.pick_shareable_event(
            NOW,
            min_age_days=1,
            max_age_days=10,
            kind_cooldown_days=0,
        )
        assert picked is not None
        # 关闭冷却也不允许和上一条同类连发（Lv32 规则仍在）
        assert picked["kind"] == "music"


def test_shared_events_still_never_repeat() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        events = [_event("a", days_ago=3, kind="music")]
        cognition = _cognition(root, events)
        first = cognition.pick_shareable_event(NOW, min_age_days=1, max_age_days=10)
        assert first is not None
        cognition.mark_event_shared(str(first["event_id"]), NOW)
        assert cognition.pick_shareable_event(NOW, min_age_days=1, max_age_days=10) is None


def main() -> None:
    test_catalog_has_24_kinds()
    test_life_events_use_the_wider_catalog()
    test_kind_cooldown_blocks_recently_shared_kind()
    test_kind_cooldown_zero_restores_old_behaviour()
    test_kind_cooldown_respects_last_shared_kind_even_when_disabled()
    test_shared_events_still_never_repeat()
    print("lv33 life template tests: PASS")


if __name__ == "__main__":
    main()
