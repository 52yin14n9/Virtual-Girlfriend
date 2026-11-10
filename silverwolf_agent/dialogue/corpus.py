"""Lv27: 语料库（corpus）引擎。

设计目标很明确：**不要每次都从同一批模板里挑句子。**

语料库保存的是"人怎么说话"的样本，不是可以直接发给用户的成品：

* 生成时只取少量样句作风格参照（few-shot）；
* 生成结果必须与样句保持足够距离，禁止逐字照抄；
* 用过的样句进入冷却，短期内不再重复出现；
* 一切事实（时间、周次、次数）仍来自确定性代码。

语料文件位于 `config/corpus/*.jsonl`，一行一条：

    {"id": "...", "scene": "...", "text": "...",
     "semantic_tags": ["..."], "relation_mode": "companionship",
     "register": "casual", "notes": "..."}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from ..paths import CORPUS_DIR, CORPUS_USAGE_PATH


@dataclass(frozen=True)
class CorpusSample:
    sample_id: str
    scene: str
    text: str
    semantic_tags: tuple[str, ...] = ()
    relation_mode: str = "companionship"
    register: str = "casual"
    notes: str = ""
    # Lv29: style 只做风格参照；phrase 是 ≤8 字语气片段
    kind: str = "style"
    # Lv29: handwritten（我写的基线）/ learned（她学会的）
    source: str = "handwritten"


@dataclass
class CorpusStats:
    total: int = 0
    by_scene: dict[str, int] = field(default_factory=dict)
    source_files: int = 0


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _ngrams(text: str, size: int = 3) -> set[str]:
    cleaned = _normalize(text)
    if len(cleaned) < size:
        return {cleaned} if cleaned else set()
    return {
        cleaned[index : index + size]
        for index in range(len(cleaned) - size + 1)
    }


def overlap_ratio(left: str, right: str, *, size: int = 3) -> float:
    """字符 3-gram 的 Jaccard 相似度，用来判断"是不是在照抄语料"。"""
    left_set = _ngrams(left, size)
    right_set = _ngrams(right, size)
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    if union == 0:
        return 0.0
    return intersection / union


class CorpusStore:
    """负责加载、采样、冷却和重叠检测。"""

    # Lv29: 这两个文件由 CorpusLearner 管理，不属于手写基线
    RESERVED_FILES = {"candidates.jsonl", "learned.jsonl"}

    def __init__(
        self,
        *,
        corpus_dir: Path | None = None,
        usage_path: Path | None = None,
        cooldown: int = 8,
        enabled: bool = True,
        learned_path: Path | None = None,
        learned_share: float = 0.3,
    ) -> None:
        self.corpus_dir = corpus_dir or CORPUS_DIR
        self.usage_path = usage_path or CORPUS_USAGE_PATH
        self.learned_path = learned_path or (
            self.corpus_dir / "learned.jsonl"
        )
        self.cooldown = max(1, int(cooldown))
        self.learned_share = max(0.0, min(0.9, float(learned_share)))
        self.enabled = bool(enabled)
        self._samples: list[CorpusSample] = []
        self._loaded = False

    # ---------- 加载 ----------

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.corpus_dir.exists():
            return
        # Lv29: 手写基线（永远只读）。candidates / learned 是另一个池子，
        # 只有 approved 的 learned 才允许参与采样。
        for path in sorted(self.corpus_dir.glob("*.jsonl")):
            if path.name in self.RESERVED_FILES:
                continue
            self._load_lines(path, source="handwritten")
        self._load_lines(self.learned_path, source="learned")

    def _load_lines(self, path: Path, *, source: str) -> None:
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if source == "learned" and isinstance(item, dict) and item.get("retired"):
                continue
            sample = self._parse_sample(item, path.stem)
            if sample is not None:
                self._samples.append(
                    CorpusSample(
                        sample_id=sample.sample_id,
                        scene=sample.scene,
                        text=sample.text,
                        semantic_tags=sample.semantic_tags,
                        relation_mode=sample.relation_mode,
                        register=sample.register,
                        notes=sample.notes,
                        kind=sample.kind,
                        source=source,
                    )
                )

    def _parse_sample(
        self,
        item: object,
        fallback_id: str,
    ) -> CorpusSample | None:
        if not isinstance(item, dict):
            return None
        text = str(item.get("text", "")).strip()
        if not text:
            return None
        tags_raw = item.get("semantic_tags", [])
        tags: tuple[str, ...] = ()
        if isinstance(tags_raw, (list, tuple)):
            tags = tuple(str(tag) for tag in tags_raw if str(tag).strip())
        return CorpusSample(
            sample_id=str(item.get("id", "") or fallback_id).strip(),
            scene=str(item.get("scene", "") or fallback_id).strip(),
            text=text,
            semantic_tags=tags,
            relation_mode=str(item.get("relation_mode", "companionship")).strip(),
            register=str(item.get("register", "casual")).strip(),
            notes=str(item.get("notes", "")).strip(),
            kind=str(item.get("kind", "style") or "style").strip(),
        )

    def reload(self) -> None:
        self._samples = []
        self._loaded = False
        self.ensure_loaded()

    # ---------- 查询 ----------

    def all_samples(self) -> list[CorpusSample]:
        self.ensure_loaded()
        return list(self._samples)

    def stats(self) -> dict[str, object]:
        self.ensure_loaded()
        by_scene: dict[str, int] = {}
        learned = 0
        phrases = 0
        for sample in self._samples:
            by_scene[sample.scene] = by_scene.get(sample.scene, 0) + 1
            if sample.source == "learned":
                learned += 1
            if sample.kind == "phrase":
                phrases += 1
        files = (
            len(list(self.corpus_dir.glob("*.jsonl")))
            if self.corpus_dir.exists()
            else 0
        )
        return {
            "enabled": self.enabled,
            "total": len(self._samples),
            "by_scene": by_scene,
            "source_files": files,
            "cooldown": self.cooldown,
            "learned": learned,
            "handwritten": len(self._samples) - learned,
            "phrase_entries": phrases,
            "learned_share": self.learned_share,
        }

    def samples(
        self,
        scene: str,
        *,
        tags: tuple[str, ...] | list[str] = (),
        k: int = 3,
        relation_mode: str = "",
        exclude_recent: bool = True,
        kind: str = "",
    ) -> list[CorpusSample]:
        self.ensure_loaded()
        if k <= 0 or not self._samples:
            return []

        wanted = {str(tag) for tag in tags if str(tag).strip()}
        recent = set(self.recent_ids()) if exclude_recent else set()

        def score(sample: CorpusSample) -> tuple[int, int, str]:
            tag_hit = len(wanted & set(sample.semantic_tags))
            mode_hit = 1 if (relation_mode and sample.relation_mode == relation_mode) else 0
            bucket = 0 if sample.sample_id in recent else 1
            digest = sha256(
                f"{scene}|{sample.sample_id}".encode("utf-8")
            ).hexdigest()
            return (bucket, tag_hit * 2 + mode_hit, digest)

        pool = [
            sample
            for sample in self._samples
            if sample.scene == scene and (not kind or sample.kind == kind)
        ]
        if not pool:
            return []
        ranked = sorted(pool, key=score, reverse=True)
        selected = ranked[:k]
        return self._balance_learned(selected, ranked, k)

    def _balance_learned(
        self,
        selected: list[CorpusSample],
        ranked: list[CorpusSample],
        k: int,
    ) -> list[CorpusSample]:
        """Lv29: 学来的条目不能挤掉手写基线。

        一次采样里 learned 最多占 round(k * share) 个（至少 1），
        超出的用同场景手写条目替换。
        """
        allowed = max(1, int(round(k * self.learned_share)))
        picked = list(selected)
        learned_count = len([item for item in picked if item.source == "learned"])
        if learned_count <= allowed:
            return picked

        replacements = [
            item
            for item in ranked
            if item.source != "learned" and item not in picked
        ]
        result: list[CorpusSample] = []
        kept_learned = 0
        for item in picked:
            if item.source != "learned":
                result.append(item)
                continue
            if kept_learned < allowed:
                result.append(item)
                kept_learned += 1
                continue
            if replacements:
                result.append(replacements.pop(0))
        return result[:k]

    def recent_ids(self) -> list[str]:
        data = self._read_usage()
        history = data.get("history", [])
        if not isinstance(history, list):
            return []
        values = [
            str(item.get("sample_id", ""))
            for item in history
            if isinstance(item, dict)
        ]
        return [value for value in values if value][-self.cooldown :]

    def recent_texts(self, limit: int = 6) -> list[str]:
        data = self._read_usage()
        history = data.get("sent", [])
        if not isinstance(history, list):
            return []
        values = [
            str(item.get("text", ""))
            for item in history
            if isinstance(item, dict)
        ]
        return [value for value in values if value][-max(1, limit) :]

    def record_use(
        self,
        *,
        sample_ids: list[str] | tuple[str, ...],
        text: str,
        at: datetime | None = None,
    ) -> None:
        moment = (at or datetime.now()).isoformat(timespec="seconds")
        data = self._read_usage()
        history = [
            item
            for item in data.get("history", [])
            if isinstance(item, dict)
        ]
        for sample_id in sample_ids:
            if not sample_id:
                continue
            history.append({"sample_id": sample_id, "at": moment})
        data["history"] = history[-50:]

        sent = [item for item in data.get("sent", []) if isinstance(item, dict)]
        if text.strip():
            sent.append({"text": text.strip(), "at": moment})
        data["sent"] = sent[-20:]
        self._write_usage(data)

    def style_profile(self, scene: str) -> str:
        """把语料库里的共性提炼成风格指令，供模型参考。"""
        samples = [item for item in self.all_samples() if item.scene == scene]
        if not samples:
            samples = self.all_samples()
        if not samples:
            return ""

        lengths = [len(_normalize(item.text)) for item in samples]
        average = sum(lengths) / max(1, len(lengths))
        shortest = min(lengths)
        longest = max(lengths)
        return (
            f"该场景语料共 {len(samples)} 条，句长多在 {shortest}–{longest} 字，"
            f"平均 {average:.0f} 字；整体口语、短句、少修饰、"
            "不用通知腔和系统腔，也不要每条都追问。"
        )

    # ---------- 使用记录 ----------

    def _read_usage(self) -> dict[str, object]:
        if not self.usage_path.exists():
            return {"history": [], "sent": []}
        try:
            data = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {"history": [], "sent": []}
        if not isinstance(data, dict):
            return {"history": [], "sent": []}
        data.setdefault("history", [])
        data.setdefault("sent", [])
        return data

    def _write_usage(self, data: dict[str, object]) -> None:
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            self.usage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
