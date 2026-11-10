from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    confidence: float
    reason: str
    source: str
    continuation_instruction: str = ""
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
