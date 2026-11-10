"""Lv29: 语料自我生长（候选采集 → 人工审核 → 转正 → 淘汰）。

三个不可妥协的约束：

1. **默认不生效**：待审候选完全不参与采样，连风格参照都不用；
2. **隐私优先**：语料会进 prompt，命中账号/网络/身份/密钥任一类直接丢弃；
3. **手写基线只读**：`config/corpus/*.jsonl` 永不被本模块修改。

护栏全部是确定性代码——什么能进语料，不能交给模型温度决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any

from ..paths import (
    CORPUS_AUDIT_PATH,
    CORPUS_CANDIDATES_PATH,
    CORPUS_LEARNED_PATH,
    CORPUS_SIGNALS_PATH,
)
from .corpus import CorpusStore, overlap_ratio

# 时间/数字类事实：语料只学语气，事实一律由代码注入
FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d"),
    re.compile(r"[一二三四五六七八九十百]{1,2}\s*[点时]"),
    re.compile(r"第\s*[一二三四五六七八九十\d]+\s*(?:周|次|天)"),
    re.compile(r"[一二三四五六七八九十\d]{1,2}\s*月"),
    re.compile(r"星期[一二三四五六日天]"),
    re.compile(r"周[一二三四五六日天]"),
)

# 隐私：命中即丢弃，审计只记类型
PRIVACY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d{6,}"), "account_number"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "email"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "network_address"),
    (
        re.compile(r"\b[a-z0-9-]+\.(?:com|cn|net|org|io|dev|xyz|top)\b", re.IGNORECASE),
        "network_domain",
    ),
    (
        re.compile(r"(sk-[A-Za-z0-9]{8,}|access[_-]?token|密码|口令|密钥)", re.IGNORECASE),
        "secret",
    ),
    (re.compile(r"(大学|学院|高中|附中|中学|研究院|workplace|公司名)"), "identity_school"),
    (re.compile(r"(?:省|市|区|县).{0,6}(?:路|街|道|小区|号院|号楼)"), "identity_address"),
    (re.compile(r"[\u4e00-\u9fff]{2,4}(?:小区|花园|公寓)"), "identity_address"),
)

TONE_FORBIDDEN: tuple[re.Pattern[str], ...] = (
    re.compile(r"提醒你一下"),
    re.compile(r"我记着呢"),
    re.compile(r"(已创建|已记录|已更新|已同步|创建成功)"),
    re.compile(r"(系统|档案|存档|数据库|任务面板|检测到)"),
    re.compile(r"(作为(?:一个)?AI|我是一个?(?:AI|人工智能|语言模型))"),
    re.compile(r"(请(?:你)?(?:及时|按时)(?:完成|打卡))"),
)

PERSONALITY_FORBIDDEN: tuple[re.Pattern[str], ...] = (
    re.compile(r"(懒|懒惰)"),
    re.compile(r"(没救|废物|没用|无可救药)"),
    re.compile(r"(不自律|没自制力)"),
    re.compile(r"(差劲|一塌糊涂)"),
    re.compile(r"(指望不上|靠不住)"),
    re.compile(r"(拖延症|重度拖延)"),
    re.compile(r"(总是失败|永远做不成)"),
)

SHAPE_FORBIDDEN = re.compile(r"[\n\r\"“”'‘’「」『』《》]")
EMOJI_FORBIDDEN = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]"
)

SENSITIVE_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ONEBOT_ACCESS_TOKEN",
    "MASTER_QQ",
    "QQ_EMERGENCY_TOKEN",
)

PHRASE_MAX_CHARS = 8
PHRASE_SCENES = {"care", "commitment_update"}


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""


class CorpusLearner:
    """候选池 + 已转正池的读写、护栏、审核与淘汰。"""

    def __init__(
        self,
        *,
        corpus: CorpusStore,
        candidates_path: Path | None = None,
        learned_path: Path | None = None,
        audit_path: Path | None = None,
        signals_path: Path | None = None,
        enabled: bool = True,
        learn_from_user: bool = False,
        phrase_mode: bool = False,
        min_chars: int = 5,
        max_chars: int = 30,
        max_overlap: float = 0.35,
        retire_days: int = 90,
        scene_limit: int = 120,
        privacy_filter: bool = True,
        extra_private_terms: tuple[str, ...] | list[str] = (),
        flush_threshold: int = 5,
    ) -> None:
        self.corpus = corpus
        self.candidates_path = candidates_path or CORPUS_CANDIDATES_PATH
        self.learned_path = learned_path or CORPUS_LEARNED_PATH
        self.audit_path = audit_path or CORPUS_AUDIT_PATH
        self.enabled = bool(enabled)
        self.learn_from_user = bool(learn_from_user)
        self.phrase_mode = bool(phrase_mode)
        self.min_chars = max(2, int(min_chars))
        self.max_chars = max(self.min_chars, int(max_chars))
        self.max_overlap = max(0.05, min(0.95, float(max_overlap)))
        self.retire_days = max(7, int(retire_days))
        self.scene_limit = max(10, int(scene_limit))
        self.privacy_filter = bool(privacy_filter)
        self.flush_threshold = max(1, int(flush_threshold))
        # 候选先在内存里攒着，攒够一批再落盘，避免每轮写小文件
        self._pending: list[dict[str, Any]] = []
        # Lv32: 隐式正向信号（只影响 review 排序，绝不自动转正）
        self.signals_path = signals_path or CORPUS_SIGNALS_PATH
        self.private_terms = tuple(
            str(item).strip()
            for item in extra_private_terms
            if str(item).strip() and len(str(item).strip()) >= 4
        )

    # ------------------------------------------------------------------
    # Lv32: 隐式正向信号
    # ------------------------------------------------------------------

    def _read_signals(self) -> dict[str, int]:
        if not self.signals_path.exists():
            return {}
        try:
            data = json.loads(self.signals_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        values: dict[str, int] = {}
        for key, value in data.items():
            try:
                values[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return values

    def _write_signals(self, data: dict[str, int]) -> None:
        try:
            self.signals_path.parent.mkdir(parents=True, exist_ok=True)
            self.signals_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def record_implicit_signal(
        self,
        text: str,
        at: datetime | None = None,
    ) -> bool:
        """她说完话后，用户继续聊且没纠正 → 记一次弱正向。

        注意：用户不回复**不**记任何负面（Lv24 红线），也绝不触发自动转正。
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        data = self._read_signals()
        data[cleaned] = int(data.get(cleaned, 0)) + 1
        if len(data) > 200:
            keep = sorted(data.items(), key=lambda item: -item[1])[:200]
            data = {key: value for key, value in keep}
        self._write_signals(data)
        return True

    def implicit_score(self, text: str) -> int:
        return int(self._read_signals().get((text or "").strip(), 0))

    # ------------------------------------------------------------------
    # 采集
    # ------------------------------------------------------------------

    def consider_assistant_text(
        self,
        text: str,
        *,
        scene: str,
        now: datetime,
        source: str = "assistant",
    ) -> dict[str, Any]:
        """她自己说过的一句话，走完护栏后进入待审池。"""
        return self._consider(text, scene=scene, now=now, source=source)

    def consider_user_text(
        self,
        text: str,
        *,
        scene: str,
        now: datetime,
    ) -> dict[str, Any]:
        """用户的口头表达（默认关闭）。"""
        if not self.learn_from_user:
            return {"accepted": False, "reason": "learn_from_user_disabled"}
        return self._consider(text, scene=scene, now=now, source="user")

    def add_manual(
        self,
        text: str,
        *,
        scene: str,
        now: datetime,
        approve: bool = False,
    ) -> dict[str, Any]:
        result = self._consider(text, scene=scene, now=now, source="manual")
        if approve and result.get("accepted"):
            entry = self.approve(str(result["candidate_id"]), now)
            return {
                "accepted": True,
                "approved": entry is not None,
                "candidate_id": result["candidate_id"],
            }
        return result

    def _consider(
        self,
        text: str,
        *,
        scene: str,
        now: datetime,
        source: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"accepted": False, "reason": "disabled"}

        cleaned = (text or "").strip()
        kind = self._kind_for(cleaned, scene)
        guard = self.guard(cleaned, kind=kind)
        if not guard.ok:
            if guard.reason.startswith("privacy:"):
                self._audit(
                    "privacy_blocked",
                    now,
                    scene=scene,
                    detail=guard.reason,
                )
            return {"accepted": False, "reason": guard.reason}

        existing = {item.get("text") for item in self._read_candidates()}
        existing.update(item.get("text") for item in self._pending)
        existing.update(
            item.text for item in self.corpus.all_samples()
        )
        if cleaned in existing:
            return {"accepted": False, "reason": "duplicate"}

        candidate = {
            "id": f"cand_{uuid.uuid4().hex[:10]}",
            "scene": scene,
            "text": cleaned,
            "kind": kind,
            "source": source,
            "created_at": now.isoformat(timespec="seconds"),
            "status": "pending",
        }
        self._pending.append(candidate)
        if len(self._pending) >= self.flush_threshold:
            self.flush()
        return {
            "accepted": True,
            "candidate_id": candidate["id"],
            "kind": kind,
            "reason": "",
        }

    def flush(self) -> int:
        """把内存里攒着的候选写进 candidates.jsonl。"""
        if not self._pending:
            return 0
        rows = self._read_candidates()
        rows.extend(self._pending)
        self._write_jsonl(self.candidates_path, rows)
        count = len(self._pending)
        self._pending = []
        return count

    def _kind_for(self, text: str, scene: str) -> str:
        if (
            self.phrase_mode
            and scene in PHRASE_SCENES
            and 2 <= len(text) <= PHRASE_MAX_CHARS
        ):
            return "phrase"
        return "style"

    # ------------------------------------------------------------------
    # 护栏
    # ------------------------------------------------------------------

    def guard(self, text: str, *, kind: str = "style") -> GuardResult:
        cleaned = (text or "").strip()
        if not cleaned:
            return GuardResult(False, "empty")

        min_chars = 2 if kind == "phrase" else self.min_chars
        max_chars = PHRASE_MAX_CHARS if kind == "phrase" else self.max_chars
        if len(cleaned) < min_chars:
            return GuardResult(False, "too_short")
        if len(cleaned) > max_chars:
            return GuardResult(False, "too_long")

        if SHAPE_FORBIDDEN.search(cleaned) or EMOJI_FORBIDDEN.search(cleaned):
            return GuardResult(False, "bad_shape")
        if "。" in cleaned[:-1] or "！" in cleaned[:-1] or "？" in cleaned[:-1]:
            return GuardResult(False, "not_single_sentence")

        # 隐私先于事实判断：带号码/地址的句子要记成隐私拦截，便于审计
        privacy = self._privacy_reason(cleaned)
        if privacy:
            return GuardResult(False, f"privacy:{privacy}")

        for pattern in FACT_PATTERNS:
            if pattern.search(cleaned):
                return GuardResult(False, f"contains_fact:{pattern.pattern}")

        for pattern in TONE_FORBIDDEN:
            if pattern.search(cleaned):
                return GuardResult(False, "notification_tone")

        for pattern in PERSONALITY_FORBIDDEN:
            if pattern.search(cleaned):
                return GuardResult(False, "personality_label")

        for sample in self.corpus.all_samples():
            if overlap_ratio(cleaned, sample.text) > self.max_overlap:
                return GuardResult(False, "too_close_to_corpus")

        return GuardResult(True, "")

    def _privacy_reason(self, text: str) -> str:
        if not self.privacy_filter:
            return ""
        for pattern, label in PRIVACY_PATTERNS:
            if pattern.search(text):
                return label
        lowered = text.lower()
        for term in self._private_terms():
            if term and term.lower() in lowered:
                return "env_secret"
        return ""

    def _private_terms(self) -> tuple[str, ...]:
        values = list(self.private_terms)
        for key in SENSITIVE_ENV_KEYS:
            value = (os.getenv(key) or "").strip()
            if len(value) >= 4:
                values.append(value)
        return tuple(dict.fromkeys(values))

    # ------------------------------------------------------------------
    # 审核
    # ------------------------------------------------------------------

    def review(self, limit: int = 10) -> list[dict[str, Any]]:
        """待审列表：隐式正向信号高的排前面（只排序，不等于转正）。"""
        self.flush()
        rows = [
            item
            for item in self._read_candidates()
            if item.get("status", "pending") == "pending"
        ]
        signals = self._read_signals()
        if signals:
            rows.sort(
                key=lambda item: (
                    int(signals.get(str(item.get("text", "")), 0)),
                    str(item.get("created_at", "")),
                ),
                reverse=True,
            )
        else:
            rows = rows[-max(1, int(limit)) :]
        return rows[: max(1, int(limit))]

    def approve(
        self,
        candidate_id: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        self.flush()
        rows = self._read_candidates()
        target = next(
            (
                item
                for item in rows
                if item.get("id") == candidate_id
                and item.get("status", "pending") == "pending"
            ),
            None,
        )
        if target is None:
            return None
        target["status"] = "approved"
        target["approved_at"] = now.isoformat(timespec="seconds")
        self._write_jsonl(self.candidates_path, rows)

        entry = {
            "id": f"learned_{uuid.uuid4().hex[:10]}",
            "scene": target.get("scene", "chat_general"),
            "text": target.get("text", ""),
            "kind": target.get("kind", "style"),
            "source": target.get("source", "assistant"),
            "approved_at": now.isoformat(timespec="seconds"),
            "use_count": 0,
            "last_used_at": "",
            "retired": False,
        }
        learned = self._read_learned()
        learned.append(entry)
        self._write_jsonl(self.learned_path, learned)
        self._audit("approved", now, entry_id=entry["id"], scene=entry["scene"])
        self.corpus.reload()
        return entry

    def reject(self, candidate_id: str, now: datetime) -> bool:
        self.flush()
        rows = self._read_candidates()
        changed = False
        for item in rows:
            if item.get("id") != candidate_id:
                continue
            if item.get("status", "pending") != "pending":
                continue
            item["status"] = "rejected"
            item["rejected_at"] = now.isoformat(timespec="seconds")
            changed = True
        if changed:
            self._write_jsonl(self.candidates_path, rows)
            self._audit("rejected", now, entry_id=candidate_id)
        return changed

    def reject_text(self, text: str, now: datetime) -> bool:
        """「别这样说」：按文本匹配待审候选或已转正条目。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        self.flush()
        rows = self._read_candidates()
        changed = False
        for item in rows:
            if (
                item.get("text") == cleaned
                and item.get("status", "pending") == "pending"
            ):
                item["status"] = "rejected"
                item["rejected_at"] = now.isoformat(timespec="seconds")
                changed = True
        if changed:
            self._write_jsonl(self.candidates_path, rows)

        learned = self._read_learned()
        retired = False
        for entry in learned:
            if entry.get("text") != cleaned or entry.get("retired"):
                continue
            entry["retired"] = True
            entry["retired_at"] = now.isoformat(timespec="seconds")
            entry["retire_reason"] = "user_rejected"
            retired = True
        if retired:
            self._write_jsonl(self.learned_path, learned)
            self.corpus.reload()

        if changed or retired:
            self._audit("user_rejected", now)
        return changed or retired

    def retire(self, entry_id: str, now: datetime) -> bool:
        learned = self._read_learned()
        changed = False
        for entry in learned:
            if entry.get("id") != entry_id or entry.get("retired"):
                continue
            entry["retired"] = True
            entry["retired_at"] = now.isoformat(timespec="seconds")
            entry["retire_reason"] = "manual"
            changed = True
        if changed:
            self._write_jsonl(self.learned_path, learned)
            self._audit("retired", now, entry_id=entry_id)
            self.corpus.reload()
        return changed

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def maintain(self, now: datetime) -> dict[str, int]:
        """淘汰长期未用的条目，并按 scene 上限裁剪。"""
        if not self.enabled:
            return {"retired": 0, "trimmed": 0}
        self.flush()
        learned = self._read_learned()
        retired_count = 0
        for entry in learned:
            if entry.get("retired"):
                continue
            if int(entry.get("use_count", 0) or 0) >= 3:
                continue
            last = entry.get("last_used_at") or entry.get("approved_at") or ""
            try:
                moment = datetime.fromisoformat(str(last))
            except ValueError:
                continue
            if moment.tzinfo is None and now.tzinfo is not None:
                moment = moment.replace(tzinfo=now.tzinfo)
            if now - moment > timedelta(days=self.retire_days):
                entry["retired"] = True
                entry["retired_at"] = now.isoformat(timespec="seconds")
                entry["retire_reason"] = "stale"
                retired_count += 1

        alive: dict[str, list[dict[str, Any]]] = {}
        for entry in learned:
            if entry.get("retired"):
                continue
            alive.setdefault(str(entry.get("scene", "")), []).append(entry)

        trimmed = 0
        for scene, items in alive.items():
            if len(items) <= self.scene_limit:
                continue
            items.sort(
                key=lambda item: (
                    int(item.get("use_count", 0) or 0),
                    str(item.get("last_used_at", "")),
                )
            )
            for entry in items[: len(items) - self.scene_limit]:
                entry["retired"] = True
                entry["retired_at"] = now.isoformat(timespec="seconds")
                entry["retire_reason"] = "scene_limit"
                trimmed += 1

        if retired_count or trimmed:
            self._write_jsonl(self.learned_path, learned)
            self._audit(
                "maintenance",
                now,
                detail=f"retired={retired_count};trimmed={trimmed}",
            )
            self.corpus.reload()
        return {"retired": retired_count, "trimmed": trimmed}

    def record_use(self, entry_id: str, now: datetime) -> None:
        learned = self._read_learned()
        changed = False
        for entry in learned:
            if entry.get("id") != entry_id:
                continue
            entry["use_count"] = int(entry.get("use_count", 0) or 0) + 1
            entry["last_used_at"] = now.isoformat(timespec="seconds")
            changed = True
        if changed:
            self._write_jsonl(self.learned_path, learned)

    # ------------------------------------------------------------------
    # 查询与统计
    # ------------------------------------------------------------------

    def list_learned(
        self,
        scene: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = [
            item
            for item in self._read_learned()
            if not item.get("retired")
            and (scene is None or item.get("scene") == scene)
        ]
        return rows[-max(1, int(limit)) :]

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        candidates = self._read_candidates()
        pending = [
            item for item in candidates if item.get("status", "pending") == "pending"
        ]
        pending_count = len(pending) + len(self._pending)
        learned = self._read_learned()
        active = [item for item in learned if not item.get("retired")]
        by_scene: dict[str, int] = {}
        for item in active:
            key = str(item.get("scene", ""))
            by_scene[key] = by_scene.get(key, 0) + 1
        return {
            "enabled": self.enabled,
            "learn_from_user": self.learn_from_user,
            "phrase_mode": self.phrase_mode,
            "pending_candidates": pending_count,
            "learned_active": len(active),
            "learned_retired": len(learned) - len(active),
            "learned_by_scene": by_scene,
            "handwritten": self.corpus.stats().get("handwritten", 0),
            "retire_days": self.retire_days,
            "scene_limit": self.scene_limit,
        }

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "stats": self.stats(now),
            "recent_candidates": self.review(limit=3),
        }

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------

    def _read_candidates(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.candidates_path)

    def _read_learned(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.learned_path)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    def _audit(self, kind: str, now: datetime, **extra: Any) -> None:
        """审计只记类型与场合，绝不记原句。"""
        record = {
            "type": kind,
            "at": now.isoformat(timespec="seconds"),
        }
        record.update({key: value for key, value in extra.items() if value is not None})
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
