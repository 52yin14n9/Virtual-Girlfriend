from __future__ import annotations

from ..delivery import (
    MessageSink,
    OutboundMessage,
)
from .onebot import OneBot11Client


class QQMessageSink(
    MessageSink
):
    """
    把 Agent 的 OutboundMessage 发送到指定 QQ 私聊或群聊。
    """

    def __init__(
        self,
        *,
        client: OneBot11Client,
        user_id: int | None = None,
        group_id: int | None = None,
    ) -> None:
        if (
            user_id is None
            and group_id is None
        ):
            raise ValueError(
                "QQMessageSink 必须指定 user_id 或 group_id"
            )
        if (
            user_id is not None
            and group_id is not None
        ):
            raise ValueError(
                "QQMessageSink 不能同时指定 user_id 和 group_id"
            )

        self.client = client
        self.user_id = user_id
        self.group_id = group_id

    async def send(
        self,
        message: OutboundMessage,
    ) -> None:
        if self.user_id is not None:
            await self.client.send_private_msg(
                user_id=self.user_id,
                message=message.content,
            )
            return

        assert self.group_id is not None
        await self.client.send_group_msg(
            group_id=self.group_id,
            message=message.content,
        )
