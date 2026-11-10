from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
import json
from typing import Any
import uuid


@dataclass
class ResponseGoal:
    kind: str
    instruction: str
    source_text: str = ""
    priority: int = 100
    weight: int = 60
    split_preference: str = "auto"

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ResponseGoal":
        return cls(
            kind=str(data["kind"]),
            instruction=str(
                data["instruction"]
            ),
            source_text=str(
                data.get(
                    "source_text",
                    "",
                )
            ),
            priority=int(
                data.get(
                    "priority",
                    100,
                )
            ),
            weight=max(
                0,
                min(
                    100,
                    int(
                        data.get(
                            "weight",
                            60,
                        )
                    ),
                ),
            ),
            split_preference=str(
                data.get(
                    "split_preference",
                    "auto",
                )
            ),
        )


@dataclass
class ToolRequest:
    name: str
    arguments: dict[str, Any]
    reason: str

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ToolRequest":
        arguments = data.get(
            "arguments",
            {},
        )
        if not isinstance(
            arguments,
            dict,
        ):
            raise ValueError(
                "tool arguments "
                "必须是 JSON object"
            )
        return cls(
            name=str(data["name"]),
            arguments=arguments,
            reason=str(
                data.get(
                    "reason",
                    "",
                )
            ),
        )


@dataclass
class MemoryRequest:
    use_short_term: bool = True
    use_rag: bool = False
    rag_query: str = ""

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "MemoryRequest":
        return cls(
            use_short_term=bool(
                data.get(
                    "use_short_term",
                    True,
                )
            ),
            use_rag=bool(
                data.get(
                    "use_rag",
                    False,
                )
            ),
            rag_query=str(
                data.get(
                    "rag_query",
                    "",
                )
            ),
        )


@dataclass
class DeliveryPolicy:
    minimum_weight: int = 40
    maximum_messages: int = 3
    split_threshold: int = 75
    message_gap_seconds: float = 0.9

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "DeliveryPolicy":
        return cls(
            minimum_weight=int(
                data.get(
                    "minimum_weight",
                    40,
                )
            ),
            maximum_messages=int(
                data.get(
                    "maximum_messages",
                    3,
                )
            ),
            split_threshold=int(
                data.get(
                    "split_threshold",
                    75,
                )
            ),
            message_gap_seconds=float(
                data.get(
                    "message_gap_seconds",
                    0.9,
                )
            ),
        )


@dataclass
class ConversationPlan:
    plan_id: str
    schema_version: str
    user_input: str
    intent: str
    render_mode: str
    response_goals: list[
        ResponseGoal
    ]
    tool_requests: list[
        ToolRequest
    ]
    memory_request: MemoryRequest
    delivery_policy: DeliveryPolicy
    context_facts: list[str] = field(
        default_factory=list
    )
    style_hints: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def create(
        cls,
        *,
        user_input: str,
        intent: str,
        render_mode: str,
        response_goals: list[
            ResponseGoal
        ],
        tool_requests: list[
            ToolRequest
        ],
        memory_request: MemoryRequest,
        delivery_policy: DeliveryPolicy,
        context_facts: list[str] | None = None,
        style_hints: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ConversationPlan":
        return cls(
            plan_id=str(uuid.uuid4()),
            schema_version="2.0",
            user_input=user_input,
            intent=intent,
            render_mode=render_mode,
            response_goals=(
                response_goals
            ),
            tool_requests=tool_requests,
            memory_request=(
                memory_request
            ),
            delivery_policy=(
                delivery_policy
            ),
            context_facts=(
                context_facts or []
            ),
            style_hints=(
                style_hints or []
            ),
            metadata=metadata or {},
        )

    def validate(self) -> None:
        if not self.user_input.strip():
            raise ValueError(
                "plan.user_input 不能为空"
            )
        if self.render_mode not in {
            "local",
            "llm",
        }:
            raise ValueError(
                "render_mode 必须是 "
                "local 或 llm"
            )
        if not self.response_goals:
            raise ValueError(
                "plan 至少需要一个 "
                "response_goal"
            )
        for goal in self.response_goals:
            if goal.split_preference not in {
                "auto",
                "merge",
                "separate",
            }:
                raise ValueError(
                    "split_preference 非法"
                )
        for request in self.tool_requests:
            if not request.name:
                raise ValueError(
                    "tool request name "
                    "不能为空"
                )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ConversationPlan":
        plan = cls(
            plan_id=str(
                data["plan_id"]
            ),
            schema_version=str(
                data.get(
                    "schema_version",
                    "2.0",
                )
            ),
            user_input=str(
                data["user_input"]
            ),
            intent=str(
                data["intent"]
            ),
            render_mode=str(
                data["render_mode"]
            ),
            response_goals=[
                ResponseGoal.from_dict(
                    item
                )
                for item in data.get(
                    "response_goals",
                    [],
                )
            ],
            tool_requests=[
                ToolRequest.from_dict(
                    item
                )
                for item in data.get(
                    "tool_requests",
                    [],
                )
            ],
            memory_request=(
                MemoryRequest.from_dict(
                    data.get(
                        "memory_request",
                        {},
                    )
                )
            ),
            delivery_policy=(
                DeliveryPolicy.from_dict(
                    data.get(
                        "delivery_policy",
                        {},
                    )
                )
            ),
            context_facts=[
                str(item)
                for item in data.get(
                    "context_facts",
                    [],
                )
            ],
            style_hints=[
                str(item)
                for item in data.get(
                    "style_hints",
                    [],
                )
            ],
            metadata=dict(
                data.get(
                    "metadata",
                    {},
                )
            ),
        )
        plan.validate()
        return plan

    @classmethod
    def from_json(
        cls,
        value: str,
    ) -> "ConversationPlan":
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError(
                "plan JSON 顶层"
                "必须是 object"
            )
        return cls.from_dict(data)


@dataclass
class ToolExecutionResult:
    name: str
    ok: bool
    content: Any
    error: str | None
    reason: str

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ToolExecutionResult":
        return cls(
            name=str(data["name"]),
            ok=bool(data["ok"]),
            content=data.get(
                "content"
            ),
            error=(
                str(data["error"])
                if data.get("error")
                is not None
                else None
            ),
            reason=str(
                data.get(
                    "reason",
                    "",
                )
            ),
        )


@dataclass
class ExecutionPacket:
    schema_version: str
    plan: dict[str, Any]
    tool_results: list[
        ToolExecutionResult
    ]
    short_memory: str
    rag_context: str
    profile_context: dict[
        str,
        Any,
    ]
    cognition_context: dict[
        str,
        Any,
    ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(
        cls,
        value: str,
    ) -> "ExecutionPacket":
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError(
                "execution JSON 顶层"
                "必须是 object"
            )
        return cls(
            schema_version=str(
                data.get(
                    "schema_version",
                    "2.0",
                )
            ),
            plan=dict(
                data["plan"]
            ),
            tool_results=[
                ToolExecutionResult.from_dict(
                    item
                )
                for item in data.get(
                    "tool_results",
                    [],
                )
            ],
            short_memory=str(
                data.get(
                    "short_memory",
                    "",
                )
            ),
            rag_context=str(
                data.get(
                    "rag_context",
                    "",
                )
            ),
            profile_context=dict(
                data.get(
                    "profile_context",
                    {},
                )
            ),
            cognition_context=dict(
                data.get(
                    "cognition_context",
                    {},
                )
            ),
        )
