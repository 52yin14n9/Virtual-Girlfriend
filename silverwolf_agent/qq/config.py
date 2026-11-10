from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from ..config import (
    _env_bool,
    load_project_env,
)
from ..paths import PROJECT_ROOT


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    value = int(
        os.getenv(
            name,
            str(default),
        )
    )
    if minimum is not None:
        value = max(
            minimum,
            value,
        )
    return value


@dataclass(frozen=True)
class QQBotConfig:
    """
    QQ / OneBot 11 网关配置。

    QQ 协议登录由 NapCat、LLOneBot 或兼容实现完成；
    本项目只连接其 OneBot WebSocket，不读取 QQ 密码。
    """

    enabled: bool
    master_qq: int
    websocket_url: str
    access_token: str
    allow_empty_access_token: bool
    auto_accept_master_friend: bool
    reject_non_master_friend: bool
    notify_non_master_private: bool
    notify_non_master_group: bool
    allow_master_group_message: bool
    friend_request_log_enabled: bool
    emergency_command: str
    emergency_token: str
    action_timeout_seconds: float
    reconnect_initial_seconds: float
    reconnect_max_seconds: float
    ping_interval_seconds: float
    ping_timeout_seconds: float
    notification_max_chars: int
    queue_max_size: int
    audit_log_path: Path

    @classmethod
    def from_env(
        cls,
    ) -> "QQBotConfig":
        load_project_env()

        master_raw = (
            os.getenv(
                "MASTER_QQ",
                "",
            ).strip()
        )
        master_qq = (
            int(master_raw)
            if master_raw
            else 0
        )

        log_raw = os.getenv(
            "QQ_AUDIT_LOG_PATH",
            "data/qq/qq_gateway.jsonl",
        )
        log_path = Path(log_raw)
        if not log_path.is_absolute():
            log_path = (
                PROJECT_ROOT
                / log_path
            )

        return cls(
            enabled=_env_bool(
                "QQ_BOT_ENABLED",
                False,
            ),
            master_qq=master_qq,
            websocket_url=os.getenv(
                "ONEBOT_WS_URL",
                "ws://127.0.0.1:3001",
            ).strip(),
            access_token=os.getenv(
                "ONEBOT_ACCESS_TOKEN",
                "",
            ).strip(),
            allow_empty_access_token=(
                _env_bool(
                    "QQ_ALLOW_EMPTY_ONEBOT_TOKEN",
                    False,
                )
            ),
            auto_accept_master_friend=(
                _env_bool(
                    "QQ_AUTO_ACCEPT_MASTER_FRIEND",
                    True,
                )
            ),
            reject_non_master_friend=(
                _env_bool(
                    "QQ_REJECT_NON_MASTER_FRIEND",
                    True,
                )
            ),
            notify_non_master_private=(
                _env_bool(
                    "QQ_NOTIFY_NON_MASTER_PRIVATE",
                    True,
                )
            ),
            notify_non_master_group=(
                _env_bool(
                    "QQ_NOTIFY_NON_MASTER_GROUP",
                    False,
                )
            ),
            allow_master_group_message=(
                _env_bool(
                    "QQ_ALLOW_MASTER_GROUP_MESSAGE",
                    False,
                )
            ),
            friend_request_log_enabled=(
                _env_bool(
                    "QQ_FRIEND_REQUEST_LOG_ENABLED",
                    True,
                )
            ),
            emergency_command=os.getenv(
                "QQ_EMERGENCY_COMMAND",
                "/qq shutdown",
            ).strip(),
            emergency_token=os.getenv(
                "QQ_EMERGENCY_TOKEN",
                "",
            ).strip(),
            action_timeout_seconds=float(
                os.getenv(
                    "ONEBOT_ACTION_TIMEOUT_SECONDS",
                    "15",
                )
            ),
            reconnect_initial_seconds=float(
                os.getenv(
                    "ONEBOT_RECONNECT_INITIAL_SECONDS",
                    "2",
                )
            ),
            reconnect_max_seconds=float(
                os.getenv(
                    "ONEBOT_RECONNECT_MAX_SECONDS",
                    "30",
                )
            ),
            ping_interval_seconds=float(
                os.getenv(
                    "ONEBOT_PING_INTERVAL_SECONDS",
                    "20",
                )
            ),
            ping_timeout_seconds=float(
                os.getenv(
                    "ONEBOT_PING_TIMEOUT_SECONDS",
                    "20",
                )
            ),
            notification_max_chars=(
                _env_int(
                    "QQ_NOTIFICATION_MAX_CHARS",
                    1000,
                    minimum=100,
                )
            ),
            queue_max_size=_env_int(
                "QQ_EVENT_QUEUE_MAX_SIZE",
                1000,
                minimum=20,
            ),
            audit_log_path=log_path,
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.master_qq <= 0:
            raise ValueError(
                "QQ_BOT_ENABLED=true 时必须设置 MASTER_QQ"
            )
        if (
            not self.access_token
            and not self
            .allow_empty_access_token
        ):
            raise ValueError(
                "必须设置 ONEBOT_ACCESS_TOKEN；"
                "仅在完全隔离的本地环境中，"
                "才能显式设置 "
                "QQ_ALLOW_EMPTY_ONEBOT_TOKEN=true"
            )
        if not self.websocket_url.startswith(
            ("ws://", "wss://")
        ):
            raise ValueError(
                "ONEBOT_WS_URL 必须以 ws:// 或 wss:// 开头"
            )
        if (
            self.emergency_command
            and not self.emergency_token
        ):
            raise ValueError(
                "启用 QQ_EMERGENCY_COMMAND 时必须设置 "
                "QQ_EMERGENCY_TOKEN"
            )
        if self.action_timeout_seconds <= 0:
            raise ValueError(
                "ONEBOT_ACTION_TIMEOUT_SECONDS 必须大于 0"
            )

    @property
    def emergency_enabled(self) -> bool:
        return bool(
            self.emergency_command
            and self.emergency_token
        )
