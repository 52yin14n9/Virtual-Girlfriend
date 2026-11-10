from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any
import uuid

from ..paths import RAG_PATH, RECALL_STATS_PATH, ensure_directories

# Lv28: 重要度规则。事实性判断必须由确定性代码做，不能交给温度。
IMPORTANCE_BASE = 5
IMPORTANCE_MIN = 1
IMPORTANCE_MAX = 10
DEFAULT_IMPORTANCE = 5

IMPORTANCE_RULES: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (
        re.compile(r"(提醒|计划|日程|每周|每天|坚持|完成|截止|打卡|承诺)"),
        2,
        "含承诺或计划",
    ),
    (
        re.compile(
            r"(我(?:的)?生日|我是|我姓|我叫|我住在|我在读|我学|我专业|我讨厌|我喜欢|我不吃|我过敏|我对.{0,8}过敏)"
        ),
        2,
        "用户明确自述",
    ),
    (
        re.compile(r"(累|困|失眠|睡不好|难受|头疼|胃疼|焦虑|开心|高兴|难过|压力|崩溃)"),
        1,
        "含情绪或身体状态",
    ),
    (
        re.compile(r"(\d{1,2}\s*月|星期[一二三四五六日天]|周[一二三四五六日天]|今天|明天|后天|下周|昨天)"),
        1,
        "含具体时间",
    ),
)


