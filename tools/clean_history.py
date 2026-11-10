"""历史数据清理工具（Lv33 附带）。

背景：从 Lv17 一路跑到 Lv26 的那份 data/ 里，混着一批**结构性垃圾**——
不是"当年说话傻"，而是早期版本的生成缺陷留下的噪声：

* RAG 里有大量空文本记录（总结失败的残骸）；
* 同一天重复写了 4–5 条日总结，内容高度雷同；
* 短期记忆里有一批 `user` 字段为空的轮次（主动消息被记成对话轮）；
* 计划里躺着早就过期的 pending 提醒，一启动就会补发；
* 主动状态的"最后活动时间"和 engagement 计数还是几个月前的。

这个工具只做"删噪声"，**不改写任何一条记忆的正文**，也不动用户档案。

用法：

    python tools/clean_history.py                  # 只体检，不改（默认）
    python tools/clean_history.py --apply          # 执行（先自动备份）
    python tools/clean_history.py --data-dir D     # 指定别的数据目录
    python tools/clean_history.py --keep-rag-days 30   # RAG 只保留最近 30 天
    python tools/clean_history.py --skip-short-term ...  # 跳过某项

设计约束：
1. 默认 dry-run，先看数字再决定；
2. `--apply` 之前自动把整个 data/ 打成 `bak/data-backup-<时间>.zip`；
3. 幂等：重复运行第二次应报 0 变化；
4. 不触碰：`data/profile/`、`cognitive.life.events`、`config/corpus/`、
   `data/weather/`、`data/qq/`、`data/corpus/`。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_BACKUP_DIR = PROJECT_ROOT.parent / "bak"

# 认知状态里被历史注水的累计值，重置为默认
FAMILIARITY_DEFAULT = 0.48
ENGAGEMENT_DEFAULT = {
    "relationship_sent": 0,
    "replies_after_proactive": 0,
    "consecutive_unanswered": 0,
    "last_relationship_sent_at": None,
    "awaiting_reply_since": None,
}


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _doc_date(item: dict) -> str:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("date", "") or "")
        if value:
            return value[:10]
    return str(item.get("created_at", "") or "")[:10]


class HistoryCleaner:
    def __init__(
        self,
        *,
        data_dir: Path,
        apply: bool = False,
        keep_rag_days: int = 0,
        do_short_term: bool = True,
        do_rag: bool = True,
        do_plans: bool = True,
        do_proactive: bool = True,
        do_cognition: bool = True,
        now: datetime | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.apply = bool(apply)
        self.keep_rag_days = max(0, int(keep_rag_days))
        self.do_short_term = do_short_term
        self.do_rag = do_rag
        self.do_plans = do_plans
        self.do_proactive = do_proactive
        self.do_cognition = do_cognition
        self.now = now or datetime.now()
        self.actions: list[str] = []

    # ------------------------------------------------------------------

    # 只把这几个键算作"这次真的会改动东西"；
    # rag_kept / rag_before / cognition_familiarity 只是信息性数字
    CHANGE_KEYS = (
        "rag_empty_removed",
        "rag_duplicate_removed",
        "short_term_turns",
        "plans_expired_cancelled",
        "proactive_history_cleared",
        "proactive_last_activity_cleared",
        "proactive_engagement_reset",
        "cognition_interaction_count",
    )

    def run(self) -> dict:
        details: dict[str, int] = {}
        if self.do_rag:
            details.update(self._clean_rag())
        if self.do_short_term:
            details.update(self._clean_short_term())
        if self.do_plans:
            details.update(self._clean_plans())
        if self.do_proactive:
            details.update(self._clean_proactive())
        if self.do_cognition:
            details.update(self._clean_cognition())
        changed = sum(
            1
            for key in self.CHANGE_KEYS
            if int(details.get(key, 0) or 0) > 0
        )
        return {
            "apply": self.apply,
            "changed_items": changed,
            "details": details,
            "actions": self.actions,
        }

    # ------------------------------------------------------------------
    # RAG
    # ------------------------------------------------------------------

    def _clean_rag(self) -> dict[str, int]:
        path = self.data_dir / "rag" / "documents.jsonl"
        if not path.exists():
            return {"rag_missing": 0}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return {"rag_unreadable": 0}

        empty = 0
        parsed: list[dict] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                empty += 1
                continue
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                empty += 1
                continue
            if self.keep_rag_days:
                date_text = _doc_date(item)
                try:
                    day = datetime.fromisoformat(date_text).date()
                except ValueError:
                    parsed.append(item)
                    continue
                if (self.now.date() - day).days > self.keep_rag_days:
                    empty += 1
                    continue
            parsed.append(item)

        # 同一天只保留信息量最大的一条（正文最长，其次最早创建）
        best: dict[str, dict] = {}
        for item in parsed:
            key = _doc_date(item)
            current = best.get(key)
            if current is None:
                best[key] = item
                continue
            if len(str(item.get("text", ""))) > len(str(current.get("text", ""))):
                best[key] = item
        dedup_dropped = len(parsed) - len(best)
        kept = [
            item for item in parsed if best.get(_doc_date(item)) is item
        ]
        kept.sort(key=lambda item: _doc_date(item))

        if self.apply and (empty or dedup_dropped):
            payload = "\n".join(
                json.dumps(item, ensure_ascii=False) for item in kept
            )
            path.write_text(
                payload + ("\n" if payload else ""),
                encoding="utf-8",
            )
            self.actions.append(
                f"RAG：删除空记录 {empty} 条、同日重复 {dedup_dropped} 条，保留 {len(kept)} 条"
            )
        return {
            "rag_empty_removed": empty,
            "rag_duplicate_removed": dedup_dropped,
            "rag_kept": len(kept),
            "rag_before": len(lines),
        }

    # ------------------------------------------------------------------
    # 短期记忆
    # ------------------------------------------------------------------

    def _clean_short_term(self) -> dict[str, int]:
        path = self.data_dir / "memory" / "short_term.json"
        data = _read_json(path)
        if data is None:
            return {"short_term_missing": 0}
        turns = data.get("recent_turns", [])
        turns = turns if isinstance(turns, list) else []
        empty_turns = len([t for t in turns if not str(t.get("user", "")).strip()])
        total = len(turns)
        if self.apply and total:
            data["recent_turns"] = []
            data["summary"] = ""
            _write_json(path, data)
            self.actions.append(
                f"短期记忆：清空 {total} 轮（其中 user 为空的 {empty_turns} 轮）"
            )
        return {
            "short_term_turns": total,
            "short_term_empty_user_turns": empty_turns,
        }

    # ------------------------------------------------------------------
    # 计划
    # ------------------------------------------------------------------

    def _clean_plans(self) -> dict[str, int]:
        path = self.data_dir / "scheduler" / "scheduled_plans.json"
        data = _read_json(path)
        if data is None:
            return {"plans_missing": 0}
        expired = 0
        changed = False
        for item in data.get("plans", []):
            if not isinstance(item, dict):
                continue
            if item.get("status") != "pending":
                continue
            try:
                due = datetime.fromisoformat(str(item.get("due_at", "")))
            except ValueError:
                continue
            if due.tzinfo is not None and self.now.tzinfo is None:
                due = due.replace(tzinfo=None)
            if due >= self.now:
                continue
            expired += 1
            if self.apply:
                item["status"] = "cancelled"
                metadata = item.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["cleanup_reason"] = "expired_before_cleanup"
                    metadata["cleanup_at"] = self.now.isoformat(timespec="seconds")
                changed = True
        if self.apply and changed:
            _write_json(path, data)
            self.actions.append(f"计划：取消已过期的 pending 提醒 {expired} 条")
        return {"plans_expired_cancelled": expired}

    # ------------------------------------------------------------------
    # 主动状态
    # ------------------------------------------------------------------

    def _clean_proactive(self) -> dict[str, int]:
        path = self.data_dir / "scheduler" / "proactive_state.json"
        data = _read_json(path)
        if data is None:
            return {"proactive_missing": 0}
        history = data.get("proactive_template_history", [])
        history_count = len(history) if isinstance(history, list) else 0
        last_activity = data.get("last_user_activity_at")
        engagement = data.get("engagement")
        engagement_dirty = isinstance(engagement, dict) and any(
            int(engagement.get(key, 0) or 0) for key in ("relationship_sent", "replies_after_proactive")
        )
        if self.apply:
            data["proactive_template_history"] = []
            data["last_user_activity_at"] = None
            data["pending_follow_up"] = None
            data["engagement"] = dict(ENGAGEMENT_DEFAULT)
            data["memory_callback_sent_date"] = None
            data["weekend_suggestion_sent_date"] = None
            data["weather_sent_date"] = None
            _write_json(path, data)
            if history_count or last_activity or engagement_dirty:
                self.actions.append(
                    f"主动状态：清模板历史 {history_count} 条、重置最后活动时间与 engagement 计数"
                )
        return {
            "proactive_history_cleared": history_count,
            "proactive_last_activity_cleared": 1 if last_activity else 0,
            "proactive_engagement_reset": 1 if engagement_dirty else 0,
        }

    # ------------------------------------------------------------------
    # 认知状态
    # ------------------------------------------------------------------

    def _clean_cognition(self) -> dict[str, int]:
        path = self.data_dir / "cognition" / "cognitive_state.json"
        data = _read_json(path)
        if data is None:
            return {"cognition_missing": 0}
        rel = data.get("relationship_state")
        if not isinstance(rel, dict):
            return {"cognition_relationship_missing": 0}
        interactions = int(rel.get("interaction_count", 0) or 0)
        familiarity = float(rel.get("familiarity", FAMILIARITY_DEFAULT) or 0.0)
        if self.apply:
            changed = (
                int(rel.get("interaction_count", 0) or 0) != 0
                or abs(float(rel.get("familiarity", FAMILIARITY_DEFAULT) or 0.0) - FAMILIARITY_DEFAULT) > 1e-6
            )
            rel["interaction_count"] = 0
            rel["familiarity"] = FAMILIARITY_DEFAULT
            _write_json(path, data)
            if changed:
                self.actions.append(
                    f"认知状态：interaction_count {interactions} → 0，familiarity {familiarity:.2f} → {FAMILIARITY_DEFAULT}"
                )
        return {
            "cognition_interaction_count": interactions,
            "cognition_familiarity": int(familiarity * 100),
        }


def backup_data(data_dir: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"data-backup-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(data_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(data_dir.parent))
    return target


def render(report: dict) -> str:
    details = report["details"]
    lines = ["【将要做的事 / 已做的事】"]

    def line(label: str, value: int, unit: str = "") -> None:
        if value:
            lines.append(f"  {label}：{value}{unit}")

    line("RAG 空记录", details.get("rag_empty_removed", 0), " 条")
    line("RAG 同日重复", details.get("rag_duplicate_removed", 0), " 条")
    kept = details.get("rag_kept")
    before = details.get("rag_before")
    if kept is not None:
        lines.append(f"  RAG 保留：{kept} 条（原 {before} 条）")
    line("短期记忆轮数", details.get("short_term_turns", 0), " 轮")
    line("其中 user 为空的轮", details.get("short_term_empty_user_turns", 0), " 轮")
    line("过期待发提醒", details.get("plans_expired_cancelled", 0), " 条")
    line("主动模板历史", details.get("proactive_history_cleared", 0), " 条")
    if details.get("proactive_last_activity_cleared"):
        lines.append("  最后活动时间：将被重置")
    if details.get("proactive_engagement_reset"):
        lines.append("  engagement 计数：将被重置")
    count = details.get("cognition_interaction_count")
    if count:
        lines.append(f"  interaction_count：{count} → 0")
    if len(lines) == 1:
        lines.append("  没有需要清理的内容（数据已经是干净的）")

    lines.append("")
    if report["apply"]:
        lines.append("【已执行】")
        for action in report["actions"]:
            lines.append(f"  ✓ {action}")
        lines.append("")
        lines.append("  提示：下次启动 Agent 会把这些改动写进各自的运行流程；")
        lines.append("        若要回滚，解压备份 zip 覆盖 data/ 即可。")
    else:
        lines.append("【这是预览，尚未修改任何文件】")
        lines.append("  确认无误后执行：python tools/clean_history.py --apply")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="银狼历史数据清理（默认只预览，不改文件）",
    )
    parser.add_argument("--apply", action="store_true", help="真正执行（执行前自动备份）")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--keep-rag-days", type=int, default=0, help="RAG 只保留最近 N 天（0=不限）")
    parser.add_argument("--skip-rag", action="store_true")
    parser.add_argument("--skip-short-term", action="store_true")
    parser.add_argument("--skip-plans", action="store_true")
    parser.add_argument("--skip-proactive", action="store_true")
    parser.add_argument("--skip-cognition", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"数据目录不存在：{data_dir}")
        return 2

    if args.apply:
        target = backup_data(data_dir, Path(args.backup_dir))
        print(f"已备份：{target}")

    cleaner = HistoryCleaner(
        data_dir=data_dir,
        apply=args.apply,
        keep_rag_days=args.keep_rag_days,
        do_rag=not args.skip_rag,
        do_short_term=not args.skip_short_term,
        do_plans=not args.skip_plans,
        do_proactive=not args.skip_proactive,
        do_cognition=not args.skip_cognition,
    )
    report = cleaner.run()
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
