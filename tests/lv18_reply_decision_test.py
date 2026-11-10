from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.agent import SilverWolfAgent
from silverwolf_agent.llm.base import BaseLLMClient
from silverwolf_agent.memory import ShortTermMemory
from silverwolf_agent.models import ChatMessage, LLMResponse
from silverwolf_agent.reply_gate import ReplyDecisionAgent


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 5, 14, 21, 17, tzinfo=ZONE)


class StaticDecisionLLM(BaseLLMClient):
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools=None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self.text)


def history(last_assistant: str) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "想进好公司，但是有点担心。"},
        {"role": "assistant", "content": last_assistant},
    ]


def test_example_closure_is_silent() -> None:
    gate = ReplyDecisionAgent(llm=None)
    decision = gate.decide(
        user_input="嗯呢",
        recent_messages=history(
            "想进好公司是好事，说明你对自己有要求。不过别把自己逼太紧，慢慢来，我也在呢。"
        ),
    )
    assert decision.should_reply is False
    assert decision.category == "acknowledgement_closure"
    assert decision.source == "rule"
    assert decision.confidence >= 0.95


def test_short_answer_to_question_is_not_swallowed() -> None:
    gate = ReplyDecisionAgent(llm=None)
    decision = gate.decide(
        user_input="嗯呢",
        recent_messages=history("今天感觉好一点了吗？"),
    )
    assert decision.should_reply is True
    assert decision.category == "conversation_continuation"


def test_ack_with_new_content_must_reply() -> None:
    gate = ReplyDecisionAgent(llm=None)
    for text in (
        "嗯呢，我下午还有面试",
        "好的，那帮我看看浦口天气",
        "嗯，我有点难受",
        "晚安",
    ):
        decision = gate.decide(
            user_input=text,
            recent_messages=history("慢慢来，我在呢。"),
        )
        assert decision.should_reply is True, (text, decision)


def test_reaction_can_end_naturally() -> None:
    gate = ReplyDecisionAgent(llm=None)
    decision = gate.decide(
        user_input="😌",
        recent_messages=history("那就先休息一会儿。"),
    )
    assert decision.should_reply is False
    assert decision.category == "reaction_closure"


def test_ambiguous_message_uses_dedicated_model() -> None:
    llm = StaticDecisionLLM(
        '{"should_reply":false,"confidence":0.93,'
        '"category":"acknowledgement_closure",'
        '"reason":"感谢语在当前上下文中是自然收尾。"}'
    )
    gate = ReplyDecisionAgent(llm=llm)
    decision = gate.decide(
        user_input="谢谢啦",
        recent_messages=history("这份步骤照着做就可以了。"),
    )
    assert llm.calls == 1
    assert decision.should_reply is False
    assert decision.source == "model"


def test_low_confidence_silence_fails_open() -> None:
    llm = StaticDecisionLLM(
        '{"should_reply":false,"confidence":0.40,'
        '"category":"uncertain","reason":"不确定。"}'
    )
    gate = ReplyDecisionAgent(
        llm=llm,
        minimum_silence_confidence=0.78,
    )
    decision = gate.decide(
        user_input="这样啊",
        recent_messages=history("我把原因简单说完了。"),
    )
    assert decision.should_reply is True
    assert decision.source == "confidence_fallback"


def test_invalid_model_output_fails_open() -> None:
    llm = StaticDecisionLLM("不是 JSON")
    gate = ReplyDecisionAgent(llm=llm)
    decision = gate.decide(
        user_input="这样啊",
        recent_messages=history("我把原因简单说完了。"),
    )
    assert decision.should_reply is True
    assert decision.source == "fallback"


def test_silent_message_still_enters_memory() -> None:
    with tempfile.TemporaryDirectory() as value:
        memory = ShortTermMemory(path=Path(value) / "memory.json")
        memory.add_turn(
            "我有点担心找工作的事。",
            "慢慢来，我在呢。",
            at=NOW,
        )
        gate = ReplyDecisionAgent(llm=None)
        decision = gate.decide(
            user_input="嗯呢",
            recent_messages=memory.recent_chat_messages(limit=8),
        )
        assert decision.should_reply is False
        memory.add_user_message("嗯呢", at=NOW)

        context = memory.context_text()
        assert "用户：嗯呢" in context
        assert context.rstrip().endswith("用户：嗯呢")
        recent = memory.recent_chat_messages(limit=8)
        assert recent[-1] == {"role": "user", "content": "嗯呢"}



class _NoOpScheduler:
    def note_user_activity(self, now) -> None:
        self.last = now


class _NoOpProfile:
    def infer_explicit_updates(self, text: str) -> None:
        raise AssertionError("静默消息不应进入主档案推断")


class _BombPlanner:
    def plan_json(self, text: str, now) -> str:
        raise AssertionError("静默消息不应调用主 Planner")


class _BombExecutor:
    def execute_json(self, plan_json: str, now):
        raise AssertionError("静默消息不应调用主 Executor")


def test_chat_bundle_stops_before_main_agent() -> None:
    with tempfile.TemporaryDirectory() as value:
        agent = SilverWolfAgent.__new__(SilverWolfAgent)
        agent.config = type("Config", (), {"reply_gate_context_messages": 8})()
        agent.scheduler = _NoOpScheduler()
        agent.memory = ShortTermMemory(path=Path(value) / "memory.json")
        agent.memory.add_turn(
            "想进好公司。",
            "想进好公司是好事，不过别把自己逼太紧，慢慢来，我也在呢。",
            at=NOW,
        )
        agent.reply_decider = ReplyDecisionAgent(llm=None)
        agent.profile = _NoOpProfile()
        agent.planner = _BombPlanner()
        agent.executor = _BombExecutor()
        agent.last_reply_decision_json = ""
        agent.last_plan_json = "old-plan"
        agent.last_execution_json = "old-execution"
        agent._rollover_if_needed = lambda now: None
        agent._compact_memory_if_needed = lambda: None

        bundle = SilverWolfAgent.chat_bundle(
            agent,
            "嗯呢",
            received_at=NOW,
        )
        assert bundle.messages == []
        assert agent.last_plan_json == ""
        assert agent.last_execution_json == ""
        assert agent.reply_decision_snapshot()["should_reply"] is False
        assert agent.memory.recent_chat_messages(limit=8)[-1] == {
            "role": "user",
            "content": "嗯呢",
        }

def run() -> None:
    test_example_closure_is_silent()
    test_short_answer_to_question_is_not_swallowed()
    test_ack_with_new_content_must_reply()
    test_reaction_can_end_naturally()
    test_ambiguous_message_uses_dedicated_model()
    test_low_confidence_silence_fails_open()
    test_invalid_model_output_fails_open()
    test_silent_message_still_enters_memory()
    test_chat_bundle_stops_before_main_agent()
    print("lv18_reply_decision_test: OK")


if __name__ == "__main__":
    run()
