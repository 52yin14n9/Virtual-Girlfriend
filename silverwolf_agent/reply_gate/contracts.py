from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any


@dataclass(frozen=True)
class ReplyDecision:
    """Whether the interactive agent should send a new QQ message."""

    should_reply: bool
    confidence: float
    category: str
    reason: str
    source: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
