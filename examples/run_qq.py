from __future__ import annotations

import asyncio
import signal

from silverwolf_agent import (
    SilverWolfAgent,
)
from silverwolf_agent.qq import (
    QQBotConfig,
    QQGateway,
)


async def main() -> None:
    config = QQBotConfig.from_env()
    config.validate()

    agent = SilverWolfAgent()
    gateway = QQGateway(
        config=config,
        agent=agent,
    )

    loop = asyncio.get_running_loop()

    async def shutdown() -> None:
        await gateway.stop()

    def request_shutdown() -> None:
        asyncio.create_task(
            shutdown()
        )

    for name in (
        "SIGINT",
        "SIGTERM",
    ):
        sig = getattr(
            signal,
            name,
            None,
        )
        if sig is None:
            continue
        try:
            loop.add_signal_handler(
                sig,
                request_shutdown,
            )
        except (
            NotImplementedError,
            RuntimeError,
        ):
            pass

    print(
        "银狼 lv18 QQ 网关正在连接 OneBot..."
    )
    print(
        f"主人 QQ：{config.master_qq}"
    )
    print(
        f"WebSocket：{config.websocket_url}"
    )

    try:
        await gateway.run_forever()
    finally:
        await gateway.stop()


if __name__ == "__main__":
    asyncio.run(
        main()
    )
