from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.delivery import MessageDispatcher, MessageSink, OutboundMessage, ReplyBundle
from silverwolf_agent.llm.base import BaseLLMClient
from silverwolf_agent.memory import AgentIdentityManager, JsonlRAGStore, ShortTermMemory, UserProfileManager
from silverwolf_agent.models import LLMResponse
from silverwolf_agent.pae import ConversationExecutor
from silverwolf_agent.pae.contracts import ConversationPlan, DeliveryPolicy, MemoryRequest, ResponseGoal
from silverwolf_agent.proactive import AsyncProactiveScheduler, PlanManager, ProactiveStateStore, TimeManager
from silverwolf_agent.proactive.contracts import ProactivePlan, RoutineEvent
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.response_completion import ResponseCompletionAgent
from silverwolf_agent.tools import ToolRegistry

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 1, 22, 0, tzinfo=ZONE)


class SequenceLLM(BaseLLMClient):
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, *, system, messages, tools=None) -> LLMResponse:
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return LLMResponse(text=self.outputs[index])


def _executor(root: Path, llm: BaseLLMClient) -> ConversationExecutor:
    default_profile = root / "default_user_profile.json"
    default_agent = root / "default_agent_profile.json"
    shutil.copy2(PROJECT_ROOT / "config" / "default_user_profile.json", default_profile)
    shutil.copy2(PROJECT_ROOT / "config" / "default_agent_profile.json", default_agent)
    profile = UserProfileManager(path=root / "profile.json", default_path=default_profile)
    memory = ShortTermMemory(path=root / "short.json")
    rag = JsonlRAGStore(path=root / "rag.jsonl")
    identity = AgentIdentityManager(path=default_agent)
    return ConversationExecutor(
        llm=llm,
        tool_registry=ToolRegistry(),
        profile=profile,
        memory=memory,
        rag=rag,
        prompt_builder=PromptBuilder(agent_identity=identity),
        agent_identity=identity,
        completion_agent=ResponseCompletionAgent(llm=None, llm_enabled=False),
        completion_max_rounds=2,
    )


def _plan(user_input: str) -> ConversationPlan:
    return ConversationPlan.create(
        user_input=user_input,
        intent="conversation",
        render_mode="llm",
        response_goals=[
            ResponseGoal(
                kind="answer_user",
                instruction="完整完成用户当前请求，不要只承诺稍后提供。",
                source_text=user_input,
                weight=90,
            )
        ],
        tool_requests=[],
        memory_request=MemoryRequest(use_short_term=True),
        delivery_policy=DeliveryPolicy(minimum_weight=40, maximum_messages=3, message_gap_seconds=0.0),
    )


def test_story_promise_is_completed_in_same_turn() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        llm = SequenceLLM([
            '{"messages":[{"content":"行，那我给你讲一个很短的故事","weight":90,"category":"conversation","goal_kinds":["answer_user"],"sequence":0}]}',
            "从前有只住在月台边的小猫，每晚替最后一班列车数星星。那天它数到第七颗时睡着了，梦里列车把所有没做完的事都装进远处的云里。醒来时，夜很安静，它也不再着急，只把尾巴圈好，继续睡了",
        ])
        executor = _executor(root, llm)
        bundle, _ = executor.execute_json(_plan("睡不着呢，讲个故事哄我").to_json(), NOW)
        text = bundle.joined_text()
        assert llm.calls == 2
        assert "行，那我给你讲一个很短的故事" in text
        assert "从前有只住在月台边的小猫" in text
        assert len(bundle.selected_messages()) == 1


def test_complete_once_request_gets_body_and_translation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        body = (
            "Passage: Many college students use small blocks of free time to review vocabulary, "
            "but research suggests that active recall is more useful than simply rereading notes. "
            "Students who test themselves often remember more after several days.\n\n"
            "翻译：许多大学生会利用零碎时间复习词汇，但研究表明，主动回忆通常比单纯重读笔记更有效。"
            "经常自我测试的学生，几天后往往能记住更多内容。\n\n"
            "Question: What does the passage mainly suggest? Answer: Active recall can improve memory."
        )
        llm = SequenceLLM([
            '{"messages":[{"content":"行，给你挑一篇经典的，原文和翻译一起发你，一次性到位","weight":90,"category":"conversation","goal_kinds":["answer_user"],"sequence":0}]}',
            body,
        ])
        executor = _executor(root, llm)
        bundle, _ = executor.execute_json(
            _plan("你帮我找一篇四级英语阅读理解，连带翻译后的内容一起发给我，一次性的发给我").to_json(), NOW
        )
        text = bundle.joined_text()
        assert llm.calls == 2
        assert "Passage:" in text
        assert "翻译：" in text
        assert len(bundle.selected_messages()) == 1


