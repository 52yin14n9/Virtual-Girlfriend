from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from silverwolf_agent.cognition import CognitiveStateManager
from silverwolf_agent.llm import EchoLLMClient
from silverwolf_agent.memory import AgentIdentityManager, JsonlRAGStore, ShortTermMemory, UserProfileManager
from silverwolf_agent.pae import ConversationExecutor, ConversationPlanner
from silverwolf_agent.proactive import PlanManager, TimeManager
from silverwolf_agent.prompts import PromptBuilder
from silverwolf_agent.tools import ToolRegistry

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 7, 20, 0, tzinfo=ZONE)


class Harness:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        default_profile = root / "default_user_profile.json"
        default_agent = root / "default_agent_profile.json"
        shutil.copy2(PROJECT_ROOT / "config" / "default_user_profile.json", default_profile)
        shutil.copy2(PROJECT_ROOT / "config" / "default_agent_profile.json", default_agent)
        self.profile = UserProfileManager(path=root / "user_profile.json", default_path=default_profile)
        self.memory = ShortTermMemory(path=root / "short_term.json")
        self.rag = JsonlRAGStore(path=root / "rag.jsonl")
        self.identity = AgentIdentityManager(path=default_agent)
        self.time = TimeManager(path=root / "time.json", timezone="Asia/Shanghai")
        self.plans = PlanManager(path=root / "plans.json")
        self.cognition = CognitiveStateManager(path=root / "cognitive_state.json")
        self.planner = ConversationPlanner(
            profile=self.profile,
            memory=self.memory,
            time_manager=self.time,
            plan_manager=self.plans,
            message_gap_seconds=0.0,
            agent_identity=self.identity,
            cognition=self.cognition,
        )
        self.executor = ConversationExecutor(
            llm=EchoLLMClient(),
            tool_registry=ToolRegistry(),
            profile=self.profile,
            memory=self.memory,
            rag=self.rag,
            prompt_builder=PromptBuilder(agent_identity=self.identity),
            agent_identity=self.identity,
        )

    def say(self, text: str, at: datetime = NOW) -> tuple[str, dict]:
        plan = self.planner.plan(text, at)
        bundle, packet_json = self.executor.execute_json(plan.to_json(), at)
        packet = json.loads(packet_json)
        intent = packet.get("cognition_context", {}).get("intent", {})
        intent_name = intent.get("name") if isinstance(intent, dict) else None
        self.cognition.record_assistant_reply(
            bundle.joined_text(),
            at,
            intent=intent_name,
        )
        return bundle.joined_text(), packet


def test_reason_chain_is_in_execution_packet(root: Path) -> None:
    h = Harness(root)
    _, packet = h.say("今天随便聊会儿")
    cognition = packet["cognition_context"]
    assert cognition["architecture"] == (
        "Identity -> Needs -> Relationship State -> Recent Events -> Current Mood -> Intent -> Response"
    )
    for key in (
        "identity", "needs", "relationship_state", "recent_events",
        "current_mood", "intent", "user_model", "shared_reality",
    ):
        assert key in cognition
    assert cognition["intent"]["name"] == "companionship"


def test_offline_life_persists_and_can_be_shared(root: Path) -> None:
    h = Harness(root)
    h.cognition.observe_silent_message("嗯", NOW - timedelta(days=2))
    created = h.cognition.advance_offline(NOW)
    assert created
    before = h.cognition.snapshot()
    assert len(before["life"]["events"]) >= 2

    response, packet = h.say("你今天怎么样？", NOW)
    assert packet["cognition_context"]["intent"]["name"] == "share_self"
    assert "今天嘛" in response
    assert response != "还不错呀，你呢？"

    # The manager persists to disk and remembers that one event was shared.
    reloaded = CognitiveStateManager(path=root / "cognitive_state.json")
    assert any(item.get("shared_at") for item in reloaded.snapshot()["life"]["events"])


def test_shared_project_becomes_common_reality(root: Path) -> None:
    h = Harness(root)
    _, packet = h.say("我们一起把这个 agent 的长期记忆做好")
    cognition = packet["cognition_context"]
    assert cognition["intent"]["name"] == "advance_shared_reality"
    projects = cognition["shared_reality"]["projects"]
    assert projects
    assert "agent 的长期记忆" in projects[-1]["title"]


def test_requested_supervision_is_bidirectional_but_supportive(root: Path) -> None:
    h = Harness(root)
    h.say("我要每天背单词，你监督我")
    response, packet = h.say("我今天没做到，光顾着打游戏了")
    intent = packet["cognition_context"]["intent"]
    assert intent["name"] == "accountability_support"
    assert intent["stance"] == "firm_support"
    assert "玩过头就是玩过头" in response
    assert "不是想管你" in response
    assert "站你这边" in response
    assert "不想理你" not in response
    assert "失望透了" not in response


def test_reasonable_failure_is_understood(root: Path) -> None:
    h = Harness(root)
    h.say("我要每天跑步，你监督我")
    response, packet = h.say("我今天没做到，因为发烧去医院了")
    intent = packet["cognition_context"]["intent"]
    assert intent["name"] == "accountability_support"
    assert intent["stance"] == "understanding_support"
    assert "能理解" in response
    assert "不用为了向我交差硬撑" in response
    assert "站你这边" in response


def test_user_model_is_correctable_and_changes_growth(root: Path) -> None:
    h = Harness(root)
    h.say("我其实很在意别人怎么看我")
    first = h.cognition.snapshot()
    active = [b for b in first["user_model"]["beliefs"] if b.get("status") == "active"]
    assert active
    careful_before = first["identity"]["growth_modifiers"]["careful_assumption"]

    response, packet = h.say("你理解错了，我不是这个意思，我现在没那么在意")
    assert packet["cognition_context"]["intent"]["name"] == "repair_understanding"
    assert "我理解错了" in response
    after = h.cognition.snapshot()
    assert after["user_model"]["corrections"]
    assert any(b.get("status") == "corrected" for b in after["user_model"]["beliefs"])
    assert after["identity"]["growth_modifiers"]["careful_assumption"] > careful_before


def test_distress_can_defer_own_story_without_guilt(root: Path) -> None:
    h = Harness(root)
    # Build enough unshared continuity that self_expression becomes meaningful.
    h.cognition.observe_silent_message("嗯", NOW - timedelta(days=3))
    h.cognition.advance_offline(NOW)
    response, packet = h.say("今天工作好累，真的有点撑不住")
    intent = packet["cognition_context"]["intent"]["name"]
    assert intent in {"comfort", "comfort_then_defer_self_share"}
    if intent == "comfort_then_defer_self_share":
        assert "你先讲" in response
        assert "欠我" not in response
        assert "都不关心我" not in response


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        tests = [
            test_reason_chain_is_in_execution_packet,
            test_offline_life_persists_and_can_be_shared,
            test_shared_project_becomes_common_reality,
            test_requested_supervision_is_bidirectional_but_supportive,
            test_reasonable_failure_is_understood,
            test_user_model_is_correctable_and_changes_growth,
            test_distress_can_defer_own_story_without_guilt,
        ]
        for index, test in enumerate(tests):
            test(root / str(index))
    print("lv21_cognitive_architecture_test: OK")


if __name__ == "__main__":
    run()
