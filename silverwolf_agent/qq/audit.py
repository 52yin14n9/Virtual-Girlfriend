from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any


class QQAuditLogger:
    """
    追加式 JSONL 审计日志。

    调用方只传入经过筛选的字段；access token、API key 和
    紧急关闭 token 不应进入 fields。
    """

    def __init__(
        self,
        path: Path,
    ) -> None:
        self.path = path
        self._lock = (
            threading.RLock()
        )

    def write(
        self,
        event: str,
        *,
        level: str = "INFO",
        **fields: Any,
    ) -> None:
        record = {
            "timestamp": (
                datetime.now()
                .astimezone()
                .isoformat(
                    timespec="seconds"
                )
            ),
            "level": level,
            "event": event,
            **fields,
        }
        with self._lock:
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            with self.path.open(
                "a",
                encoding="utf-8",
            ) as file:
                file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
