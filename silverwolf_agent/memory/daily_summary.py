from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Callable, Any

from ..paths import DAILY_STATE_PATH, ensure_directories
from .rag import JsonlRAGStore
from .short_term import ShortTermMemory
from .profile import UserProfileManager


class DailySummaryManager:
    def __init__(
        self,
        rag: JsonlRAGStore,
        memory: ShortTermMemory,
        profile: UserProfileManager,
        state_path: Path = DAILY_STATE_PATH,
    ) -> None:
        ensure_directories()
        self.rag = rag
        self.memory = memory
        self.profile = profile
        self.state_path = state_path
        if not self.state_path.exists():
            self._write_state({"last_summary_date": None})

    def _read_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"last_summary_date": None}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def should_rollover(self, today: date) -> bool:
        state = self._read_state()
        last = state.get("last_summary_date")
        if not last:
            return False
        return last != today.isoformat()

    def mark_active_date(self, today: date) -> None:
        state = self._read_state()
        if not state.get("last_summary_date"):
            state["last_summary_date"] = today.isoformat()
            self._write_state(state)

    def generate(
        self,
        *,
        target_date: date,
        summarizer: Callable[[str], str],
    ) -> str:
        snapshot = self.memory.snapshot()
        source = {
            "date": target_date.isoformat(),
            "short_summary": snapshot.get("summary", ""),
            "recent_turns": snapshot.get("recent_turns", []),
        }

        if not source["short_summary"] and not source["recent_turns"]:
            summary = f"{target_date.isoformat()}：当天没有可总结的对话。"
        else:
            summary = summarizer(json.dumps(source, ensure_ascii=False)).strip()

        self.rag.add(
            summary,
            metadata={
                "type": "daily_summary",
                "date": target_date.isoformat(),
                "profile_version": self.profile.load().get("schema_version", 3),
            },
            kind="daily_summary",
        )
        self._write_state({"last_summary_date": target_date.isoformat()})
        return summary
