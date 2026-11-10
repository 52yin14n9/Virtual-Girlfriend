"""Lv27: 长期承诺与澄清会话的持久化。

沿用项目既有风格：纯 JSON 文件、损坏时回退默认值、schema_version
显式迁移，不引入数据库依赖。
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from ..paths import COMMITMENTS_PATH, COMMITMENT_CLARIFY_PATH
from .contracts import ClarificationSession, Commitment


class CommitmentStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or COMMITMENTS_PATH

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "commitments": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {"schema_version": self.SCHEMA_VERSION, "commitments": []}
        if not isinstance(data, dict):
            return {"schema_version": self.SCHEMA_VERSION, "commitments": []}
        data.setdefault("schema_version", self.SCHEMA_VERSION)
        if not isinstance(data.get("commitments"), list):
            data["commitments"] = []
        return data

    def _write(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- 查询 ----------

    def all(self) -> list[Commitment]:
        data = self._read()
        return [
            Commitment.from_dict(item)
            for item in data.get("commitments", [])  # type: ignore[union-attr]
            if isinstance(item, dict)
        ]

    def active(self) -> list[Commitment]:
        return [item for item in self.all() if item.status == "active"]

    def get(self, commitment_id: str) -> Commitment | None:
        for item in self.all():
            if item.commitment_id == commitment_id:
                return item
        return None

    def find_by_hint(self, text: str) -> Commitment | None:
        """按标题关键词找承诺，用于“把跑步那个取消”。"""
        cleaned = text.strip()
        if not cleaned:
            return None
        candidates = self.active()
        best: Commitment | None = None
        best_score = 0
        for item in candidates:
            score = 0
            if item.title and item.title in cleaned:
                score = len(item.title)
            else:
                for chunk in _title_chunks(item.title):
                    if len(chunk) >= 2 and chunk in cleaned:
                        score = max(score, len(chunk))
            if score > best_score:
                best = item
                best_score = score
        if best is not None:
            return best
        # 只有一个活跃承诺时，带操作语义的句子默认指向它。
        if len(candidates) == 1:
            return candidates[0]
        return None

    # ---------- 写入 ----------

    def save(self, commitment: Commitment) -> Commitment:
        data = self._read()
        rows = [
            item
            for item in data.get("commitments", [])  # type: ignore[union-attr]
            if isinstance(item, dict)
        ]
        payload = commitment.to_dict()
        merged = False
        for index, item in enumerate(rows):
            if item.get("commitment_id") == commitment.commitment_id:
                rows[index] = payload
                merged = True
                break
        if not merged:
            rows.append(payload)
        data["commitments"] = rows
        self._write(data)
        return commitment

    def create(self, commitment: Commitment) -> Commitment:
        return self.save(commitment)

    def cancel(self, commitment_id: str, at: datetime) -> Commitment | None:
        commitment = self.get(commitment_id)
        if commitment is None:
            return None
        commitment.status = "cancelled"
        commitment.metadata["cancelled_at"] = at.isoformat(timespec="seconds")
        return self.save(commitment)

    def finish(self, commitment_id: str, at: datetime) -> Commitment | None:
        commitment = self.get(commitment_id)
        if commitment is None:
            return None
        commitment.status = "finished"
        commitment.metadata["finished_at"] = at.isoformat(timespec="seconds")
        return self.save(commitment)

    def mark_week(self, commitment_id: str, week: int, *, skipped: bool) -> Commitment | None:
        commitment = self.get(commitment_id)
        if commitment is None:
            return None
        week = int(week)
        if skipped:
            if week not in commitment.skipped_weeks:
                commitment.skipped_weeks.append(week)
            if week in commitment.completed_weeks:
                commitment.completed_weeks.remove(week)
        else:
            if week not in commitment.completed_weeks:
                commitment.completed_weeks.append(week)
            if week in commitment.skipped_weeks:
                commitment.skipped_weeks.remove(week)
        commitment.completed_weeks.sort()
        commitment.skipped_weeks.sort()
        return self.save(commitment)

    def snapshot(self) -> dict[str, object]:
        items = self.all()
        return {
            "schema_version": self.SCHEMA_VERSION,
            "count": len(items),
            "active_count": len([item for item in items if item.status == "active"]),
            "commitments": [item.to_dict() for item in items],
        }


class ClarificationStore:
    """同一时间只保存一个进行中的补全会话。"""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or COMMITMENT_CLARIFY_PATH

    def get(self) -> ClarificationSession | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("session")
        if not isinstance(raw, dict):
            return None
        return ClarificationSession.from_dict(raw)

    def save(self, session: ClarificationSession) -> ClarificationSession:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "session": session.to_dict(),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return session

    def clear(self) -> None:
        if not self.path.exists():
            return
        payload = {"schema_version": self.SCHEMA_VERSION, "session": None}
        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


def _title_chunks(title: str) -> list[str]:
    cleaned = title.strip()
    if not cleaned:
        return []
    chunks = [cleaned]
    for part in re_split_chunks(cleaned):
        if part not in chunks:
            chunks.append(part)
    return chunks


def re_split_chunks(title: str) -> list[str]:
    import re

    parts = re.split(r"[的，,、\s]+", title)
    return [part for part in parts if len(part) >= 2]
