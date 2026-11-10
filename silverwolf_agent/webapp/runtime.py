from __future__ import annotations

import asyncio
from concurrent.futures import Future
from datetime import datetime
import threading
from typing import Any

from .message_store import (
    MessageStore,
)
from ..agent import SilverWolfAgent
from ..delivery import (
    MessageSink,
    OutboundMessage,
)


class BrowserMessageSink(
    MessageSink
):
    def __init__(
        self,
        *,
        store: MessageStore,
        agent: SilverWolfAgent,
    ) -> None:
        self.store = store
        self.agent = agent

    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        self.store.publish(
            role="assistant",
            content=message.content,
            timestamp=self.agent.now(),
            source=message.source,
            weight=message.weight,
            category=message.category,
            metadata={
                **message.metadata,
                "message_id": (
                    message.message_id
                ),
                "goal_kinds": (
                    message.goal_kinds
                ),
            },
        )


class AsyncAgentRuntime:
    """
    在独立线程中维护一个长期 asyncio 事件循环。

    Flask 请求线程通过
    run_coroutine_threadsafe 提交对话；
    Agent 的主动调度器也运行在同一个循环中。
    """

    def __init__(
        self,
        *,
        agent: SilverWolfAgent,
        store: MessageStore,
    ) -> None:
        self.agent = agent
        self.store = store
        self.sink = BrowserMessageSink(
            store=store,
            agent=agent,
        )

        self._loop = (
            asyncio.new_event_loop()
        )
        self._thread = threading.Thread(
            target=self._thread_main,
            name=(
                "silverwolf-web-runtime"
            ),
            daemon=True,
        )
        self._started = (
            threading.Event()
        )
        self._stopped = (
            threading.Event()
        )
        self._start_error: (
            BaseException
            | None
        ) = None

    @property
    def running(self) -> bool:
        return (
            self._thread.is_alive()
            and self._started.is_set()
            and self._start_error
            is None
        )

    def start(
        self,
        timeout: float = 10.0,
    ) -> None:
        if self._thread.is_alive():
            return

        self._thread.start()
        if not self._started.wait(
            timeout=timeout
        ):
            raise RuntimeError(
                "Agent 后台事件循环"
                "启动超时"
            )
        if (
            self._start_error
            is not None
        ):
            raise RuntimeError(
                "Agent 后台启动失败"
            ) from self._start_error

    def _thread_main(self) -> None:
        asyncio.set_event_loop(
            self._loop
        )
        try:
            self._loop.run_until_complete(
                self.agent.start(
                    self.sink
                )
            )
        except BaseException as exc:
            self._start_error = exc
            self._started.set()
            self._stopped.set()
            self._loop.close()
            return

        self._started.set()
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(
                    self.agent.stop()
                )
            finally:
                self._loop.close()
                self._stopped.set()

    def submit_user_message(
        self,
        text: str,
        *,
        received_at: datetime,
    ) -> Future[Any]:
        self._require_running()
        future = (
            asyncio.run_coroutine_threadsafe(
                self.agent
                .handle_user_message(
                    text,
                    self.sink,
                    received_at=(
                        received_at
                    ),
                ),
                self._loop,
            )
        )
        future.add_done_callback(
            self._report_error
        )
        return future

    def trigger_proactive_once(
        self,
    ) -> Future[Any]:
        self._require_running()
        future = (
            asyncio.run_coroutine_threadsafe(
                self.agent
                .run_proactive_once(
                    self.sink
                ),
                self._loop,
            )
        )
        future.add_done_callback(
            self._report_error
        )
        return future

    def _report_error(
        self,
        future: Future[Any],
    ) -> None:
        try:
            future.result()
        except BaseException as exc:
            self.store.publish(
                role="system",
                content=(
                    "消息处理失败："
                    + str(exc)
                ),
                timestamp=(
                    self.agent.now()
                ),
                source="system",
                weight=100,
                category="error",
            )

    def _require_running(
        self,
    ) -> None:
        if not self.running:
            raise RuntimeError(
                "Agent 后台运行时"
                "尚未启动"
            )

    def stop(
        self,
        timeout: float = 10.0,
    ) -> None:
        if not self._thread.is_alive():
            return

        try:
            future = (
                asyncio.run_coroutine_threadsafe(
                    self.agent.stop(),
                    self._loop,
                )
            )
            future.result(
                timeout=timeout
            )
        except BaseException:
            pass

        self._loop.call_soon_threadsafe(
            self._loop.stop
        )
        self._stopped.wait(
            timeout=timeout
        )