def score_importance(text: str) -> tuple[int, str]:
    """按确定性规则给一条记忆打 1–10 分，并返回命中原因。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return DEFAULT_IMPORTANCE, "空文本按基线"

    score = IMPORTANCE_BASE
    reasons: list[str] = []
    for pattern, bonus, reason in IMPORTANCE_RULES:
        if pattern.search(cleaned):
            score += bonus
            reasons.append(reason)
    score = max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, score))
    return score, "、".join(reasons) or "基线"


@dataclass
class RAGDocument:
    id: str
    text: str
    metadata: dict[str, Any]
    created_at: str

    @property
    def importance(self) -> int:
        raw = self.metadata.get("importance", DEFAULT_IMPORTANCE)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_IMPORTANCE
        return max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, value))


class JsonlRAGStore:
    """零依赖的轻量 RAG。

    Lv28 起：检索不再只看词面重合，而是把「重要度」和「遗忘曲线」一起算进来。
    - 重要的事衰减慢；
    - 被回忆起过的事衰减更慢（复习效应）；
    - `decay_enabled=False` 时退回 Lv27 的纯词法排序。
    """

    def __init__(
        self,
        path: Path = RAG_PATH,
        *,
        stats_path: Path | None = None,
        decay_enabled: bool = True,
        weight_relevance: float = 0.55,
        weight_importance: float = 0.25,
        weight_recency: float = 0.20,
        stability_base_days: float = 14.0,
    ) -> None:
        ensure_directories()
        self.path = path
        self.path.touch(exist_ok=True)
        self.stats_path = stats_path or (
            RECALL_STATS_PATH
            if path == RAG_PATH
            else path.with_name("recall_stats.json")
        )
        self.decay_enabled = bool(decay_enabled)
        total = max(
            0.0001,
            float(weight_relevance) + float(weight_importance) + float(weight_recency),
        )
        # 归一化，避免配置写错导致分数尺度漂移
        self.weight_relevance = float(weight_relevance) / total
        self.weight_importance = float(weight_importance) / total
        self.weight_recency = float(weight_recency) / total
        self.stability_base_days = max(1.0, float(stability_base_days))

    # ---------- 写入 ----------

    def add(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        *,
        kind: str = "",
        importance: int | None = None,
    ) -> RAGDocument:
        payload = dict(metadata or {})
        if kind and "kind" not in payload:
            payload["kind"] = kind
        if importance is None:
            score, reason = score_importance(text)
            payload.setdefault("importance", score)
            payload.setdefault("importance_reason", reason)
        else:
            payload["importance"] = max(
                IMPORTANCE_MIN,
                min(IMPORTANCE_MAX, int(importance)),
            )
            payload.setdefault("importance_reason", "调用方指定")

        doc = RAGDocument(
            id=str(uuid.uuid4()),
            text=text.strip(),
            metadata=payload,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(doc), ensure_ascii=False) + "\n")
        return doc

    def all(self) -> list[RAGDocument]:
        docs: list[RAGDocument] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                docs.append(RAGDocument(**item))
            except (json.JSONDecodeError, TypeError):
                continue
        return docs

    # ---------- 召回统计 ----------

    def _read_stats(self) -> dict[str, dict[str, Any]]:
        if not self.stats_path.exists():
            return {}
        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_stats(self, data: dict[str, dict[str, Any]]) -> None:
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            self.stats_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def recall_stats(self) -> dict[str, dict[str, Any]]:
        return self._read_stats()

    def recall_count(self, doc_id: str) -> int:
        item = self._read_stats().get(doc_id, {})
        try:
            return int(item.get("count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def mark_recalled(
        self,
        doc_ids: list[str] | tuple[str, ...],
        at: datetime | None = None,
    ) -> None:
        """被检索到 = 被复习一次，衰减变慢。"""
        ids = [str(item) for item in doc_ids if str(item)]
        if not ids:
            return
        moment = (at or datetime.now()).isoformat(timespec="seconds")
        data = self._read_stats()
        for doc_id in ids:
            item = data.get(doc_id)
            if not isinstance(item, dict):
                item = {"count": 0, "last_at": ""}
            try:
                item["count"] = int(item.get("count", 0) or 0) + 1
            except (TypeError, ValueError):
                item["count"] = 1
            item["last_at"] = moment
            data[doc_id] = item
        self._write_stats(data)

    # ---------- 检索 ----------

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = re.sub(r"\s+", "", text.lower())
        latin = set(re.findall(r"[a-z0-9_]+", normalized))
        chinese_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
        unigrams = set(chinese_chars)
        bigrams = {
            chinese_chars[index] + chinese_chars[index + 1]
            for index in range(len(chinese_chars) - 1)
        }
        return latin | unigrams | bigrams

    def _relevance(self, query_tokens: set[str], doc_tokens: set[str]) -> float:
        overlap = query_tokens & doc_tokens
        if not overlap:
            return 0.0
        precision = len(overlap) / max(1, len(query_tokens))
        density = len(overlap) / math.sqrt(max(1, len(doc_tokens)))
        return min(1.0, precision * 0.8 + density * 0.2)

    def _stability_days(self, importance: int, recall_count: int) -> float:
        return (
            self.stability_base_days
            + 6.0 * importance
            + 4.0 * min(max(0, recall_count), 5)
        )

    def _recency(
        self,
        doc: RAGDocument,
        *,
        now: datetime,
        importance: int,
        recall_count: int,
    ) -> float:
        try:
            created = datetime.fromisoformat(doc.created_at)
        except (TypeError, ValueError):
            return 0.5
        if created.tzinfo is None and now.tzinfo is not None:
            created = created.replace(tzinfo=now.tzinfo)
        age_days = max(0.0, (now - created).total_seconds() / 86400.0)
        stability = self._stability_days(importance, recall_count)
        return math.exp(-age_days / stability)

    def search_scored(
        self,
        query: str,
        top_k: int = 4,
        *,
        now: datetime | None = None,
    ) -> list[tuple[RAGDocument, dict[str, float]]]:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []

        moment = now or datetime.now()
        stats = self._read_stats() if self.decay_enabled else {}
        scored: list[tuple[float, RAGDocument, dict[str, float]]] = []

        for doc in self.all():
            relevance = self._relevance(query_tokens, self._tokens(doc.text))
            if relevance <= 0:
                continue
            importance = doc.importance
            if not self.decay_enabled:
                scored.append(
                    (
                        relevance,
                        doc,
                        {
                            "relevance": round(relevance, 4),
                            "importance": float(importance),
                            "recency": 1.0,
                            "final": round(relevance, 4),
                        },
                    )
                )
                continue

            item = stats.get(doc.id, {})
            try:
                recall_count = int(item.get("count", 0) or 0)
            except (TypeError, ValueError):
                recall_count = 0
            importance_norm = (importance - 1) / 9.0
            recency = self._recency(
                doc,
                now=moment,
                importance=importance,
                recall_count=recall_count,
            )
            final = (
                self.weight_relevance * relevance
                + self.weight_importance * importance_norm
                + self.weight_recency * recency
            )
            scored.append(
                (
                    final,
                    doc,
                    {
                        "relevance": round(relevance, 4),
                        "importance": float(importance),
                        "recency": round(recency, 4),
                        "recall_count": float(recall_count),
                        "final": round(final, 4),
                    },
                )
            )

        scored.sort(key=lambda entry: entry[0], reverse=True)
        return [
            (doc, detail)
            for _, doc, detail in scored[: max(1, int(top_k))]
        ]

    def search(
        self,
        query: str,
        top_k: int = 4,
        *,
        now: datetime | None = None,
    ) -> list[RAGDocument]:
        return [
            doc
            for doc, _ in self.search_scored(query, top_k=top_k, now=now)
        ]

    # ---------- 调试 ----------

    def stats(self) -> dict[str, Any]:
        docs = self.all()
        stats = self._read_stats()
        by_kind: dict[str, int] = {}
        importance_total = 0
        for doc in docs:
            kind = str(
                doc.metadata.get("kind")
                or doc.metadata.get("type")
                or "unknown"
            )
            by_kind[kind] = by_kind.get(kind, 0) + 1
            importance_total += doc.importance
        return {
            "documents": len(docs),
            "by_kind": by_kind,
            "average_importance": (
                round(importance_total / len(docs), 2) if docs else 0.0
            ),
            "recalled_documents": len(
                [key for key in stats if stats[key].get("count")]
            ),
            "decay_enabled": self.decay_enabled,
            "weights": {
                "relevance": round(self.weight_relevance, 3),
                "importance": round(self.weight_importance, 3),
                "recency": round(self.weight_recency, 3),
            },
        }
