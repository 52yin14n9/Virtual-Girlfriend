"""Lv28: 每周反思。

把"流水账式记忆"变成"她对这段时间的理解"。三条硬规则：

1. **证据强制**：没有真实 doc_id 支撑的判断直接丢弃，宁可少不可编；
2. **禁词过滤**：任何负面定性（懒、没救、不自律…）一律丢弃；
3. **永不主动播报**：反思只影响她怎么想，不直接说出口（Lv24 的底线）。

离线时退化为统计式反思：只写 reflections，不写 beliefs。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import re
from typing import Any

from ..llm import BaseLLMClient, EchoLLMClient, LLMServiceError
from ..models import ChatMessage
from .rag import RAGDocument

BANNED_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(懒|懒惰)"),
    re.compile(r"(没救|废物|没用|无可救药)"),
    re.compile(r"(不自律|没自制力|自我管理差)"),
    re.compile(r"(差劲|糟糕透顶|一塌糊涂)"),
    re.compile(r"(指望不上|靠不住)"),
    re.compile(r"(拖延症|重度拖延)"),
    re.compile(r"(总是失败|永远做不成)"),
)


@dataclass(frozen=True)
class ReflectionResult:
    ran: bool
    trigger: str
    source: str
    week_summary: str = ""
    observations: tuple[dict[str, Any], ...] = ()
    open_threads: tuple[str, ...] = ()
    dropped: int = 0
    evidence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "trigger": self.trigger,
            "source": self.source,
            "week_summary": self.week_summary,
            "observations": list(self.observations),
            "open_threads": list(self.open_threads),
            "dropped": self.dropped,
            "evidence_count": self.evidence_count,
        }


@dataclass
class _Draft:
    week_summary: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    tone_notes: str = ""
    milestones: list[str] = field(default_factory=list)


class ReflectionEngine:
    def __init__(
        self,
        *,
        rag: Any,
        cognition: Any,
        memory: Any = None,
        commitment_store: Any = None,
        llm: BaseLLMClient | None = None,
        enabled: bool = True,
        weekday: int = 6,
        hour: int = 21,
        importance_threshold: int = 150,
        max_evidence: int = 12,
    ) -> None:
        self.rag = rag
        self.cognition = cognition
        self.memory = memory
        self.commitment_store = commitment_store
        self.llm = llm
        self.enabled = bool(enabled)
        self.weekday = max(0, min(6, int(weekday)))
        self.hour = max(0, min(23, int(hour)))
        self.importance_threshold = max(20, int(importance_threshold))
        self.max_evidence = max(3, int(max_evidence))

    # ------------------------------------------------------------------
    # 触发
    # ------------------------------------------------------------------

    def _last_run(self) -> datetime | None:
        meta = self.cognition.reflection_snapshot()
        raw = meta.get("last_run_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None

    def due(self, now: datetime) -> str:
        """返回本次触发原因；空字符串表示不该跑。"""
        if not self.enabled:
            return ""

        last = self._last_run()
        if last is not None:
            if last.tzinfo is None and now.tzinfo is not None:
                last = last.replace(tzinfo=now.tzinfo)
            # 一天最多一次
            if last.date() == now.date():
                return ""

        if now.weekday() == self.weekday and now.hour >= self.hour:
            return "weekly"

        weekly_importance = self._weekly_importance(now)
        if weekly_importance >= self.importance_threshold:
            return "threshold"
        return ""

    def _weekly_importance(self, now: datetime) -> int:
        total = 0
        for doc in self._recent_documents(now):
            total += doc.importance
        return total

    def _recent_documents(self, now: datetime) -> list[RAGDocument]:
        try:
            docs = self.rag.all()
        except Exception:  # noqa: BLE001 - 反思失败不该影响主链路
            return []
        window_start = now - timedelta(days=7)
        recent: list[RAGDocument] = []
        for doc in docs:
            try:
                created = datetime.fromisoformat(doc.created_at)
            except (TypeError, ValueError):
                continue
            if created.tzinfo is None and now.tzinfo is not None:
                created = created.replace(tzinfo=now.tzinfo)
            if created >= window_start:
                recent.append(doc)
        return recent

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run(
        self,
        now: datetime,
        *,
        trigger: str = "",
        force: bool = False,
    ) -> ReflectionResult:
        reason = trigger or self.due(now)
        if not reason:
            if not force:
                return ReflectionResult(ran=False, trigger="", source="not_due")
            reason = "manual"

        evidence = sorted(
            self._recent_documents(now),
            key=lambda doc: (-doc.importance, doc.created_at),
        )[: self.max_evidence]
        threads = self._open_threads()

        if not evidence and not threads:
            return ReflectionResult(ran=False, trigger=reason, source="no_data")

        if self._llm_available():
            draft = self._draft_with_llm(evidence, threads, now)
            source = "llm"
        else:
            draft = None
            source = ""

        if draft is None:
            draft = self._draft_statistical(evidence, threads, now)
            source = "statistical"

        observations, dropped = self._filter_observations(
            draft.observations,
            valid_ids={doc.id for doc in evidence},
        )

        payload = {
            "week_summary": draft.week_summary,
            "observations": observations,
            "open_threads": draft.open_threads or threads,
            "tone_notes": draft.tone_notes,
            "milestones": draft.milestones,
            "trigger": reason,
            "source": source,
            "created_at": now.isoformat(timespec="seconds"),
        }
        # 离线统计式反思只留记录，不写 beliefs（避免用模板生成"理解"）
        self.cognition.record_reflection(
            payload,
            now,
            trigger=reason,
            apply_beliefs=(source == "llm"),
        )

        if draft.week_summary:
            try:
                self.rag.add(
                    draft.week_summary,
                    metadata={
                        "type": "reflection",
                        "week_of": now.date().isoformat(),
                        "evidence_count": len(evidence),
                    },
                    kind="reflection",
                    importance=8,
                )
            except Exception:  # noqa: BLE001
                pass

        return ReflectionResult(
            ran=True,
            trigger=reason,
            source=source,
            week_summary=draft.week_summary,
            observations=tuple(observations),
            open_threads=tuple(draft.open_threads or threads),
            dropped=dropped,
            evidence_count=len(evidence),
        )

    # ------------------------------------------------------------------
    # 取证
    # ------------------------------------------------------------------

    def _open_threads(self) -> list[str]:
        threads: list[str] = []
        store = self.commitment_store
        if store is None:
            return threads
        try:
            for item in store.active()[:4]:
                remaining = item.remaining_weeks()
                threads.append(
                    f"{item.title}（还剩 {remaining} 周）"
                )
        except Exception:  # noqa: BLE001
            return []
        return threads

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------

    def _llm_available(self) -> bool:
        return self.llm is not None and not isinstance(self.llm, EchoLLMClient)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你在整理一段陪伴关系里这一周的记忆。\n"
            "硬性要求：\n"
            "1. 只输出合法 JSON，不要 Markdown，不要解释。\n"
            "2. 每条 observation 必须带 evidence_doc_ids，且只能引用【证据】里出现的 id。\n"
            "3. 禁止对用户做负面人格定性（懒、没救、不自律、拖延症、差劲等）。\n"
            "4. 不确定就少写，不要为了凑数编造。\n"
            "5. 这是内部整理，不会直接说给用户听；不要写成安慰或对话。\n"
            "JSON 结构："
            '{"week_summary":"一句话概括这周","observations":'
            '[{"claim":"对她的判断","confidence":0.6,"evidence_doc_ids":["id"]}],'
            '"open_threads":["还没结束的事"],"tone_notes":"这周该注意的语气","milestones":["值得记住的一件事"]}'
        )

    def _draft_with_llm(
        self,
        evidence: list[RAGDocument],
        threads: list[str],
        now: datetime,
    ) -> _Draft | None:
        if self.llm is None:
            return None
        lines = [
            f"[{doc.id}] ({doc.created_at[:10]} 重要度{doc.importance}) {doc.text[:200]}"
            for doc in evidence
        ]
        user = (
            f"本周时间：{now.date().isoformat()}\n\n"
            "【证据】\n"
            + ("\n".join(lines) if lines else "（本周没有记录）")
            + "\n\n【未完成的事】\n"
            + ("\n".join(f"- {item}" for item in threads) if threads else "（无）")
        )
        try:
            response = self.llm.complete(
                system=self._system_prompt(),
                messages=[ChatMessage(role="user", content=user)],
            )
        except (LLMServiceError, ValueError, OSError):
            return None
        except Exception:  # noqa: BLE001
            return None

        data = self._parse_json(getattr(response, "text", ""))
        if data is None:
            return None

        observations: list[dict[str, Any]] = []
        raw_observations = data.get("observations", [])
        if isinstance(raw_observations, list):
            for item in raw_observations:
                if not isinstance(item, dict):
                    continue
                claim = str(item.get("claim", "")).strip()
                evidence_ids = item.get("evidence_doc_ids", [])
                if not claim or not isinstance(evidence_ids, (list, tuple)):
                    continue
                try:
                    confidence = float(item.get("confidence", 0.5))
                except (TypeError, ValueError):
                    confidence = 0.5
                observations.append(
                    {
                        "claim": claim[:80],
                        "confidence": max(0.0, min(0.65, confidence)),
                        "evidence_doc_ids": [str(x) for x in evidence_ids][:6],
                    }
                )

        return _Draft(
            week_summary=str(data.get("week_summary", "")).strip()[:200],
            observations=observations,
            open_threads=[
                str(item).strip()
                for item in data.get("open_threads", [])
                if str(item).strip()
            ][:6]
            if isinstance(data.get("open_threads"), list)
            else [],
            tone_notes=str(data.get("tone_notes", "")).strip()[:120],
            milestones=[
                str(item).strip()
                for item in data.get("milestones", [])
                if str(item).strip()
            ][:4]
            if isinstance(data.get("milestones"), list)
            else [],
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            start = cleaned.find("{")
            if start < 0:
                return None
            try:
                value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None

    def _draft_statistical(
        self,
        evidence: list[RAGDocument],
        threads: list[str],
        now: datetime,
    ) -> _Draft:
        """没有模型时的诚实版本：只说统计，不做判断。"""
        count = len(evidence)
        topics: list[str] = []
        if self.memory is not None:
            try:
                recent = self.memory.recent_user_text(limit=30)
            except Exception:  # noqa: BLE001
                recent = ""
            topics = re.findall(r"[\u4e00-\u9fff]{2,4}", recent[:600])[:40]
        popular: list[str] = []
        for word in topics:
            if topics.count(word) >= 3 and word not in popular:
                popular.append(word)
            if len(popular) >= 3:
                break

        if count:
            summary = f"这周有 {count} 条值得记的事"
        else:
            summary = "这周没有留下明确记录"
        if popular:
            summary += f"，反复出现的是：{'、'.join(popular)}"
        summary += "。"

        return _Draft(
            week_summary=summary,
            observations=[],
            open_threads=list(threads),
            tone_notes="",
            milestones=[],
        )

    # ------------------------------------------------------------------
    # 护栏
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_observations(
        observations: list[dict[str, Any]],
        *,
        valid_ids: set[str],
    ) -> tuple[list[dict[str, Any]], int]:
        kept: list[dict[str, Any]] = []
        dropped = 0
        seen: set[str] = set()
        for item in observations:
            claim = str(item.get("claim", "")).strip()
            evidence = item.get("evidence_doc_ids", [])
            if not claim or claim in seen:
                dropped += 1
                continue
            if not isinstance(evidence, (list, tuple)) or not evidence:
                dropped += 1
                continue
            if not set(str(x) for x in evidence).issubset(valid_ids):
                # 引用了不存在的证据 = 编的
                dropped += 1
                continue
            if any(pattern.search(claim) for pattern in BANNED_CLAIM_PATTERNS):
                dropped += 1
                continue
            seen.add(claim)
            kept.append(
                {
                    "claim": claim,
                    "confidence": item.get("confidence", 0.5),
                    "evidence_doc_ids": [str(x) for x in evidence][:6],
                }
            )
        return kept, dropped

    # ------------------------------------------------------------------

    def snapshot(self, now: datetime) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "due": self.due(now),
            "weekly_importance": self._weekly_importance(now),
            "threshold": self.importance_threshold,
            "schedule": {
                "weekday": self.weekday,
                "hour": self.hour,
            },
            "cognition": self.cognition.reflection_snapshot(),
        }
