from __future__ import annotations

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

from silverwolf_agent.webapp import (
    create_app,
)


app = create_app()


if __name__ == "__main__":
    print(
        "银狼lv18 测试前端："
        "http://127.0.0.1:5000"
    )
    print(
        "请保持这个进程运行，"
        "主动消息才会持续推送。"
    )
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
