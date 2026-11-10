"""Lv27: 把"确定性事实 + 语料库风格"合成为一句话。

调用方只提供：

* `scene`    场景（到点提醒 / 计划确认 / 澄清追问 / 开课播报 …）
* `facts`    已经算死的事实（几点、第几周、一共几周）
* `fallback` 确定性兜底文案

本模块负责尝试用模型按语料风格重写，并在任何一个护栏不通过时
安全回退到 `fallback`。**事实永远不会由模型重新计算。**
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
import re

from ..llm import BaseLLMClient, EchoLLMClient, LLMServiceError
from ..models import ChatMessage
from .corpus import CorpusSample, CorpusStore, overlap_ratio


@dataclass(frozen=True)
class SpeechResult:
    text: str
    source: str
    samples: tuple[str, ...] = ()


class SpeechComposer:
    """语料驱动的话术合成器（带确定性兜底）。"""

    FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"提醒你一下"),
        re.compile(r"我记着呢"),
        re.compile(r"(已创建|创建成功|已记录|已更新|已入库)"),
        re.compile(r"(系统|档案|存档|数据库|任务面板)"),
        re.compile(r"(检测到|根据用户档案|指令已接收)"),
        re.compile(r"(计划已|任务已)"),
        re.compile(r"(作为(一个)?AI|我是一个?(AI|人工智能|语言模型))"),
        re.compile(r"(请(你)?(及时|按时)(完成|打卡))"),
    )

    def __init__(
        self,
        *,
        llm: BaseLLMClient | None = None,
        corpus: CorpusStore | None = None,
        enabled: bool = True,
        max_overlap: float = 0.35,
        samples: int = 3,
        max_chars: int = 90,
        phrase_mode: bool = False,
    ) -> None:
        self.llm = llm
        self.corpus = corpus or CorpusStore()
        self.enabled = bool(enabled)
        self.max_overlap = max(0.05, min(0.95, float(max_overlap)))
        self.samples = max(0, int(samples))
        self.max_chars = max(20, int(max_chars))
        # Lv29: 语气片段原样复用，默认关闭
        self.phrase_mode = bool(phrase_mode)

    PHRASE_SCENES = {"care", "commitment_update"}

    # ------------------------------------------------------------------

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self.llm is None or isinstance(self.llm, EchoLLMClient):
            return False
        return True

    def compose_bounded(
        self,
        *,
        timeout_seconds: float = 8.0,
        **kwargs: object,
    ) -> SpeechResult:
        """Lv31: 带硬超时的合成。

        主动消息生成发生在调度循环里，绝不能被模型拖死：
        超时或异常时立即返回确定性兜底文案，并标记来源。
        """
        fallback_text = str(kwargs.get("fallback", "") or "").strip()
        if not self.available() or timeout_seconds <= 0:
            return self.compose(**kwargs)  # type: ignore[arg-type]

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self.compose, **kwargs)  # type: ignore[arg-type]
            return future.result(timeout=float(timeout_seconds))
        except FutureTimeout:
            return SpeechResult(text=fallback_text, source="timeout")
        except Exception:  # noqa: BLE001 - 兜底文案永远可用
            return SpeechResult(text=fallback_text, source="error")
        finally:
            pool.shutdown(wait=False)

    def maybe_phrase(
        self,
        scene: str,
        *,
        at: datetime | None = None,
    ) -> "SpeechResult | None":
        """取一条已转正的语气片段原样使用（phrase 模式）。"""
        if not self.phrase_mode or not self.enabled:
            return None
        try:
            samples = self.corpus.samples(
                scene,
                k=1,
                kind="phrase",
            )
        except Exception:  # noqa: BLE001 - 语气片段是可选增强
            return None
        if not samples:
            return None
        sample = samples[0]
        try:
            self.corpus.record_use(
                sample_ids=[sample.sample_id],
                text=sample.text,
                at=at,
            )
        except Exception:  # noqa: BLE001
            pass
        return SpeechResult(
            text=sample.text,
            source="phrase_reuse",
            samples=(sample.sample_id,),
        )

    def compose(
        self,
        *,
        scene: str,
        facts: dict[str, object],
        fallback: str,
        required_tokens: tuple[str, ...] | list[str] = (),
        max_chars: int | None = None,
        relation_mode: str = "companionship",
        tags: tuple[str, ...] | list[str] = (),
        at: datetime | None = None,
        samples: int | None = None,
    ) -> SpeechResult:
        fallback_text = (fallback or "").strip()
        sample_count = self.samples if samples is None else max(0, int(samples))

        # Lv29: phrase 模式（默认关闭）。只有 ≤8 字的语气片段允许原样复用，
        # 且仍然受冷却与"最近不重复"约束。
        if self.phrase_mode and scene in self.PHRASE_SCENES:
            reused = self.maybe_phrase(scene, at=at)
            if reused is not None:
                return reused

        if not self.available():
            return SpeechResult(text=fallback_text, source="deterministic")

        exemplars = self.corpus.samples(
            scene,
            tags=tags,
            k=sample_count,
            relation_mode=relation_mode,
        )
        if not exemplars:
            return SpeechResult(text=fallback_text, source="no_corpus")

        candidate = self._generate(
            scene=scene,
            facts=facts,
            exemplars=exemplars,
            fallback=fallback_text,
            relation_mode=relation_mode,
        )
        if not candidate:
            return SpeechResult(text=fallback_text, source="generation_failed")

        limit = max_chars or self.max_chars
        problem = self._validate(
            candidate,
            scene=scene,
            required_tokens=required_tokens,
            max_chars=limit,
        )
        if problem:
            # 一次严格重试：把失败原因明确写进指令，减少"照着语料抄"。
            candidate = self._generate(
                scene=scene,
                facts=facts,
                exemplars=exemplars,
                fallback=fallback_text,
                relation_mode=relation_mode,
                strict_reason=problem,
            )
            if not candidate or self._validate(
                candidate,
                scene=scene,
                required_tokens=required_tokens,
                max_chars=limit,
            ):
                return SpeechResult(text=fallback_text, source=f"guard_failed:{problem}")

        self.corpus.record_use(
            sample_ids=[sample.sample_id for sample in exemplars],
            text=candidate,
            at=at,
        )
        return SpeechResult(
            text=candidate,
            source="corpus_llm",
            samples=tuple(sample.sample_id for sample in exemplars),
        )

    # ------------------------------------------------------------------

    def _generate(
        self,
        *,
        scene: str,
        facts: dict[str, object],
        exemplars: list[CorpusSample],
        fallback: str,
        relation_mode: str,
        strict_reason: str = "",
    ) -> str:
        if self.llm is None:
            return ""
        system = self._system_prompt(scene, relation_mode)
        user = self._user_prompt(
            facts=facts,
            exemplars=exemplars,
            fallback=fallback,
            strict_reason=strict_reason,
        )
        try:
            response = self.llm.complete(
                system=system,
                messages=[ChatMessage(role="user", content=user)],
            )
        except (LLMServiceError, ValueError, OSError):
            return ""
        except Exception:  # noqa: BLE001 - 兜底：任何网络/解析异常都不该影响主流程
            return ""
        return self._clean(response.text)

    def _system_prompt(self, scene: str, relation_mode: str) -> str:
        profile = self.corpus.style_profile(scene)
        mode_rule = (
            "当前是普通陪伴关系：不要给用户日常行为打分、不要催促汇报。"
            if relation_mode != "accountability"
            else "当前是用户主动托付的监督关系：可以直接一点，但仍然站在同一侧。"
        )
        return (
            "你负责把已经确定的事实，改写成像熟人随口说出的一句话。\n"
            "硬性要求：\n"
            "1. 只输出这一句话本身，不要解释、不要引号、不要换行、不要表情符号。\n"
            "2. 只能使用给定事实，禁止新增或修改任何时间、数字、次数、周历。\n"
            "3. 不要使用通知腔、系统腔：不要出现“提醒你一下”“我记着呢”“已创建”“系统”“档案”“存档”。\n"
            "4. 不要逐字照抄参考语料，只学它的语气和长度。\n"
            "5. 长度控制在 40 字以内，能短则短，最多一个逗号停顿。\n"
            f"6. {mode_rule}\n"
            f"参考语料风格：{profile}\n"
            f"场景：{scene}"
        )

    def _user_prompt(
        self,
        *,
        facts: dict[str, object],
        exemplars: list[CorpusSample],
        fallback: str,
        strict_reason: str,
    ) -> str:
        fact_lines = "\n".join(
            f"- {key}: {value}"
            for key, value in facts.items()
            if value not in ("", None, [], ())
        )
        samples = "\n".join(
            f"- {sample.text}" for sample in exemplars
        )
        strict = (
            f"\n上一次生成不合格（{strict_reason}），这次务必换一种说法。\n"
            if strict_reason
            else ""
        )
        return (
            f"【必须表达的事实】\n{fact_lines}\n\n"
            f"【参考语料（只学语气，不要照抄）】\n{samples}\n\n"
            f"【确定性版本（意思必须一致）】\n{fallback}\n"
            f"{strict}\n"
            "请输出一句更自然的话。"
        )

    # ------------------------------------------------------------------

    def _validate(
        self,
        text: str,
        *,
        scene: str,
        required_tokens: tuple[str, ...] | list[str],
        max_chars: int,
    ) -> str:
        cleaned = text.strip()
        if not cleaned:
            return "empty"
        if "\n" in cleaned:
            return "multiline"
        if len(cleaned) > max_chars:
            return "too_long"
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.search(cleaned):
                return f"forbidden:{pattern.pattern}"
        normalized = re.sub(r"\s+", "", cleaned)
        for token in required_tokens:
            key = re.sub(r"\s+", "", str(token))
            if key and key not in normalized:
                return f"missing_token:{token}"
        # 与整个场景语料比较，而不只是这次抽到的样句，避免"换一批样本就抄"。
        pool = [
            sample
            for sample in self.corpus.all_samples()
            if sample.scene == scene
        ] or self.corpus.all_samples()
        for sample in pool:
            if overlap_ratio(cleaned, sample.text) > self.max_overlap:
                return "too_close_to_corpus"
        for recent in self.corpus.recent_texts(limit=6):
            if re.sub(r"\s+", "", recent) == normalized:
                return "duplicate_recent"
        return ""

    @staticmethod
    def _clean(text: str) -> str:
        value = (text or "").strip()
        value = value.strip("\"'“”「」『』`")
        value = re.sub(r"^[\-\*\d.、\s]+", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    # ------------------------------------------------------------------

    def style_block(
        self,
        scene: str,
        *,
        tags: tuple[str, ...] | list[str] = (),
        k: int = 2,
        relation_mode: str = "companionship",
    ) -> str:
        """给普通聊天 Prompt 用的风格锚点（只注入少量样句）。"""
        if not self.enabled or k <= 0:
            return ""
        exemplars = self.corpus.samples(
            scene,
            tags=tags,
            k=k,
            relation_mode=relation_mode,
        )
        if not exemplars:
            return ""
        lines = "\n".join(f"- {sample.text}" for sample in exemplars)
        return (
            "以下只是语气参考，学它的句长和口吻，不要照抄，也不要在回复里提到它们：\n"
            f"{lines}"
        )
