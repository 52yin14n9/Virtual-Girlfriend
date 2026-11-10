from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from silverwolf_agent.delivery import (
    OutboundMessage,
)
from silverwolf_agent.qq import (
    QQAuditLogger,
    QQBotConfig,
    QQGateway,
    QQMessageSink,
    extract_message_text,
)


ZONE = ZoneInfo("Asia/Shanghai")
MASTER_QQ = 123456789
BOT_QQ = 987654321


class FakeAppConfig:
    def zoneinfo(self):
        return ZONE


class FakeAgent:
    def __init__(self) -> None:
        self.config = FakeAppConfig()
        self.started_sink = None
        self.stopped = False
        self.received: list[
            tuple[str, datetime]
        ] = []

    def now(self) -> datetime:
        return datetime(
            2026,
            8,
            4,
            20,
            0,
            tzinfo=ZONE,
        )

    async def start(
        self,
        sink,
    ) -> None:
        self.started_sink = sink

    async def stop(self) -> None:
        self.stopped = True

    async def handle_user_message(
        self,
        text,
        sink,
        *,
        received_at=None,
    ):
        self.received.append(
            (
                text,
                received_at,
            )
        )
        await sink.send(
            OutboundMessage(
                content=(
                    "银狼回复："
                    + text
                ),
                weight=100,
                category=(
                    "conversation"
                ),
                source=(
                    "interactive"
                ),
            )
        )


class FakeOneBotClient:
    def __init__(self) -> None:
        self.connected = False
        self.handler = None
        self.private_messages: list[
            dict
        ] = []
        self.group_messages: list[
            dict
        ] = []
        self.friend_actions: list[
            dict
        ] = []
        self.login_info = {
            "user_id": BOT_QQ,
            "nickname": "银狼测试号",
        }
        self.status = {
            "online": True,
            "good": True,
        }
        self.version = {
            "app_name": "NapCat.OneBot",
            "app_version": "test-version",
            "protocol_version": "v11",
        }
        self.strangers = {
            111222333: {
                "nickname": "陌生测试员",
            }
        }

    def set_event_handler(
        self,
        handler,
    ) -> None:
        self.handler = handler

    async def start(self) -> None:
        self.connected = True

    async def stop(self) -> None:
        self.connected = False

    async def wait_until_ready(
        self,
        timeout=30,
    ) -> None:
        assert self.connected

    async def send_private_msg(
        self,
        *,
        user_id,
        message,
    ):
        record = {
            "user_id": int(user_id),
            "message": str(message),
        }
        self.private_messages.append(
            record
        )
        return {
            "message_id": len(
                self.private_messages
            )
        }

    async def send_group_msg(
        self,
        *,
        group_id,
        message,
    ):
        record = {
            "group_id": int(group_id),
            "message": str(message),
        }
        self.group_messages.append(
            record
        )
        return {
            "message_id": len(
                self.group_messages
            )
        }

    async def set_friend_add_request(
        self,
        *,
        flag,
        approve,
        remark="",
    ):
        self.friend_actions.append(
            {
                "flag": flag,
                "approve": bool(
                    approve
                ),
                "remark": remark,
            }
        )
        return None

    async def get_login_info(self):
        return dict(
            self.login_info
        )

    async def get_status(self):
        return dict(
            self.status
        )

    async def get_version_info(self):
        return dict(
            self.version
        )

    async def get_stranger_info(
        self,
        *,
        user_id,
    ):
        return dict(
            self.strangers.get(
                int(user_id),
                {
                    "nickname": "",
                },
            )
        )


def make_config(
    root: Path,
    **overrides,
) -> QQBotConfig:
    values = {
        "enabled": True,
        "master_qq": MASTER_QQ,
        "websocket_url": (
            "ws://127.0.0.1:3001"
        ),
        "access_token": "test-access",
        "allow_empty_access_token": False,
        "auto_accept_master_friend": True,
        "reject_non_master_friend": True,
        "notify_non_master_private": True,
        "notify_non_master_group": False,
        "allow_master_group_message": False,
        "friend_request_log_enabled": True,
        "emergency_command": (
            "/qq shutdown"
        ),
        "emergency_token": (
            "emergency-secret"
        ),
        "action_timeout_seconds": 5.0,
        "reconnect_initial_seconds": 1.0,
        "reconnect_max_seconds": 5.0,
        "ping_interval_seconds": 20.0,
        "ping_timeout_seconds": 20.0,
        "notification_max_chars": 1000,
        "queue_max_size": 100,
        "audit_log_path": (
            root / "qq.jsonl"
        ),
    }
    values.update(overrides)
    return QQBotConfig(
        **values
    )


