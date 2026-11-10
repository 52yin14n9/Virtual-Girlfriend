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


async def integration_case() -> None:
    received_headers: list[str] = []
    action_names: list[str] = []
    event_received = (
        asyncio.Event()
    )
    events: list[dict] = []

    async def handler(
        connection,
    ) -> None:
        authorization = (
            connection.request.headers.get(
                "Authorization",
                "",
            )
        )
        received_headers.append(
            authorization
        )

        async for raw in connection:
            request = json.loads(
                raw
            )
            action = request[
                "action"
            ]
            action_names.append(
                action
            )

            if action == "get_login_info":
                data = {
                    "user_id": 987654321,
                    "nickname": (
                        "银狼集成测试号"
                    ),
                }
            elif action == "get_status":
                data = {
                    "online": True,
                    "good": True,
                }
            else:
                data = {}

            await connection.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": data,
                        "echo": request[
                            "echo"
                        ],
                    },
                    ensure_ascii=False,
                )
            )

            if action == "get_login_info":
                await connection.send(
                    json.dumps(
                        {
                            "time": 1785859200,
                            "self_id": 987654321,
                            "post_type": (
                                "message"
                            ),
                            "message_type": (
                                "private"
                            ),
                            "sub_type": (
                                "friend"
                            ),
                            "message_id": 9001,
                            "user_id": 123456789,
                            "message": (
                                "集成事件"
                            ),
                            "raw_message": (
                                "集成事件"
                            ),
                            "sender": {
                                "nickname": (
                                    "主人"
                                )
                            },
                        },
                        ensure_ascii=False,
                    )
                )

    server = await serve(
        handler,
        "127.0.0.1",
        0,
        ping_interval=None,
    )
    port = server.sockets[
        0
    ].getsockname()[1]

    client = OneBot11Client(
        websocket_url=(
            f"ws://127.0.0.1:{port}"
        ),
        access_token=(
            "integration-token"
        ),
        action_timeout_seconds=5,
        reconnect_initial_seconds=0.5,
        reconnect_max_seconds=1,
        ping_interval_seconds=10,
        ping_timeout_seconds=10,
    )

    async def on_event(
        event: dict,
    ) -> None:
        events.append(
            event
        )
        event_received.set()

    client.set_event_handler(
        on_event
    )

    try:
        await client.start()
        await client.wait_until_ready(
            timeout=5
        )

        login = await (
            client.get_login_info()
        )
        status = await (
            client.get_status()
        )

        await asyncio.wait_for(
            event_received.wait(),
            timeout=5,
        )

        assert login == {
            "user_id": 987654321,
            "nickname": (
                "银狼集成测试号"
            ),
        }
        assert status[
            "online"
        ] is True
        assert received_headers == [
            (
                "Bearer "
                "integration-token"
            )
        ]
        assert action_names == [
            "get_login_info",
            "get_status",
        ]
        assert len(events) == 1
        assert events[0][
            "message_id"
        ] == 9001
    finally:
        await client.stop()
        server.close()
        await server.wait_closed()


def run() -> None:
    asyncio.run(
        integration_case()
    )
    print(
        "lv16_onebot_websocket_integration_test: OK"
    )


if __name__ == "__main__":
    run()
