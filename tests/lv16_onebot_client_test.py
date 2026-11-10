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

from silverwolf_agent.qq.onebot import (
    OneBot11Client,
    OneBotActionError,
)


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(
        self,
        value: str,
    ) -> None:
        self.sent.append(
            value
        )


async def success_case() -> None:
    client = OneBot11Client(
        websocket_url=(
            "ws://127.0.0.1:3001"
        ),
        access_token="token",
        action_timeout_seconds=2,
    )
    socket = FakeSocket()
    client._socket = socket
    client._ready_event.set()

    task = asyncio.create_task(
        client.call_action(
            "get_login_info"
        )
    )
    while not socket.sent:
        await asyncio.sleep(0)

    request = json.loads(
        socket.sent[0]
    )
    assert request["action"] == (
        "get_login_info"
    )
    assert request["params"] == {}
    echo = request["echo"]

    future = client._pending[
        echo
    ]
    future.set_result(
        {
            "status": "ok",
            "retcode": 0,
            "data": {
                "user_id": 123,
                "nickname": "银狼",
            },
            "echo": echo,
        }
    )

    data = await task
    assert data == {
        "user_id": 123,
        "nickname": "银狼",
    }
    assert echo not in (
        client._pending
    )


async def error_case() -> None:
    client = OneBot11Client(
        websocket_url=(
            "ws://127.0.0.1:3001"
        ),
        access_token="token",
        action_timeout_seconds=2,
    )
    socket = FakeSocket()
    client._socket = socket
    client._ready_event.set()

    task = asyncio.create_task(
        client.call_action(
            "send_private_msg",
            {
                "user_id": 123,
                "message": "test",
            },
        )
    )
    while not socket.sent:
        await asyncio.sleep(0)

    request = json.loads(
        socket.sent[0]
    )
    echo = request["echo"]
    client._pending[
        echo
    ].set_result(
        {
            "status": "failed",
            "retcode": 1404,
            "wording": "not found",
            "data": None,
            "echo": echo,
        }
    )

    try:
        await task
    except OneBotActionError as exc:
        assert "1404" in str(
            exc
        )
    else:
        raise AssertionError(
            "failed action must raise"
        )


async def event_response_split_case() -> None:
    events: list[dict] = []
    client = OneBot11Client(
        websocket_url=(
            "ws://127.0.0.1:3001"
        ),
        access_token="token",
    )

    async def handler(
        event: dict,
    ) -> None:
        events.append(
            event
        )

    client.set_event_handler(
        handler
    )

    class IteratorSocket:
        def __init__(self) -> None:
            self.values = iter(
                [
                    json.dumps(
                        {
                            "post_type": (
                                "message"
                            ),
                            "message_type": (
                                "private"
                            ),
                            "user_id": 123,
                        }
                    )
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(
            self,
        ):
            try:
                return next(
                    self.values
                )
            except StopIteration:
                raise StopAsyncIteration

    await client._receive_loop(
        IteratorSocket()
    )
    await asyncio.sleep(0)
    assert len(events) == 1
    assert events[0][
        "post_type"
    ] == "message"


def run() -> None:
    asyncio.run(
        success_case()
    )
    asyncio.run(
        error_case()
    )
    asyncio.run(
        event_response_split_case()
    )
    print(
        "lv16_onebot_client_test: OK"
    )


if __name__ == "__main__":
    run()
