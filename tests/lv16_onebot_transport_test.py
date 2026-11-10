from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from websockets.asyncio.server import (
    serve,
)

from silverwolf_agent.qq import (
    OneBot11Client,
)


async def transport_case() -> None:
    received_actions: list[
        dict
    ] = []
    received_events: list[
        dict
    ] = []
    authorized = (
        asyncio.Event()
    )
    event_received = (
        asyncio.Event()
    )

    async def event_handler(
        event: dict,
    ) -> None:
        received_events.append(
            event
        )
        event_received.set()

    async def handler(
        connection,
    ) -> None:
        auth = connection.request.headers.get(
            "Authorization",
            "",
        )
        if auth == "Bearer transport-token":
            authorized.set()

        async for raw in connection:
            request = json.loads(raw)
            received_actions.append(
                request
            )
            action = request[
                "action"
            ]
            echo = request.get(
                "echo"
            )

            if action == "get_login_info":
                data = {
                    "user_id": 987654321,
                    "nickname": (
                        "银狼传输测试"
                    ),
                }
            elif action == "get_status":
                data = {
                    "online": True,
                    "good": True,
                }
            elif action == "send_private_msg":
                assert (
                    request["params"][
                        "user_id"
                    ]
                    == 123456789
                )
                assert (
                    request["params"][
                        "message"
                    ]
                    == "测试消息"
                )
                data = {
                    "message_id": 42,
                }
            else:
                data = {}

            await connection.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": data,
                        "echo": echo,
                    },
                    ensure_ascii=False,
                )
            )

            if action == "get_status":
                await connection.send(
                    json.dumps(
                        {
                            "time": 1785859200,
                            "self_id": (
                                987654321
                            ),
                            "post_type": (
                                "message"
                            ),
                            "message_type": (
                                "private"
                            ),
                            "sub_type": (
                                "friend"
                            ),
                            "message_id": 99,
                            "user_id": (
                                123456789
                            ),
                            "message": (
                                "来自真实WS的事件"
                            ),
                            "raw_message": (
                                "来自真实WS的事件"
                            ),
                            "sender": {
                                "nickname": "主人",
                            },
                        },
                        ensure_ascii=False,
                    )
                )

    async with serve(
        handler,
        "127.0.0.1",
        0,
    ) as server:
        port = server.sockets[0].getsockname()[1]
        client = OneBot11Client(
            websocket_url=(
                f"ws://127.0.0.1:{port}"
            ),
            access_token=(
                "transport-token"
            ),
            action_timeout_seconds=5,
            reconnect_initial_seconds=1,
            reconnect_max_seconds=2,
            ping_interval_seconds=10,
            ping_timeout_seconds=10,
        )
        client.set_event_handler(
            event_handler
        )

        await client.start()
        try:
            await client.wait_until_ready(
                timeout=5
            )
            await asyncio.wait_for(
                authorized.wait(),
                timeout=5,
            )

            login = (
                await client
                .get_login_info()
            )
            assert login == {
                "user_id": 987654321,
                "nickname": (
                    "银狼传输测试"
                ),
            }

            status = (
                await client.get_status()
            )
            assert status == {
                "online": True,
                "good": True,
            }

            result = (
                await client
                .send_private_msg(
                    user_id=123456789,
                    message="测试消息",
                )
            )
            assert result == {
                "message_id": 42,
            }

            await asyncio.wait_for(
                event_received.wait(),
                timeout=5,
            )
            assert (
                received_events[-1][
                    "raw_message"
                ]
                == "来自真实WS的事件"
            )
            assert [
                item["action"]
                for item
                in received_actions
            ] == [
                "get_login_info",
                "get_status",
                "send_private_msg",
            ]
        finally:
            await client.stop()

    assert not client.connected


def run() -> None:
    asyncio.run(
        transport_case()
    )
    print(
        "lv16_onebot_transport_test: OK"
    )


if __name__ == "__main__":
    run()
