from __future__ import annotations

import json

from .contracts import ProactivePlan
from ..delivery import (
    OutboundMessage,
    ReplyBundle,
)


class ProactiveExecutor:
    """
    主动行为 Executor。

    输入 ProactivePlan JSON，
    输出带权重的 ReplyBundle。
    """

    def execute_json(
        self,
        plan_json: str,
    ) -> tuple[
        ReplyBundle,
        str,
    ]:
        plan = ProactivePlan.from_json(
            plan_json
        )

        messages = [
            OutboundMessage.from_dict(
                item
            )
            for item in (
                plan.planned_messages
            )
        ]

        bundle = ReplyBundle(
            messages=messages,
            minimum_weight=int(
                plan.metadata.get(
                    "minimum_weight",
                    50,
                )
            ),
            maximum_messages=int(
                plan.metadata.get(
                    "maximum_messages",
                    3,
                )
            ),
        )

        execution_json = json.dumps(
            {
                "schema_version": "1.0",
                "proactive_plan": (
                    plan.to_dict()
                ),
                "reply_bundle": (
                    bundle.to_dict()
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        return bundle, execution_json
