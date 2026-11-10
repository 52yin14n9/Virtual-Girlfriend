from __future__ import annotations

import asyncio
from dataclasses import (
    asdict,
    dataclass,
)
from datetime import datetime
import itertools
from typing import (
    Any,
    Callable,
)

from ..agent import SilverWolfAgent
from .audit import QQAuditLogger
from .config import QQBotConfig
from .events import (
    QQFriendRequestEvent,
    QQMessageEvent,
)
from .onebot import (
    OneBot11Client,
)
from .sink import QQMessageSink


@dataclass
class QQBotAccountInfo:
    user_id: int = 0
    nickname: str = ""
    online: bool | None = None
    good: bool | None = None
    app_name: str = ""
    app_version: str = ""
    protocol_version: str = ""
    refreshed_at: str = ""

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        online_text = (
            "在线"
            if self.online is True
            else (
                "离线"
                if self.online is False
                else "未知"
            )
        )
        good_text = (
            "正常"
            if self.good is True
            else (
                "异常"
                if self.good is False
                else "未知"
            )
        )
        lines = [
            "我的 QQ 账号信息：",
            f"QQ号：{self.user_id or '未知'}",
            f"昵称：{self.nickname or '未知'}",
            f"在线状态：{online_text}",
            f"运行状态：{good_text}",
        ]
        if self.app_name:
            lines.append(
                f"OneBot实现：{self.app_name}"
            )
        if self.app_version:
            lines.append(
                f"实现版本：{self.app_version}"
            )
        if self.protocol_version:
            lines.append(
                f"协议版本：{self.protocol_version}"
            )
        return "\n".join(lines)


