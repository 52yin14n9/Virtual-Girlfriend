from __future__ import annotations

import json
import re

from ..llm import BaseLLMClient, EchoLLMClient, LLMServiceError
from ..models import ChatMessage
from .contracts import CompletionDecision


class ResponseCompletionAgent:
    """Judge whether one assistant turn actually finished the user's request.

    The judge is deliberately separate from turn-taking. It never talks to the
    user directly. When it says a response is incomplete, the Executor may ask
    the main chat model for a bounded continuation in the *same* user turn.
    """

    _SUBSTANTIVE_REQUEST = re.compile(
        r"(?:讲|写|找|发|给我|帮我|做|生成|整理|总结|翻译|解释|分析|"
        r"列出|提供|推荐|教我|告诉我|回答|阅读|故事|作文|代码|方案|全文|完整|一次性)"
    )
    _SETUP_ONLY = re.compile(
        r"(?:我(?:来|就|这就|先|给你)|那我|行[，,]?我|好[，,]?我|可以[，,]?我)?"
        r"(?:给你)?(?:讲|写|找|挑|整理|发|做|生成|翻译|解释|列)(?:一个|一篇|一下|给你)?"
    )
    _PROMISE_TAIL = re.compile(
        r"(?:给你讲一个很短的故事|原文和翻译一起发你|一次性到位|下面(?:就)?给你|这就发你|我来给你整理)[~～。.!！]*$"
    )

    def __init__(
        self,
        *,
        llm: BaseLLMClient | None = None,
        enabled: bool = True,
        llm_enabled: bool = True,
        minimum_incomplete_confidence: float = 0.72,
    ) -> None:
        self.llm = llm
        self.enabled = bool(enabled)
        self.llm_enabled = bool(llm_enabled)
        self.minimum_incomplete_confidence = max(
            0.0, min(1.0, float(minimum_incomplete_confidence))
        )

    def decide(
        self,
        *,
        user_input: str,
        assistant_text: str,
        goal_instructions: list[str] | None = None,
    ) -> CompletionDecision:
        user = user_input.strip()
        answer = assistant_text.strip()
        goals = [str(item).strip() for item in (goal_instructions or []) if str(item).strip()]

        if not self.enabled:
            return self._complete("完成判定未启用。", "disabled", 1.0)
        if not answer:
            return self._incomplete(
                "当前回复为空。", "rule", 1.0, "直接完成用户当前请求，不要只做承诺或预告。"
            )
        if not self._SUBSTANTIVE_REQUEST.search(user):
            return self._complete("当前不是明显的内容交付型请求。", "rule", 0.94)

        # Strong local guard for the exact failure mode: the model promises to
        # provide content but stops before the content begins.
        if len(answer) <= 140 and (
            self._PROMISE_TAIL.search(answer)
            or (
                self._SETUP_ONLY.search(answer)
                and not self._has_delivered_payload(user, answer)
            )
        ):
            return self._incomplete(
                "回复停在准备/承诺阶段，尚未交付用户要求的主体内容。",
                "rule",
                0.99,
                "不要重复开场白，直接从缺失的主体内容开始，并把当前请求完成。",
            )

        if "故事" in user and len(answer) < 90 and re.search(r"(?:从前|有个|有一|那天|夜里)", answer):
            return self._incomplete(
                "故事已经起头但没有形成最基本的展开或收束。",
                "rule",
                0.94,
                "接着当前故事继续讲到一个自然结尾，不要重新从开场讲一遍。",
            )

        if re.search(r"(?:一次性|完整|全部|全文|连带|一起发)", user) and len(answer) < 180:
            return self._incomplete(
                "用户明确要求一次性或完整交付，但当前内容明显过短。",
                "rule",
                0.96,
                "补齐所有缺失部分，一次性完成，不要再次询问用户是否继续。",
            )

        if not self.llm_enabled or self.llm is None or isinstance(self.llm, EchoLLMClient):
            return self._complete("规则层未发现明确未完成。", "rule", 0.82)

        model_decision = self._model_decision(user=user, answer=answer, goals=goals)
        if model_decision is None:
            return self._complete("判定模型不可用，按防循环策略停止续写。", "model_error", 0.55)
        if not model_decision.complete and model_decision.confidence < self.minimum_incomplete_confidence:
            return self._complete("未完成判断置信度不足，按防循环策略停止续写。", "confidence_fallback", 1.0 - model_decision.confidence)
        return model_decision

    @staticmethod
    def _has_delivered_payload(user: str, answer: str) -> bool:
        if "故事" in user:
            return len(answer) >= 90 and any(token in answer for token in ("从前", "后来", "那天", "有一", "夜里"))
        if "翻译" in user or "阅读" in user:
            # A real bilingual reading answer normally contains enough body text
            # and at least one structural separator/newline.
            return len(answer) >= 220 and ("\n" in answer or "翻译" in answer)
        return len(answer) >= 120

    def _model_decision(self, *, user: str, answer: str, goals: list[str]) -> CompletionDecision | None:
        system = (
            "你是对话完成度判定器，不扮演聊天角色。判断当前 assistant 回复是否已经实质完成用户这一轮请求。\n"
            "重点：不能把‘我来讲/我给你找/下面发你/一次性到位’这种只有承诺没有正文的回复判为完成。\n"
            "如果用户要求故事、文章、翻译、代码、列表、解释等可交付内容，必须已经出现主体内容。\n"
            "如果已经足够完成，就 complete=true。不要因为还能扩写就判未完成。\n"
            "只输出 JSON：{\"complete\":true,\"confidence\":0.0,\"reason\":\"一句理由\",\"continuation_instruction\":\"若未完成，说明只需补什么\"}"
        )
        payload = json.dumps(
            {"user_input": user, "goal_instructions": goals, "assistant_text": answer},
            ensure_ascii=False,
        )
        try:
            response = self.llm.complete(
                system=system,
                messages=[ChatMessage(role="user", content=payload)],
                tools=None,
            )
            data = json.loads(response.text.strip())
            if not isinstance(data, dict) or not isinstance(data.get("complete"), bool):
                return None
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            return CompletionDecision(
                complete=bool(data["complete"]),
                confidence=confidence,
                reason=str(data.get("reason", "")).strip() or "模型完成度判定。",
                source="model",
                continuation_instruction=str(data.get("continuation_instruction", "")).strip(),
            )
        except (LLMServiceError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _complete(reason: str, source: str, confidence: float) -> CompletionDecision:
        return CompletionDecision(True, confidence, reason, source)

    @staticmethod
    def _incomplete(reason: str, source: str, confidence: float, instruction: str) -> CompletionDecision:
        return CompletionDecision(False, confidence, reason, source, instruction)
