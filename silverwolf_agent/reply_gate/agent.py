from __future__ import annotations

import json
import re
from typing import Any

from ..llm import BaseLLMClient, EchoLLMClient, LLMServiceError
from ..models import ChatMessage
from .contracts import ReplyDecision


class ReplyDecisionAgent:
    """
    Dedicated conversational turn-taking agent.

    It decides whether a new user message needs a visible reply before the
    main Planner/Executor is called. Important or uncertain messages fail open
    to a normal reply; only high-confidence conversational closures are silent.
    """

    _ACK_ONLY = re.compile(
        r"^(?:"
        r"嗯+|嗯呢|嗯呐|嗯好|好+|好的|好哒|好嘞|好呀|好哦|"
        r"行|行吧|可以|可以的|知道了|收到|明白了|懂了|"
        r"没问题|对的|是的|ok+|okay|okk+|噢+|哦+|啊好"
        r")[~～。.!！]*$",
        re.IGNORECASE,
    )
    _REACTION_ONLY = re.compile(
        r"^(?:[😀-🙏🌀-🫿❤♥✨⭐🌟💫]+|哈哈+|嘿嘿+|嘻嘻+|笑死)[~～。.!！]*$"
    )
    _QUESTION = re.compile(
        r"[？?]|(?:吗|么|嘛)\s*[。！!]*$|(?:你呢|然后呢|后来呢|现在呢)\s*[。！!]*$|"
        r"(?:怎么|为什么|为何|什么|哪里|哪儿|哪个|谁|多少|几点|"
        r"什么时候|怎么样|要不要|想不想|需不需要|是不是|能不能|"
        r"可不可以|是否)"
    )
    _REQUEST = re.compile(
        r"(?:帮我|请你|麻烦|记得|提醒我|告诉我|查一下|看看|"
        r"改成|设置|取消|关闭|打开|不要|别再|以后|从现在起|"
        r"给我|教我|写一个|做一个|分析|解释|继续|回复|回答)"
    )
    _IMPORTANT_STATE = re.compile(
        r"(?:难过|焦虑|害怕|孤独|崩溃|痛苦|想哭|不舒服|生病|"
        r"受伤|头疼|胸闷|喘不过气|累死|烦死|撑不住|受不了|"
        r"不想活|想死|自杀|出事|报警|急救)"
    )
    _GREETING_OR_GOODBYE = re.compile(
        r"^(?:早安|早上好|中午好|下午好|晚上好|晚安|你好|嗨|哈喽|"
        r"拜拜|再见|我睡了|我去睡了|先睡了|明天见)[~～。.!！]*$"
    )
    _DIRECT_ADDRESS = re.compile(
        r"(?:银狼|正在等你说早安)"
    )
    _PREVIOUS_EXPECTS_REPLY = re.compile(
        r"[？?]|(?:吗|么|嘛)\s*[。！!]*$|(?:你呢|然后呢|后来呢|现在呢)\s*[。！!]*$|"
        r"(?:要不要|想不想|需不需要|可以吗|可不可以|怎么样|"
        r"什么时候|哪里|哪一个|哪个|多少|几点|告诉我你的选择|"
        r"你觉得|你想|选一个)"
    )
    _ALLOWED_CATEGORIES = {
        "acknowledgement_closure",
        "reaction_closure",
        "question_or_request",
        "new_information",
        "emotional_support",
        "greeting_or_goodbye",
        "conversation_continuation",
        "uncertain",
        "disabled",
        "model_error",
    }

    def __init__(
        self,
        *,
        llm: BaseLLMClient | None = None,
        enabled: bool = True,
        llm_enabled: bool = True,
        minimum_silence_confidence: float = 0.78,
        context_messages: int = 8,
    ) -> None:
        self.llm = llm
        self.enabled = bool(enabled)
        self.llm_enabled = bool(llm_enabled)
        self.minimum_silence_confidence = max(
            0.0,
            min(1.0, float(minimum_silence_confidence)),
        )
        self.context_messages = max(2, int(context_messages))

    def decide(
        self,
        *,
        user_input: str,
        recent_messages: list[dict[str, str]] | None = None,
    ) -> ReplyDecision:
        text = user_input.strip()
        history = list(recent_messages or [])[-self.context_messages :]

        if not self.enabled:
            return self._reply(
                category="disabled",
                reason="回复判定功能未启用。",
                source="disabled",
                confidence=1.0,
            )
        if not text:
            return self._silent(
                category="acknowledgement_closure",
                reason="空消息无需生成可见回复。",
                source="rule",
                confidence=1.0,
            )

        previous_assistant = self._last_assistant(history)
        previous_expects_reply = bool(
            previous_assistant
            and self._PREVIOUS_EXPECTS_REPLY.search(previous_assistant)
        )

        if previous_assistant and not previous_expects_reply:
            if self._ACK_ONLY.fullmatch(text):
                return self._silent(
                    category="acknowledgement_closure",
                    reason="用户只是对上一条非提问消息作简短确认，对话可自然停住。",
                    source="rule",
                    confidence=0.98,
                )
            if self._REACTION_ONLY.fullmatch(text):
                return self._silent(
                    category="reaction_closure",
                    reason="用户仅作轻量反应，上一条消息也没有等待答案。",
                    source="rule",
                    confidence=0.91,
                )

        # A short acknowledgement can be the answer to a real question. Keep it.
        if previous_expects_reply and (
            self._ACK_ONLY.fullmatch(text)
            or self._REACTION_ONLY.fullmatch(text)
        ):
            return self._reply(
                category="conversation_continuation",
                reason="上一条消息包含明确问题，短回复可能承载有效回答。",
                source="rule",
                confidence=0.94,
            )

        strong_reply = self._strong_reply_reason(text)
        if strong_reply:
            category, reason = strong_reply
            return self._reply(
                category=category,
                reason=reason,
                source="rule",
                confidence=0.99,
            )

        if not previous_assistant:
            return self._reply(
                category="conversation_continuation",
                reason="缺少上一条银狼消息，不能把当前内容当作收尾。",
                source="rule",
                confidence=0.96,
            )

        model_decision = self._model_decision(text=text, history=history)
        if model_decision is not None:
            if (
                not model_decision.should_reply
                and model_decision.confidence < self.minimum_silence_confidence
            ):
                return self._reply(
                    category="uncertain",
                    reason="判定模型对静默没有达到安全置信度，按保守策略回复。",
                    source="confidence_fallback",
                    confidence=1.0 - model_decision.confidence,
                )
            return model_decision

        return self._reply(
            category="uncertain",
            reason="无法可靠确认对话已经结束，按保守策略正常回复。",
            source="fallback",
            confidence=0.60,
        )

    def _model_decision(
        self,
        *,
        text: str,
        history: list[dict[str, str]],
    ) -> ReplyDecision | None:
        if (
            not self.llm_enabled
            or self.llm is None
            or isinstance(self.llm, EchoLLMClient)
        ):
            return None

        transcript = [
            {
                "role": str(item.get("role", "")),
                "content": str(item.get("content", "")),
            }
            for item in history
            if str(item.get("content", "")).strip()
        ]
        payload: dict[str, Any] = {
            "recent_conversation": transcript,
            "new_user_message": text,
        }
        system = (
            "你是独立的对话轮次判定 Agent。你不生成聊天回复，只判断银狼是否应再发送一条消息。\n"
            "仅当用户是在做纯确认、附和、表情反应或自然收尾，并且上一条银狼消息没有明确提问、请求选择或等待信息时，才允许 should_reply=false。\n"
            "出现问题、请求、新事实、状态变化、情绪求助、问候、告别、日程/天气/设置意图、纠正信息，或任何不确定情况，都必须 should_reply=true。\n"
            "不要因为消息很短就静默；要结合上一条消息。宁可多回复一次，也不能吞掉重要内容。\n"
            "只输出 JSON："
            '{"should_reply":true,"confidence":0.0,"category":"类别","reason":"一句中文理由"}'
        )
        try:
            response = self.llm.complete(
                system=system,
                messages=[
                    ChatMessage(
                        role="user",
                        content=json.dumps(payload, ensure_ascii=False),
                    )
                ],
                tools=None,
            )
            data = self._parse_json(response.text)
            if data is None:
                return None
            should_reply = data.get("should_reply")
            if not isinstance(should_reply, bool):
                return None
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            category = str(data.get("category", "uncertain"))
            if category not in self._ALLOWED_CATEGORIES:
                category = "uncertain"
            reason = str(data.get("reason", "模型完成回复必要性判断。")).strip()
            return ReplyDecision(
                should_reply=should_reply,
                confidence=confidence,
                category=category,
                reason=reason[:240],
                source="model",
            )
        except (LLMServiceError, ValueError, TypeError, json.JSONDecodeError):
            return None
        except Exception:
            # This gate must never take the main conversation down.
            return None

    @classmethod
    def _strong_reply_reason(cls, text: str) -> tuple[str, str] | None:
        if cls._GREETING_OR_GOODBYE.fullmatch(text):
            return (
                "greeting_or_goodbye",
                "问候或告别通常需要一个自然回应。",
            )
        if cls._IMPORTANT_STATE.search(text):
            return (
                "emotional_support",
                "消息包含重要情绪或身体状态，不能静默。",
            )
        if cls._QUESTION.search(text):
            return (
                "question_or_request",
                "消息包含问题，需要回答。",
            )
        if cls._REQUEST.search(text):
            return (
                "question_or_request",
                "消息包含请求、设置或行动意图。",
            )
        if cls._DIRECT_ADDRESS.search(text):
            return (
                "conversation_continuation",
                "用户直接称呼银狼或 QQ 昵称。",
            )
        # Acknowledgement plus additional content is new information, not closure.
        if len(text) >= 8 or re.search(r"[，,；;：:]", text):
            return (
                "new_information",
                "消息包含超出简单附和的新内容。",
            )
        return None

    @staticmethod
    def _last_assistant(history: list[dict[str, str]]) -> str:
        for item in reversed(history):
            if str(item.get("role", "")) == "assistant":
                value = str(item.get("content", "")).strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
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

    @staticmethod
    def _reply(*, category: str, reason: str, source: str, confidence: float) -> ReplyDecision:
        return ReplyDecision(
            should_reply=True,
            confidence=max(0.0, min(1.0, confidence)),
            category=category,
            reason=reason,
            source=source,
        )

    @staticmethod
    def _silent(*, category: str, reason: str, source: str, confidence: float) -> ReplyDecision:
        return ReplyDecision(
            should_reply=False,
            confidence=max(0.0, min(1.0, confidence)),
            category=category,
            reason=reason,
            source=source,
        )