def private_event(
    *,
    user_id: int,
    text: str,
    message_id: int,
    nickname: str = "",
    timestamp: int = 1785859200,
) -> dict:
    return {
        "time": timestamp,
        "self_id": BOT_QQ,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": message_id,
        "user_id": user_id,
        "message": [
            {
                "type": "text",
                "data": {
                    "text": text,
                },
            }
        ],
        "raw_message": text,
        "sender": {
            "user_id": user_id,
            "nickname": nickname,
        },
    }


def group_event(
    *,
    user_id: int,
    text: str,
    message_id: int,
    group_id: int = 555666777,
) -> dict:
    data = private_event(
        user_id=user_id,
        text=text,
        message_id=message_id,
        nickname="群成员",
    )
    data.update(
        {
            "message_type": "group",
            "sub_type": "normal",
            "group_id": group_id,
        }
    )
    return data


def friend_event(
    *,
    user_id: int,
    flag: str,
    comment: str,
) -> dict:
    return {
        "time": 1785859200,
        "self_id": BOT_QQ,
        "post_type": "request",
        "request_type": "friend",
        "user_id": user_id,
        "comment": comment,
        "flag": flag,
    }


async def start_gateway(
    root: Path,
    **config_overrides,
):
    client = FakeOneBotClient()
    agent = FakeAgent()
    config = make_config(
        root,
        **config_overrides,
    )
    gateway = QQGateway(
        config=config,
        agent=agent,
        client=client,
        audit=QQAuditLogger(
            config.audit_log_path
        ),
        now_provider=agent.now,
    )
    await gateway.start()
    return (
        gateway,
        client,
        agent,
        config,
    )


def test_config_validation(
    root: Path,
) -> None:
    invalid = make_config(
        root,
        master_qq=0,
    )
    try:
        invalid.validate()
    except ValueError as exc:
        assert "MASTER_QQ" in str(
            exc
        )
    else:
        raise AssertionError(
            "missing MASTER_QQ must fail"
        )

    invalid_token = make_config(
        root,
        emergency_token="",
    )
    try:
        invalid_token.validate()
    except ValueError as exc:
        assert (
            "QQ_EMERGENCY_TOKEN"
            in str(exc)
        )
    else:
        raise AssertionError(
            "missing emergency token must fail"
        )


def test_message_extraction() -> None:
    event = {
        "message": [
            {
                "type": "text",
                "data": {
                    "text": "你好",
                },
            },
            {
                "type": "image",
                "data": {
                    "file": "unsafe-path",
                },
            },
            {
                "type": "at",
                "data": {
                    "qq": "123",
                },
            },
        ]
    }
    assert (
        extract_message_text(
            event
        )
        == "你好[图片][@123]"
    )


async def master_message_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        _config,
    ) = await start_gateway(root)
    try:
        await gateway.process_event(
            private_event(
                user_id=MASTER_QQ,
                text="你好",
                message_id=1,
                nickname="主人",
            )
        )
        assert len(
            agent.received
        ) == 1
        assert agent.received[0][0] == (
            "你好"
        )
        assert (
            client.private_messages[-1]
            == {
                "user_id": MASTER_QQ,
                "message": (
                    "银狼回复：你好"
                ),
            }
        )
        assert gateway._priority(
            private_event(
                user_id=MASTER_QQ,
                text="优先",
                message_id=2,
            )
        ) == 0
    finally:
        await gateway.stop()


async def non_master_message_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        config,
    ) = await start_gateway(root)
    try:
        await gateway.process_event(
            private_event(
                user_id=111222333,
                text="你好银狼",
                message_id=10,
                nickname="",
            )
        )

        assert not agent.received
        assert len(
            client.private_messages
        ) == 1
        notice = (
            client.private_messages[0]
        )
        assert notice[
            "user_id"
        ] == MASTER_QQ
        assert (
            "[通知] 收到来自 QQ: "
            "111222333 的消息"
            in notice["message"]
        )
        assert (
            "昵称: 陌生测试员"
            in notice["message"]
        )
        assert (
            "消息内容: 你好银狼"
            in notice["message"]
        )
        assert "时间:" in (
            notice["message"]
        )

        records = [
            json.loads(line)
            for line in (
                config.audit_log_path
                .read_text(
                    encoding="utf-8"
                )
                .splitlines()
            )
        ]
        assert any(
            item["event"]
            == "identity_verification_failed"
            for item in records
        )
        assert not any(
            "test-access"
            in json.dumps(
                item,
                ensure_ascii=False,
            )
            for item in records
        )
    finally:
        await gateway.stop()


