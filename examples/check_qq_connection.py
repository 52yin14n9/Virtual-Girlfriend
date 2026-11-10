from __future__ import annotations

import asyncio

from silverwolf_agent.qq import (
    OneBot11Client,
    QQBotConfig,
)


async def main() -> None:
    config = QQBotConfig.from_env()
    if not config.enabled:
        raise RuntimeError(
            "请先在 .env 中设置 QQ_BOT_ENABLED=true"
        )
    config.validate()

    client = OneBot11Client(
        websocket_url=(
            config.websocket_url
        ),
        access_token=(
            config.access_token
        ),
        action_timeout_seconds=(
            config.action_timeout_seconds
        ),
        reconnect_initial_seconds=(
            config.reconnect_initial_seconds
        ),
        reconnect_max_seconds=(
            config.reconnect_max_seconds
        ),
        ping_interval_seconds=(
            config.ping_interval_seconds
        ),
        ping_timeout_seconds=(
            config.ping_timeout_seconds
        ),
    )

    try:
        print(
            "正在连接 OneBot WebSocket："
            + config.websocket_url
        )
        await client.start()
        await client.wait_until_ready(
            timeout=45
        )

        login = await client.get_login_info()
        status = await client.get_status()
        try:
            version = (
                await client
                .get_version_info()
            )
        except Exception as exc:
            version = {
                "error": str(exc),
            }

        print("连接成功。")
        print(
            "QQ号："
            + str(
                login.get(
                    "user_id",
                    "未知",
                )
            )
        )
        print(
            "昵称："
            + str(
                login.get(
                    "nickname",
                    "未知",
                )
            )
        )
        print(
            "在线状态："
            + str(
                status.get(
                    "online",
                    "未知",
                )
            )
        )
        print(
            "运行状态："
            + str(
                status.get(
                    "good",
                    "未知",
                )
            )
        )
        print(
            "OneBot实现："
            + str(
                version.get(
                    "app_name",
                    version.get(
                        "app_full_name",
                        "未知",
                    ),
                )
            )
        )

        bot_qq = int(
            login.get(
                "user_id",
                0,
            )
            or 0
        )
        if bot_qq == config.master_qq:
            raise RuntimeError(
                "机器人 QQ 与 MASTER_QQ 相同，"
                "请使用两个不同账号。"
            )

        print(
            "主人 QQ 配置："
            + str(
                config.master_qq
            )
        )
        print(
            "QQ 网关配置自检通过。"
        )
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(
        main()
    )
