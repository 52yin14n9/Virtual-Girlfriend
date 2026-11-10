from __future__ import annotations

import asyncio
import json
import uuid
from typing import (
    Any,
    Awaitable,
    Callable,
)

try:
    from websockets.asyncio.client import (
        connect,
    )
    from websockets.exceptions import (
        ConnectionClosed,
    )
except ImportError:  # pragma: no cover - deployment dependency
    connect = None
    ConnectionClosed = Exception


class OneBotActionError(
    RuntimeError
):
    pass


class OneBotNotConnectedError(
    RuntimeError
):
    pass


EventHandler = Callable[
    [dict[str, Any]],
    Awaitable[None],
]


class OneBot11Client:
    """
    OneBot 11 正向 WebSocket 客户端。

    同一连接同时承载：
    - OneBot 事件上报；
    - 带 echo 的动作请求与响应。
    """

    def __init__(
        self,
        *,
        websocket_url: str,
        access_token: str = "",
        action_timeout_seconds: float = 15.0,
        reconnect_initial_seconds: float = 2.0,
        reconnect_max_seconds: float = 30.0,
        ping_interval_seconds: float = 20.0,
        ping_timeout_seconds: float = 20.0,
    ) -> None:
        self.websocket_url = (
            websocket_url
        )
        self.access_token = (
            access_token
        )
        self.action_timeout_seconds = max(
            1.0,
            float(
                action_timeout_seconds
            ),
        )
        self.reconnect_initial_seconds = max(
            0.5,
            float(
                reconnect_initial_seconds
            ),
        )
        self.reconnect_max_seconds = max(
            self.reconnect_initial_seconds,
            float(
                reconnect_max_seconds
            ),
        )
        self.ping_interval_seconds = max(
            5.0,
            float(
                ping_interval_seconds
            ),
        )
        self.ping_timeout_seconds = max(
            5.0,
            float(
                ping_timeout_seconds
            ),
        )

        self._event_handler: (
            EventHandler
            | None
        ) = None
        self._socket: Any = None
        self._runner: (
            asyncio.Task[None]
            | None
        ) = None
        self._stop_event = (
            asyncio.Event()
        )
        self._ready_event = (
            asyncio.Event()
        )
        self._send_lock = (
            asyncio.Lock()
        )
        self._pending: dict[
            str,
            asyncio.Future[
                dict[str, Any]
            ],
        ] = {}
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._ready_event.is_set()

    def set_event_handler(
        self,
        handler: EventHandler,
    ) -> None:
        self._event_handler = handler

    async def start(self) -> None:
        if (
            self._runner is not None
            and not self._runner.done()
        ):
            return
        if connect is None:
            raise RuntimeError(
                "缺少 websockets 依赖，请先运行 "
                "pip install -r requirements.txt"
            )

        self._stop_event.clear()
        self._runner = (
            asyncio.create_task(
                self._run_forever(),
                name=(
                    "silverwolf-onebot-client"
                ),
            )
        )

    async def stop(self) -> None:
        self._stop_event.set()
        self._ready_event.clear()

        socket = self._socket
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                pass

        if self._runner is not None:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            finally:
                self._runner = None

        self._fail_pending(
            OneBotNotConnectedError(
                "OneBot 客户端已停止"
            )
        )

    async def wait_until_ready(
        self,
        timeout: float = 30.0,
    ) -> None:
        await asyncio.wait_for(
            self._ready_event.wait(),
            timeout=max(
                1.0,
                timeout,
            ),
        )

    async def call_action(
        self,
        action: str,
        params: (
            dict[str, Any]
            | None
        ) = None,
    ) -> Any:
        await self.wait_until_ready(
            timeout=(
                self.action_timeout_seconds
            )
        )
        socket = self._socket
        if socket is None:
            raise OneBotNotConnectedError(
                "OneBot WebSocket 尚未连接"
            )

        echo = str(
            uuid.uuid4()
        )
        loop = (
            asyncio.get_running_loop()
        )
        future: asyncio.Future[
            dict[str, Any]
        ] = loop.create_future()
        self._pending[echo] = future

        payload = {
            "action": action,
            "params": params or {},
            "echo": echo,
        }

        try:
            async with self._send_lock:
                await socket.send(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                )

            response = await asyncio.wait_for(
                future,
                timeout=(
                    self.action_timeout_seconds
                ),
            )
        finally:
            self._pending.pop(
                echo,
                None,
            )

        status = str(
            response.get(
                "status",
                "",
            )
        )
        retcode = int(
            response.get(
                "retcode",
                -1,
            )
        )
        if (
            status != "ok"
            or retcode != 0
        ):
            raise OneBotActionError(
                f"OneBot action={action} 执行失败："
                f"status={status}, retcode={retcode}, "
                f"wording={response.get('wording', '')}"
            )
        return response.get(
            "data"
        )

    async def send_private_msg(
        self,
        *,
        user_id: int,
        message: str,
    ) -> Any:
        return await self.call_action(
            "send_private_msg",
            {
                "user_id": int(
                    user_id
                ),
                "message": str(
                    message
                ),
                "auto_escape": True,
            },
        )

    async def send_group_msg(
        self,
        *,
        group_id: int,
        message: str,
    ) -> Any:
        return await self.call_action(
            "send_group_msg",
            {
                "group_id": int(
                    group_id
                ),
                "message": str(
                    message
                ),
                "auto_escape": True,
            },
        )

    async def set_friend_add_request(
        self,
        *,
        flag: str,
        approve: bool,
        remark: str = "",
    ) -> Any:
        return await self.call_action(
            "set_friend_add_request",
            {
                "flag": flag,
                "approve": bool(
                    approve
                ),
                "remark": (
                    remark
                    if approve
                    else ""
                ),
            },
        )

    async def get_login_info(
        self,
    ) -> dict[str, Any]:
        data = await self.call_action(
            "get_login_info"
        )
        return (
            dict(data)
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    async def get_status(
        self,
    ) -> dict[str, Any]:
        data = await self.call_action(
            "get_status"
        )
        return (
            dict(data)
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    async def get_version_info(
        self,
    ) -> dict[str, Any]:
        data = await self.call_action(
            "get_version_info"
        )
        return (
            dict(data)
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    async def get_stranger_info(
        self,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        data = await self.call_action(
            "get_stranger_info",
            {
                "user_id": int(
                    user_id
                ),
                "no_cache": False,
            },
        )
        return (
            dict(data)
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    async def _run_forever(
        self,
    ) -> None:
        delay = (
            self.reconnect_initial_seconds
        )

        while not (
            self._stop_event.is_set()
        ):
            headers = (
                {
                    "Authorization": (
                        "Bearer "
                        + self.access_token
                    )
                }
                if self.access_token
                else None
            )

            try:
                assert connect is not None
                async with connect(
                    self.websocket_url,
                    additional_headers=headers,
                    ping_interval=(
                        self.ping_interval_seconds
                    ),
                    ping_timeout=(
                        self.ping_timeout_seconds
                    ),
                    open_timeout=15,
                    close_timeout=10,
                    max_size=4 * 1024 * 1024,
                    proxy=None,
                ) as socket:
                    self._socket = socket
                    self._ready_event.set()
                    self.last_error = None
                    delay = (
                        self.reconnect_initial_seconds
                    )
                    await self._receive_loop(
                        socket
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(
                    exc
                )
            finally:
                self._ready_event.clear()
                self._socket = None
                self._fail_pending(
                    OneBotNotConnectedError(
                        "OneBot WebSocket 已断开"
                    )
                )

            if self._stop_event.is_set():
                break

            await asyncio.sleep(
                delay
            )
            delay = min(
                self.reconnect_max_seconds,
                delay * 2,
            )

    async def _receive_loop(
        self,
        socket: Any,
    ) -> None:
        try:
            async for raw in socket:
                try:
                    payload = json.loads(
                        raw
                    )
                except (
                    TypeError,
                    json.JSONDecodeError,
                ):
                    continue

                if not isinstance(
                    payload,
                    dict,
                ):
                    continue

                echo = payload.get(
                    "echo"
                )
                if echo is not None:
                    future = (
                        self._pending.pop(
                            str(echo),
                            None,
                        )
                    )
                    if (
                        future is not None
                        and not future.done()
                    ):
                        future.set_result(
                            payload
                        )
                    continue

                if (
                    self._event_handler
                    is not None
                ):
                    asyncio.create_task(
                        self._event_handler(
                            payload
                        ),
                        name=(
                            "silverwolf-onebot-event"
                        ),
                    )
        except ConnectionClosed:
            return

    def _fail_pending(
        self,
        error: Exception,
    ) -> None:
        pending = list(
            self._pending.values()
        )
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(
                    error
                )