async def friend_request_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        _agent,
        _config,
    ) = await start_gateway(root)
    try:
        await gateway.process_event(
            friend_event(
                user_id=MASTER_QQ,
                flag="master-flag",
                comment="重新添加",
            )
        )
        assert (
            client.friend_actions[-1]
            == {
                "flag": "master-flag",
                "approve": True,
                "remark": "主人",
            }
        )

        await gateway.process_event(
            friend_event(
                user_id=444555666,
                flag="other-flag",
                comment="加个好友",
            )
        )
        assert (
            client.friend_actions[-1]
            == {
                "flag": "other-flag",
                "approve": False,
                "remark": "",
            }
        )
        assert any(
            "已处理非主人好友申请"
            in item["message"]
            for item in (
                client.private_messages
            )
        )
    finally:
        await gateway.stop()


async def account_info_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        _config,
    ) = await start_gateway(root)
    try:
        await gateway.process_event(
            private_event(
                user_id=MASTER_QQ,
                text="报告你的账号信息",
                message_id=20,
            )
        )
        assert not agent.received
        answer = (
            client.private_messages[-1]
            ["message"]
        )
        assert (
            f"QQ号：{BOT_QQ}"
            in answer
        )
        assert (
            "昵称：银狼测试号"
            in answer
        )
        assert "在线状态：在线" in (
            answer
        )
        assert (
            "OneBot实现：NapCat.OneBot"
            in answer
        )
    finally:
        await gateway.stop()


async def emergency_shutdown_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        _config,
    ) = await start_gateway(root)

    await gateway.process_event(
        private_event(
            user_id=MASTER_QQ,
            text=(
                "/qq shutdown wrong"
            ),
            message_id=30,
        )
    )
    assert gateway._started
    assert (
        "验证失败"
        in client.private_messages[-1][
            "message"
        ]
    )

    await gateway.process_event(
        private_event(
            user_id=MASTER_QQ,
            text=(
                "/qq shutdown "
                "emergency-secret"
            ),
            message_id=31,
        )
    )
    await asyncio.sleep(0.05)

    assert gateway._stop_event.is_set()
    assert agent.stopped
    assert not client.connected
    assert (
        "正在停止"
        in client.private_messages[-1][
            "message"
        ]
    )

    audit_text = (
        root / "qq.jsonl"
    ).read_text(
        encoding="utf-8"
    )
    assert (
        "emergency-secret"
        not in audit_text
    )


async def duplicate_and_group_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        _config,
    ) = await start_gateway(root)
    try:
        event = private_event(
            user_id=MASTER_QQ,
            text="只处理一次",
            message_id=40,
        )
        await gateway.process_event(
            event
        )
        await gateway.process_event(
            event
        )
        assert len(agent.received) == 1

        await gateway.process_event(
            group_event(
                user_id=MASTER_QQ,
                text="群里问一句",
                message_id=41,
            )
        )
        assert len(agent.received) == 1
        assert not (
            client.group_messages
        )
    finally:
        await gateway.stop()


async def group_mode_case(
    root: Path,
) -> None:
    (
        gateway,
        client,
        agent,
        _config,
    ) = await start_gateway(
        root,
        allow_master_group_message=True,
    )
    try:
        await gateway.process_event(
            group_event(
                user_id=MASTER_QQ,
                text="群里允许回复",
                message_id=50,
            )
        )
        assert len(agent.received) == 1
        assert (
            client.group_messages[-1]
            ["message"]
            == "银狼回复：群里允许回复"
        )
    finally:
        await gateway.stop()


async def sink_case() -> None:
    client = FakeOneBotClient()
    private_sink = QQMessageSink(
        client=client,
        user_id=MASTER_QQ,
    )
    group_sink = QQMessageSink(
        client=client,
        group_id=123123123,
    )
    message = OutboundMessage(
        content="测试发送",
        weight=100,
        category="test",
        source="interactive",
    )
    await private_sink.send(
        message
    )
    await group_sink.send(
        message
    )
    assert (
        client.private_messages[-1]
        ["user_id"]
        == MASTER_QQ
    )
    assert (
        client.group_messages[-1]
        ["group_id"]
        == 123123123
    )


def run() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        test_config_validation(
            root
        )
        test_message_extraction()

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            master_message_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            non_master_message_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            friend_request_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            account_info_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            emergency_shutdown_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            duplicate_and_group_case(
                Path(value)
            )
        )

    with tempfile.TemporaryDirectory() as value:
        asyncio.run(
            group_mode_case(
                Path(value)
            )
        )

    asyncio.run(
        sink_case()
    )

    print(
        "lv16_qq_gateway_test: OK"
    )


if __name__ == "__main__":
    run()
