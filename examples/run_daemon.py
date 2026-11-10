from __future__ import annotations

import asyncio
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

from silverwolf_agent import (
    ConsoleMessageSink,
    SilverWolfAgent,
)


async def main() -> None:
    agent = SilverWolfAgent()
    sink = ConsoleMessageSink()

    print(
        "银狼lv18 主动任务进程已启动。"
    )
    print(
        "保持这个进程运行，"
        "到点后会触发主动消息。"
    )

    await agent.start(sink)
    try:
        while True:
            await asyncio.sleep(3600)
    except (
        KeyboardInterrupt,
        asyncio.CancelledError,
    ):
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
