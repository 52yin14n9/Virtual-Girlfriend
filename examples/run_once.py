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
    await agent.run_proactive_once(
        sink
    )


if __name__ == "__main__":
    asyncio.run(main())
