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

from silverwolf_agent import (
    ConsoleMessageSink,
    SilverWolfAgent,
)


def parse_value(
    raw: str,
):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


async def main() -> None:
    agent = SilverWolfAgent()
    sink = ConsoleMessageSink()

    mode = (
        "离线测试"
        if agent.offline
        else (
            "真实模型："
            + agent.config.model
        )
    )
    print(
        f"银狼lv18 已上线（{mode}）。"
    )
    print(
        "后台主动关心已启动；"
        "进程关闭后调度也会停止。"
    )
    print(
        "命令：/summary /profile "
        "/profile set 路径 值 "
        "/memory /pae /plans "
        "/plan cancel 关键词 "
        "/time /time set 槽位 HH:MM "
        "/proactive on|off /tick /exit"
    )

    await agent.start(sink)

    try:
        while True:
            try:
                user_input = (
                    await asyncio.to_thread(
                        input,
                        "你> ",
                    )
                ).strip()
            except (
                EOFError,
                KeyboardInterrupt,
            ):
                print(
                    "\n银狼lv18> "
                    "存档完成。下线。"
                )
                break

            if not user_input:
                continue

            if user_input == "/exit":
                print(
                    "银狼lv18> "
                    "存档完成。下线。"
                )
                break

            if user_input == "/summary":
                summary = (
                    await asyncio.to_thread(
                        agent
                        .generate_daily_summary
                    )
                )
                print(
                    "银狼lv18> "
                    + summary
                )
                continue

            if user_input == "/profile":
                profile = (
                    agent.profile
                    .prompt_view(
                        agent.now().date()
                    )
                )
                print(
                    json.dumps(
                        profile,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            if user_input.startswith(
                "/profile set "
            ):
                rest = user_input[
                    len("/profile set "):
                ].strip()
                path, sep, raw_value = (
                    rest.partition(" ")
                )
                if not sep:
                    print(
                        "银狼lv18> 格式："
                        "/profile set 路径 值"
                    )
                    continue

                try:
                    agent.profile.set_path(
                        path,
                        parse_value(
                            raw_value
                        ),
                        reason=(
                            "cli_manual_update"
                        ),
                    )
                    print(
                        "银狼lv18> "
                        f"档案字段 {path} "
                        "已更新。"
                    )
                except Exception as exc:
                    print(
                        "银狼lv18> "
                        f"更新失败：{exc}"
                    )
                continue

            if user_input == "/memory":
                print(
                    json.dumps(
                        agent.memory
                        .snapshot(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            # Lv33: 只读体检（人话结论，不修任何东西）
            if user_input == "/doctor":
                print(agent.doctor_report()["text"])
                continue

            # Lv33: 精简总览
            if user_input == "/status":
                print(agent.status_report()["text"])
                continue

            # Lv30: 人设分层状态（可带一句试算：/persona 晚上提醒我吃药）
            if user_input.startswith("/persona"):
                parts = user_input.split(maxsplit=1)
                probe = parts[1] if len(parts) > 1 else ""
                print(
                    json.dumps(
                        agent.persona_snapshot(probe),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            # Lv28: 记忆健康度（重要度分布 + 反思状态）
            if user_input == "/memory-stats":
                print(
                    json.dumps(
                        agent.memory_snapshot(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            # Lv28: 手动跑一次每周反思（不影响正常对话）
            if user_input == "/reflect":
                print(
                    json.dumps(
                        agent.maybe_reflect(
                            trigger="manual",
                            force=True,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            # Lv29: 语料生长 —— 待审 / 转正 / 拒绝 / 查看 / 统计 / 手工添加
            if user_input.startswith("/corpus"):
                parts = user_input.split(maxsplit=3)
                action = parts[1] if len(parts) > 1 else "stats"
                now = agent.now()
                learner = agent.corpus_learner
                if action in {"review", "待审"}:
                    payload = learner.review(limit=10)
                elif action in {"approve", "过"} and len(parts) > 2:
                    payload = learner.approve(parts[2], now)
                elif action in {"reject", "拒"} and len(parts) > 2:
                    payload = {"rejected": learner.reject(parts[2], now)}
                elif action in {"retire", "撤"} and len(parts) > 2:
                    payload = {"retired": learner.retire(parts[2], now)}
                elif action in {"list", "列表"}:
                    payload = learner.list_learned(
                        parts[2] if len(parts) > 2 else None,
                    )
                elif action in {"add", "加"} and len(parts) > 3:
                    payload = learner.add_manual(
                        parts[3],
                        scene=parts[2],
                        now=now,
                    )
                else:
                    payload = agent.corpus_snapshot()
                print(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            if user_input == "/pae":
                print(
                    agent.pae_debug()
                )
                continue

            if user_input == "/plans":
                print(
                    json.dumps(
                        agent.plans_snapshot(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            if user_input.startswith(
                "/plan cancel "
            ):
                query = user_input[
                    len("/plan cancel "):
                ].strip()
                cancelled = (
                    agent.plan_manager
                    .cancel_by_query(
                        query
                    )
                )
                print(
                    "银狼lv18> "
                    + (
                        "相关计划已取消。"
                        if cancelled
                        else (
                            "没有找到对应计划。"
                        )
                    )
                )
                continue

            if user_input == "/time":
                print(
                    json.dumps(
                        agent.time_snapshot(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue

            if user_input.startswith(
                "/time set "
            ):
                rest = user_input[
                    len("/time set "):
                ].strip()
                slot, sep, value = (
                    rest.partition(" ")
                )
                if not sep:
                    print(
                        "银狼lv18> 格式："
                        "/time set "
                        "morning|noon|evening "
                        "HH:MM"
                    )
                    continue

                try:
                    result = (
                        agent.time_manager
                        .set_slot(
                            slot,
                            value,
                        )
                    )
                    print(
                        "银狼lv18> "
                        f"{slot} 已调整为 "
                        f"{result['time']}。"
                    )
                except Exception as exc:
                    print(
                        "银狼lv18> "
                        f"修改失败：{exc}"
                    )
                continue

            if user_input in {
                "/proactive on",
                "/proactive off",
            }:
                enabled = (
                    user_input.endswith(
                        "on"
                    )
                )
                agent.time_manager.set_proactive_enabled(
                    enabled
                )
                print(
                    "银狼lv18> 主动关心"
                    + (
                        "已开启。"
                        if enabled
                        else "已关闭。"
                    )
                )
                continue

            if user_input == "/tick":
                bundle = (
                    await agent
                    .run_proactive_once(
                        sink
                    )
                )
                if bundle is None:
                    print(
                        "银狼lv18> "
                        "现在没有到期的"
                        "主动消息。"
                    )
                continue

            try:
                await agent.handle_user_message(
                    user_input,
                    sink,
                )
            except Exception as exc:
                print(
                    "\n银狼lv18> "
                    f"接口出了点 Bug：{exc}"
                )
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