def test_completion_loop_stops_when_model_makes_no_progress() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        promise = "行，那我给你讲一个很短的故事"
        llm = SequenceLLM([
            '{"messages":[{"content":"行，那我给你讲一个很短的故事","weight":90,"category":"conversation","goal_kinds":["answer_user"],"sequence":0}]}',
            promise,
            promise,
        ])
        executor = _executor(root, llm)
        bundle, _ = executor.execute_json(_plan("睡不着呢，讲个故事哄我").to_json(), NOW)
        assert llm.calls == 2
        assert bundle.joined_text() == promise


class FailingSink(MessageSink):
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, message: OutboundMessage) -> None:
        self.calls += 1
        raise ConnectionError("OneBot disconnected")


class FakeTimeManager:
    def timezone(self):
        return ZONE

    def due_routines(self, current, state):
        if state.routine_sent("evening", current.date().isoformat()):
            return []
        return [RoutineEvent(key="evening", scheduled_at="17:58", weight=90, window_minutes=120)]

    def is_quiet_time(self, current):
        return False


class FixedProactivePlanner:
    def plan_json(self, *, now, routines, due_plans, follow_up):
        messages = []
        if routines:
            messages.append(
                OutboundMessage(
                    content="晚上啦，宝。项目不会跑，先吃点东西再继续。手头那个项目后来推进得怎么样？",
                    weight=90,
                    category="routine_evening",
                    source="proactive",
                    metadata={"routine_key": "evening", "expects_reply": True},
                ).to_dict()
            )
        return ProactivePlan.create(
            planned_messages=messages,
            routine_keys=[item.key for item in routines],
            scheduled_plan_ids=[],
            metadata={"minimum_weight": 50, "maximum_messages": 1},
        ).to_json()


class FixedProactiveExecutor:
    def execute_json(self, plan_json):
        plan = ProactivePlan.from_json(plan_json)
        return (
            ReplyBundle(
                messages=[OutboundMessage.from_dict(item) for item in plan.planned_messages],
                minimum_weight=50,
                maximum_messages=1,
            ),
            "{}",
        )


def test_network_failure_does_not_retry_every_poll() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state = ProactiveStateStore(path=root / "state.json")
        scheduler = AsyncProactiveScheduler(
            time_manager=FakeTimeManager(),
            plan_manager=PlanManager(path=root / "plans.json"),
            state=state,
            planner=FixedProactivePlanner(),
            executor=FixedProactiveExecutor(),
            memory=ShortTermMemory(path=root / "short.json"),
            dispatcher=MessageDispatcher(default_gap_seconds=0.0),
            now_provider=lambda: NOW,
            poll_seconds=5.0,
            follow_up_enabled=False,
        )
        sink = FailingSink()

        async def scenario():
            await scheduler.run_once(sink=sink, now=NOW)
            await scheduler.run_once(sink=sink, now=NOW + timedelta(seconds=5))
            await scheduler.run_once(sink=sink, now=NOW + timedelta(seconds=10))
            assert sink.calls == 1
            snapshot = state.proactive_delivery_guard_snapshot()
            assert snapshot["failure_count"] == 1
            assert snapshot["suspended"] is False

            # First retry is allowed only after the backoff window.
            await scheduler.run_once(sink=sink, now=NOW + timedelta(seconds=31))
            assert sink.calls == 2
            snapshot = state.proactive_delivery_guard_snapshot()
            assert snapshot["failure_count"] == 2

            # Second backoff is 120 seconds; the third failed attempt suspends
            # proactive delivery instead of retrying forever.
            await scheduler.run_once(sink=sink, now=NOW + timedelta(seconds=100))
            assert sink.calls == 2
            await scheduler.run_once(sink=sink, now=NOW + timedelta(seconds=152))
            assert sink.calls == 3
            snapshot = state.proactive_delivery_guard_snapshot()
            assert snapshot["failure_count"] == 3
            assert snapshot["suspended"] is True
            await scheduler.run_once(sink=sink, now=NOW + timedelta(minutes=30))
            assert sink.calls == 3

            # User activity proves the channel is alive and resets the circuit.
            state.note_user_activity(NOW + timedelta(minutes=31))
            assert state.proactive_delivery_guard_snapshot()["failure_count"] == 0

        asyncio.run(scenario())


def main() -> None:
    test_story_promise_is_completed_in_same_turn()
    test_complete_once_request_gets_body_and_translation()
    test_completion_loop_stops_when_model_makes_no_progress()
    test_network_failure_does_not_retry_every_poll()
    print("lv26 completion + delivery tests: PASS")


if __name__ == "__main__":
    main()