class QQGateway:
    """
    银狼 QQ 私有网关。

    安全边界：
    - 只有 MASTER_QQ 的消息进入 Agent；
    - 非主人消息不进入 LLM、短期记忆或 RAG；
    - 非主人好友申请默认拒绝；
    - 主人消息在事件优先队列中优先级最高；
    - 紧急关闭命令仅接受主人 + 环境变量 token。
    """

    ACCOUNT_INFO_COMMANDS = {
        "报告你的账号信息",
        "报告账号信息",
        "你的qq账号信息",
        "你的QQ账号信息",
        "/qq info",
        "/qq status",
    }

    def __init__(
        self,
        *,
        config: QQBotConfig,
        agent: SilverWolfAgent,
        client: (
            OneBot11Client
            | Any
            | None
        ) = None,
        audit: (
            QQAuditLogger
            | None
        ) = None,
        now_provider: (
            Callable[[], datetime]
            | None
        ) = None,
    ) -> None:
        self.config = config
        self.agent = agent
        self.client = (
            client
            or OneBot11Client(
                websocket_url=(
                    config.websocket_url
                ),
                access_token=(
                    config.access_token
                ),
                action_timeout_seconds=(
                    config
                    .action_timeout_seconds
                ),
                reconnect_initial_seconds=(
                    config
                    .reconnect_initial_seconds
                ),
                reconnect_max_seconds=(
                    config
                    .reconnect_max_seconds
                ),
                ping_interval_seconds=(
                    config
                    .ping_interval_seconds
                ),
                ping_timeout_seconds=(
                    config
                    .ping_timeout_seconds
                ),
            )
        )
        self.audit = (
            audit
            or QQAuditLogger(
                config.audit_log_path
            )
        )
        self.now_provider = (
            now_provider
            or agent.now
        )

        self.bot_info = (
            QQBotAccountInfo()
        )
        self._event_queue: (
            asyncio.PriorityQueue[
                tuple[
                    int,
                    int,
                    dict[str, Any],
                ]
            ]
        ) = asyncio.PriorityQueue(
            maxsize=(
                config.queue_max_size
            )
        )
        self._counter = (
            itertools.count()
        )
        self._worker: (
            asyncio.Task[None]
            | None
        ) = None
        self._stop_event = (
            asyncio.Event()
        )
        self._started = False
        self._stop_lock = (
            asyncio.Lock()
        )
        self._seen_message_ids: (
            set[int]
        ) = set()
        self._seen_order: list[int] = []
        self._seen_limit = 2048

    async def start(self) -> None:
        if self._started:
            return
        self.config.validate()
        if not self.config.enabled:
            raise RuntimeError(
                "QQ_BOT_ENABLED=false，QQ 网关未启用"
            )

        self._stop_event.clear()
        self.client.set_event_handler(
            self.enqueue_event
        )
        self._worker = (
            asyncio.create_task(
                self._worker_loop(),
                name=(
                    "silverwolf-qq-event-worker"
                ),
            )
        )

        try:
            await self.client.start()
            await self.client.wait_until_ready(
                timeout=45
            )
            await self.refresh_bot_info()

            if (
                self.bot_info.user_id
                == self.config.master_qq
            ):
                raise ValueError(
                    "机器人 QQ 号不能与 MASTER_QQ 相同"
                )

            master_sink = QQMessageSink(
                client=self.client,
                user_id=(
                    self.config.master_qq
                ),
            )
            await self.agent.start(
                master_sink
            )
            self._started = True

            self.audit.write(
                "qq_gateway_started",
                master_qq=(
                    self.config.master_qq
                ),
                bot_qq=(
                    self.bot_info.user_id
                ),
                bot_nickname=(
                    self.bot_info.nickname
                ),
                websocket_url=(
                    self.config
                    .websocket_url
                    .split("?", 1)[0]
                ),
            )
        except Exception:
            await self.stop()
            raise

    async def run_forever(
        self,
    ) -> None:
        await self.start()
        await self._stop_event.wait()

    async def stop(self) -> None:
        async with self._stop_lock:
            has_resources = (
                self._started
                or self._worker
                is not None
                or bool(
                    getattr(
                        self.client,
                        "connected",
                        False,
                    )
                )
            )
            if (
                self._stop_event.is_set()
                and not has_resources
            ):
                return

            self._stop_event.set()

            try:
                await self.agent.stop()
            except Exception as exc:
                self.audit.write(
                    "agent_stop_failed",
                    level="ERROR",
                    error=str(exc),
                )

            try:
                await self.client.stop()
            except Exception as exc:
                self.audit.write(
                    "onebot_stop_failed",
                    level="ERROR",
                    error=str(exc),
                )

            if self._worker is not None:
                current_task = (
                    asyncio.current_task()
                )
                if (
                    self._worker
                    is not current_task
                ):
                    self._worker.cancel()
                    try:
                        await self._worker
                    except asyncio.CancelledError:
                        pass
                self._worker = None

            if self._started:
                self.audit.write(
                    "qq_gateway_stopped"
                )
            self._started = False

    async def enqueue_event(
        self,
        event: dict[str, Any],
    ) -> None:
        priority = self._priority(
            event
        )
        await self._event_queue.put(
            (
                priority,
                next(
                    self._counter
                ),
                dict(event),
            )
        )

    async def process_event(
        self,
        event: dict[str, Any],
    ) -> None:
        """
        直接处理单个事件，供单元测试与嵌入式集成使用。
        """
        post_type = str(
            event.get(
                "post_type",
                "",
            )
        )
        if post_type == "message":
            await self._handle_message(
                QQMessageEvent.from_dict(
                    event
                )
            )
            return

        if (
            post_type == "request"
            and str(
                event.get(
                    "request_type",
                    "",
                )
            )
            == "friend"
        ):
            await self._handle_friend_request(
                QQFriendRequestEvent
                .from_dict(event)
            )
            return

        if (
            post_type
            == "meta_event"
            and str(
                event.get(
                    "meta_event_type",
                    "",
                )
            )
            == "lifecycle"
        ):
            sub_type = str(
                event.get(
                    "sub_type",
                    "",
                )
            )
            self.audit.write(
                "onebot_lifecycle",
                sub_type=sub_type,
                self_id=int(
                    event.get(
                        "self_id",
                        0,
                    )
                    or 0
                ),
            )
            if sub_type in {
                "connect",
                "enable",
            }:
                try:
                    await self.refresh_bot_info()
                except Exception as exc:
                    self.audit.write(
                        "bot_info_refresh_after_lifecycle_failed",
                        level="WARNING",
                        error=str(exc),
                    )

    async def refresh_bot_info(
        self,
    ) -> QQBotAccountInfo:
        login = await self.client.get_login_info()

        status: dict[str, Any] = {}
        version: dict[str, Any] = {}

        try:
            status = (
                await self.client.get_status()
            )
        except Exception as exc:
            self.audit.write(
                "get_status_failed",
                level="WARNING",
                error=str(exc),
            )

        try:
            version = (
                await self.client
                .get_version_info()
            )
        except Exception as exc:
            self.audit.write(
                "get_version_info_failed",
                level="WARNING",
                error=str(exc),
            )

        online_raw = status.get(
            "online"
        )
        good_raw = status.get(
            "good"
        )

        self.bot_info = (
            QQBotAccountInfo(
                user_id=int(
                    login.get(
                        "user_id",
                        0,
                    )
                    or 0
                ),
                nickname=str(
                    login.get(
                        "nickname",
                        "",
                    )
                ),
                online=(
                    bool(online_raw)
                    if online_raw
                    is not None
                    else None
                ),
                good=(
                    bool(good_raw)
                    if good_raw
                    is not None
                    else None
                ),
                app_name=str(
                    version.get(
                        "app_name",
                        version.get(
                            "app_full_name",
                            "",
                        ),
                    )
                ),
                app_version=str(
                    version.get(
                        "app_version",
                        version.get(
                            "version",
                            "",
                        ),
                    )
                ),
                protocol_version=str(
                    version.get(
                        "protocol_version",
                        "",
                    )
                ),
                refreshed_at=(
                    self.now_provider()
                    .astimezone(
                        self.agent
                        .config
                        .zoneinfo()
                    )
                    .isoformat(
                        timespec="seconds"
                    )
                ),
            )
        )
        self.audit.write(
            "bot_info_refreshed",
            bot_qq=(
                self.bot_info.user_id
            ),
            nickname=(
                self.bot_info.nickname
            ),
            online=(
                self.bot_info.online
            ),
            good=(
                self.bot_info.good
            ),
            app_name=(
                self.bot_info.app_name
            ),
            app_version=(
                self.bot_info.app_version
            ),
        )
        return self.bot_info

    async def notify_master(
        self,
        message: str,
    ) -> None:
        await self.client.send_private_msg(
            user_id=(
                self.config.master_qq
            ),
            message=message,
        )

    async def _worker_loop(
        self,
    ) -> None:
        while not (
            self._stop_event.is_set()
        ):
            try:
                (
                    _priority,
                    _sequence,
                    event,
                ) = (
                    await self
                    ._event_queue
                    .get()
                )
                try:
                    await self.process_event(
                        event
                    )
                finally:
                    self._event_queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.audit.write(
                    "qq_event_processing_failed",
                    level="ERROR",
                    error=str(exc),
                )

    async def _handle_friend_request(
        self,
        event: QQFriendRequestEvent,
    ) -> None:
        is_master = (
            event.user_id
            == self.config.master_qq
        )

        if is_master:
            approve = (
                self.config
                .auto_accept_master_friend
            )
            if approve:
                await self.client.set_friend_add_request(
                    flag=event.flag,
                    approve=True,
                    remark="主人",
                )
            self.audit.write(
                "master_friend_request",
                user_id=event.user_id,
                approved=approve,
                comment=(
                    event.comment[:200]
                ),
            )
            return

        if (
            self.config
            .reject_non_master_friend
        ):
            await self.client.set_friend_add_request(
                flag=event.flag,
                approve=False,
            )

        if (
            self.config
            .friend_request_log_enabled
        ):
            self.audit.write(
                "non_master_friend_request",
                level="WARNING",
                user_id=event.user_id,
                rejected=(
                    self.config
                    .reject_non_master_friend
                ),
                comment=(
                    event.comment[:200]
                ),
            )

        try:
            await self.notify_master(
                "\n".join(
                    [
                        "[通知] 已处理非主人好友申请",
                        f"QQ: {event.user_id}",
                        (
                            "处理: 已拒绝"
                            if (
                                self.config
                                .reject_non_master_friend
                            )
                            else "处理: 仅记录"
                        ),
                        (
                            "验证信息: "
                            + (
                                event.comment
                                or "无"
                            )[
                                : self.config
                                .notification_max_chars
                            ]
                        ),
                    ]
                )
            )
        except Exception as exc:
            self.audit.write(
                "friend_request_notification_failed",
                level="ERROR",
                user_id=event.user_id,
                error=str(exc),
            )

    async def _handle_message(
        self,
        event: QQMessageEvent,
    ) -> None:
        if (
            event.user_id <= 0
            or event.user_id
            == event.self_id
        ):
            return
        if (
            event.message_id
            and self._is_duplicate(
                event.message_id
            )
        ):
            self.audit.write(
                "duplicate_message_ignored",
                message_id=(
                    event.message_id
                ),
                user_id=event.user_id,
            )
            return
        if not event.text:
            return

        is_master = (
            event.user_id
            == self.config.master_qq
        )

        if not is_master:
            await self._handle_non_master_message(
                event
            )
            return

        if (
            event.message_type
            == "group"
            and not self.config
            .allow_master_group_message
        ):
            self.audit.write(
                "master_group_message_ignored",
                group_id=event.group_id,
                message_id=event.message_id,
            )
            return

        self.audit.write(
            "master_message_accepted",
            message_id=event.message_id,
            message_type=(
                event.message_type
            ),
            group_id=event.group_id,
            preview=(
                self._audit_preview(
                    event.text
                )
            ),
        )

        if await self._handle_master_command(
            event
        ):
            return

        sink = (
            QQMessageSink(
                client=self.client,
                group_id=(
                    event.group_id
                ),
            )
            if (
                event.message_type
                == "group"
                and event.group_id
                is not None
            )
            else QQMessageSink(
                client=self.client,
                user_id=(
                    self.config.master_qq
                ),
            )
        )

        bundle = await self.agent.handle_user_message(
            event.text,
            sink,
            received_at=(
                event.occurred_at(
                    self.agent
                    .config
                    .zoneinfo()
                )
            ),
        )
        if (
            bundle is not None
            and not getattr(bundle, "messages", [])
        ):
            snapshot = None
            snapshot_getter = getattr(
                self.agent,
                "reply_decision_snapshot",
                None,
            )
            if callable(snapshot_getter):
                try:
                    snapshot = snapshot_getter()
                except Exception:
                    snapshot = None
            self.audit.write(
                "master_message_reply_suppressed",
                message_id=event.message_id,
                category=(
                    snapshot.get("category")
                    if isinstance(snapshot, dict)
                    else None
                ),
                confidence=(
                    snapshot.get("confidence")
                    if isinstance(snapshot, dict)
                    else None
                ),
                decision_source=(
                    snapshot.get("source")
                    if isinstance(snapshot, dict)
                    else None
                ),
            )

    async def _handle_non_master_message(
        self,
        event: QQMessageEvent,
    ) -> None:
        self.audit.write(
            "identity_verification_failed",
            level="WARNING",
            sender_qq=event.user_id,
            nickname=event.nickname,
            message_type=(
                event.message_type
            ),
            group_id=event.group_id,
            message_id=event.message_id,
            preview=event.text[:200],
        )

        should_notify = (
            (
                event.message_type
                == "private"
                and self.config
                .notify_non_master_private
            )
            or (
                event.message_type
                == "group"
                and self.config
                .notify_non_master_group
            )
        )
        if not should_notify:
            return

        nickname = (
            event.nickname
            or await self._lookup_nickname(
                event.user_id
            )
            or "未知"
        )
        timestamp = (
            event.occurred_at(
                self.agent
                .config
                .zoneinfo()
            )
            .isoformat(
                timespec="seconds"
            )
        )
        content = event.text[
            : self.config
            .notification_max_chars
        ]

        lines = [
            (
                "[通知] 收到来自 QQ: "
                f"{event.user_id} 的消息"
            ),
            f"昵称: {nickname}",
        ]
        if event.group_id is not None:
            lines.append(
                f"来源群: {event.group_id}"
            )
        lines.extend(
            [
                f"消息内容: {content}",
                f"时间: {timestamp}",
            ]
        )

        await self.notify_master(
            "\n".join(lines)
        )

    async def _handle_master_command(
        self,
        event: QQMessageEvent,
    ) -> bool:
        normalized = (
            event.text.strip()
        )

        if (
            normalized
            in self.ACCOUNT_INFO_COMMANDS
            or normalized.lower()
            in {
                command.lower()
                for command
                in self.ACCOUNT_INFO_COMMANDS
            }
        ):
            info = await self.refresh_bot_info()
            await self._send_command_reply(
                event,
                info.render(),
            )
            return True

        emergency_prefix = (
            self.config
            .emergency_command
        )
        if (
            emergency_prefix
            and normalized.startswith(
                emergency_prefix
            )
        ):
            supplied = normalized[
                len(
                    emergency_prefix
                ):
            ].strip()

            if (
                not self.config
                .emergency_enabled
                or supplied
                != self.config
                .emergency_token
            ):
                self.audit.write(
                    "emergency_shutdown_auth_failed",
                    level="ERROR",
                    sender_qq=event.user_id,
                    message_id=(
                        event.message_id
                    ),
                )
                await self._send_command_reply(
                    event,
                    "紧急关闭验证失败，未执行。",
                )
                return True

            self.audit.write(
                "emergency_shutdown_requested",
                level="WARNING",
                sender_qq=event.user_id,
            )
            await self._send_command_reply(
                event,
                "紧急关闭指令已验证，银狼 QQ 网关正在停止。",
            )
            self._stop_event.set()
            asyncio.create_task(
                self.stop(),
                name=(
                    "silverwolf-qq-emergency-stop"
                ),
            )
            return True

        return False

    async def _send_command_reply(
        self,
        event: QQMessageEvent,
        content: str,
    ) -> None:
        if (
            event.message_type
            == "group"
            and event.group_id
            is not None
        ):
            await self.client.send_group_msg(
                group_id=event.group_id,
                message=content,
            )
        else:
            await self.client.send_private_msg(
                user_id=(
                    self.config.master_qq
                ),
                message=content,
            )

    async def _lookup_nickname(
        self,
        user_id: int,
    ) -> str:
        try:
            data = (
                await self.client
                .get_stranger_info(
                    user_id=user_id
                )
            )
            return str(
                data.get(
                    "nickname",
                    "",
                )
            )
        except Exception as exc:
            self.audit.write(
                "nickname_lookup_failed",
                level="WARNING",
                user_id=user_id,
                error=str(exc),
            )
            return ""

    def _audit_preview(
        self,
        text: str,
    ) -> str:
        normalized = text.strip()
        command = (
            self.config
            .emergency_command
        )
        if (
            command
            and normalized.startswith(
                command
            )
        ):
            return (
                "[紧急关闭命令内容已隐藏]"
            )
        return normalized[:200]

    def _is_duplicate(
        self,
        message_id: int,
    ) -> bool:
        if message_id in (
            self._seen_message_ids
        ):
            return True

        self._seen_message_ids.add(
            message_id
        )
        self._seen_order.append(
            message_id
        )
        if len(
            self._seen_order
        ) > self._seen_limit:
            expired = (
                self._seen_order.pop(0)
            )
            self._seen_message_ids.discard(
                expired
            )
        return False

    def _priority(
        self,
        event: dict[str, Any],
    ) -> int:
        user_id = int(
            event.get(
                "user_id",
                0,
            )
            or 0
        )
        is_master = (
            user_id
            == self.config.master_qq
        )
        post_type = str(
            event.get(
                "post_type",
                "",
            )
        )

        if (
            post_type == "message"
            and is_master
        ):
            return 0
        if (
            post_type == "request"
            and is_master
        ):
            return 1
        if post_type == "meta_event":
            return 10
        if post_type == "request":
            return 20
        if post_type == "message":
            return 30
        return 50
