"""Lv33: 体检（/doctor）与总览（/status）。

起因很具体：Lv27→Lv32 六个版本的能力，在真实数据里**一项都没生效过**
（认知 schema 还是 21、RAG 没有任何 importance 字段、承诺/语料/自我分享文件都不存在）。
问题不是功能坏了，而是**没人能一眼看出"跑没跑"**。

所以这里只做一件事：把"是否生效"变成确定性判定，并给出人话结论。

铁律：
1. **只读**——不修任何数据，不写任何文件；
2. 判定全部是确定性规则，不调用模型；
3. 不通过不代表出错（可能只是还没用够），文案要中肯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .paths import (
    COGNITION_STATE_PATH,
    COMMITMENTS_PATH,
    CORPUS_CANDIDATES_PATH,
    CORPUS_LEARNED_PATH,
    CORPUS_SIGNALS_PATH,
    RECALL_STATS_PATH,
    RAG_PATH,
    PROACTIVE_STATE_PATH,
    SCHEDULER_DIR,
    ensure_directories,
)

OK = "OK"
PENDING = "未生效"
PROBLEM = "异常"


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    status: str
    detail: str
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    conclusion: str = ""

    @property
    def problems(self) -> list[Check]:
        return [item for item in self.checks if item.status != OK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [item.to_dict() for item in self.checks],
            "ok_count": len([item for item in self.checks if item.ok]),
            "total": len(self.checks),
            "problems": [item.name for item in self.problems],
            "conclusion": self.conclusion,
        }

    def render(self) -> str:
        lines: list[str] = []
        current = ""
        for check in self.checks:
            if check.category != current:
                current = check.category
                lines.append("")
                lines.append(f"【{current}】")
            mark = "✓" if check.ok else ("·" if check.status == PENDING else "✗")
            line = f"  {mark} {check.name:<12} {check.detail}"
            lines.append(line.rstrip())
            if check.hint and not check.ok:
                lines.append(f"      → {check.hint}")
        lines.append("")
        lines.append("【结论】")
        for part in self.conclusion.split("\n"):
            lines.append(f"  {part}")
        return "\n".join(lines).strip()


class Doctor:
    """只读体检。所有判定都是确定性规则。"""

    def __init__(
        self,
        *,
        agent: Any,
        now: datetime,
        stale_days: int = 3,
    ) -> None:
        self.agent = agent
        self.now = now
        self.stale_days = max(1, int(stale_days))

    # ------------------------------------------------------------------

    def run(self) -> DoctorReport:
        report = DoctorReport()
        report.checks.extend(self._config_checks())
        report.checks.extend(self._data_checks())
        report.checks.extend(self._directory_checks())
        report.conclusion = self._conclusion(report)
        return report

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def _config_checks(self) -> list[Check]:
        config = getattr(self.agent, "config", None)
        checks: list[Check] = []

        api_key = str(getattr(config, "api_key", "") or "").strip()
        checks.append(
            Check(
                "配置",
                "API Key",
                OK if api_key else PROBLEM,
                "已配置" if api_key else "未配置",
                "" if api_key else "未配置时全链路离线：语料化、每周反思、记忆加权都不会生效",
            )
        )

        checks.append(
            Check(
                "配置",
                "模型 / 时区",
                OK,
                f"{getattr(config, 'model', '?')} · {getattr(config, 'timezone', '?')}",
            )
        )

        flags = {
            "长期承诺": getattr(config, "commitment_enabled", None),
            "语料生长": getattr(config, "corpus_learning_enabled", None),
            "人设分层": getattr(config, "persona_layers_enabled", None),
            "主动语料化": getattr(config, "proactive_speech_enabled", None),
            "自我分享": getattr(config, "self_share_enabled", None),
            "每周反思": getattr(config, "reflection_enabled", None),
        }
        shown = [
            f"{name}{'on' if value else 'off'}"
            for name, value in flags.items()
            if value is not None
        ]
        checks.append(Check("配置", "功能开关", OK, " | ".join(shown) or "（无）"))
        return checks

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def _expected_schema(self) -> int | None:
        cognition = getattr(self.agent, "cognition", None)
        return getattr(cognition, "SCHEMA_VERSION", None) if cognition else None

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _data_checks(self) -> list[Check]:
        checks: list[Check] = []

        # 1. 认知 schema
        expected = self._expected_schema()
        data = self._read_json(COGNITION_STATE_PATH)
        if data is None:
            checks.append(
                Check("数据", "认知状态", PENDING, "文件不存在", "正常聊一句就会生成")
            )
        else:
            actual = data.get("schema_version")
            if expected is not None and actual != expected:
                checks.append(
                    Check(
                        "数据",
                        "认知状态",
                        PENDING,
                        f"schema {actual}（期望 {expected}）",
                        "旧版本数据：跑一轮对话后会自动升级",
                    )
                )
            else:
                checks.append(
                    Check("数据", "认知状态", OK, f"schema {actual}")
                )

        # 2. 每周反思
        reflections = data.get("reflections", []) if isinstance(data, dict) else []
        count = len(reflections) if isinstance(reflections, list) else 0
        checks.append(
            Check(
                "数据",
                "每周反思",
                OK if count else PENDING,
                f"{count} 次",
                "周日 21 点后或本周重要度累计到阈值才会跑",
            )
        )

        # 3. RAG 重要度覆盖
        docs, with_importance = self._rag_importance()
        if docs == 0:
            checks.append(
                Check("数据", "RAG 重要度", PENDING, "没有长期记忆", "跨天后会自动写日总结")
            )
        elif with_importance == 0:
            checks.append(
                Check(
                    "数据",
                    "RAG 重要度",
                    PENDING,
                    f"{docs} 条全部无该字段",
                    "Lv28 起才会写入分级；旧记录按默认值 5 处理",
                )
            )
        else:
            checks.append(
                Check(
                    "数据",
                    "RAG 重要度",
                    OK if with_importance >= docs else OK,
                    f"{with_importance}/{docs} 条已分级",
                )
            )

        # 4. 召回统计
        recall = self._read_json(RECALL_STATS_PATH)
        recalled = len([k for k in (recall or {}) if (recall or {}).get(k)])
        checks.append(
            Check(
                "数据",
                "记忆召回",
                OK if recalled else PENDING,
                f"{recalled} 条被想起过" if recalled else "尚无记录",
                "问一句需要查记忆的话（例如“还记得我上次说的吗”）就会产生",
            )
        )

        # 5. 长期承诺
        commitments = self._read_json(COMMITMENTS_PATH)
        items = commitments.get("commitments", []) if isinstance(commitments, dict) else []
        checks.append(
            Check(
                "数据",
                "长期承诺",
                OK if items else PENDING,
                f"{len(items)} 项" if items else "尚未创建",
                "说一句“我以后每周的周末打算学 XX”就会触发澄清流程",
            )
        )

        # 6. 语料生长
        has_candidates = CORPUS_CANDIDATES_PATH.exists()
        has_learned = CORPUS_LEARNED_PATH.exists()
        signals = self._read_json(CORPUS_SIGNALS_PATH) or {}
        checks.append(
            Check(
                "数据",
                "语料生长",
                OK if (has_candidates or has_learned) else PENDING,
                (
                    f"候选 {'有' if has_candidates else '无'} · "
                    f"已转正 {'有' if has_learned else '无'} · "
                    f"弱信号 {len(signals)}"
                ),
                "聊几句后候选会攒起来；转正需要你 /corpus approve",
            )
        )

        # 7. 自我分享
        state = self._read_json(PROACTIVE_STATE_PATH) or {}
        shares = state.get("self_share_history", [])
        share_count = len(shares) if isinstance(shares, list) else 0
        checks.append(
            Check(
                "数据",
                "自我分享",
                OK if share_count else PENDING,
                f"{share_count} 次",
                "每周最多 2 次，会在早/中/晚消息尾部出现",
            )
        )

        # 8. 主动语料化
        history = state.get("proactive_template_history", [])
        with_source = 0
        if isinstance(history, list):
            with_source = len(
                [
                    item
                    for item in history
                    if isinstance(item, dict) and item.get("source")
                ]
            )
        checks.append(
            Check(
                "数据",
                "主动语料化",
                OK if with_source else PENDING,
                f"{with_source}/{len(history)} 条带来源标记",
                "Lv31 起才会写 source；有 API Key 时主动消息才会走模型",
            )
        )

        # 9. 最后活动
        raw = state.get("last_user_activity_at")
        if not raw:
            checks.append(
                Check("数据", "最后活动", PENDING, "从未记录", "正常聊一句就会写入")
            )
        else:
            try:
                moment = datetime.fromisoformat(str(raw))
            except ValueError:
                moment = None
            if moment is None:
                checks.append(Check("数据", "最后活动", PROBLEM, "时间格式无法解析"))
            else:
                if moment.tzinfo is None and self.now.tzinfo is not None:
                    moment = moment.replace(tzinfo=self.now.tzinfo)
                days = (self.now - moment).days
                stale = days >= self.stale_days
                checks.append(
                    Check(
                        "数据",
                        "最后活动",
                        PENDING if stale else OK,
                        f"{moment.date().isoformat()}（{days} 天前）",
                        f"数据已超过 {self.stale_days} 天没更新，上面的计数可能只是历史遗留",
                    )
                )
        return checks

    def _rag_importance(self) -> tuple[int, int]:
        if not RAG_PATH.exists():
            return 0, 0
        total = 0
        with_importance = 0
        try:
            lines = RAG_PATH.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return 0, 0
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            metadata = item.get("metadata") if isinstance(item, dict) else None
            if isinstance(metadata, dict) and "importance" in metadata:
                with_importance += 1
        return total, with_importance

    # ------------------------------------------------------------------
    # 目录
    # ------------------------------------------------------------------

    def _directory_checks(self) -> list[Check]:
        checks: list[Check] = []
        try:
            ensure_directories()
        except OSError as exc:
            checks.append(
                Check("目录", "数据目录", PROBLEM, f"创建失败：{exc}", "检查磁盘权限")
            )
            return checks

        probe = SCHEDULER_DIR / ".doctor_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks.append(Check("目录", "数据可写", OK, str(SCHEDULER_DIR.parent)))
        except OSError as exc:
            checks.append(
                Check("目录", "数据可写", PROBLEM, f"写入失败：{exc}", "检查目录权限")
            )
        return checks

    # ------------------------------------------------------------------
    # 结论
    # ------------------------------------------------------------------

    def _conclusion(self, report: DoctorReport) -> str:
        config = getattr(self.agent, "config", None)
        api_key = str(getattr(config, "api_key", "") or "").strip()
        pending = [item for item in report.checks if item.status == PENDING]
        problems = [item for item in report.checks if item.status == PROBLEM]

        lines: list[str] = []
        if problems:
            lines.append(
                "有 "
                + str(len(problems))
                + " 项需要先处理："
                + "、".join(item.name for item in problems)
                + "。"
            )
        if not api_key:
            lines.append(
                "未配置 API Key：现在是纯离线模式，语料化、每周反思、记忆加权都不会生效。"
            )
            lines.append("把 API Key 写进 .env 再重启，这些能力才会开始工作。")
            return "\n".join(lines)

        stale = any(item.name == "最后活动" and not item.ok for item in report.checks)
        if pending and stale:
            lines.append(
                f"多数新功能还没有在真实对话中跑过（{len(pending)} 项未生效）。"
            )
            lines.append("建议先正常运行一天，再执行 /doctor 复查；届时上面会逐项变成 ✓。")
            return "\n".join(lines)

        if pending:
            lines.append(
                "还有 "
                + str(len(pending))
                + " 项没触发过："
                + "、".join(item.name for item in pending)
                + "。"
            )
            lines.append("多数只是还没到触发条件，按上面每项的提示试一次即可。")
            return "\n".join(lines)

        lines.append("全部检查通过，各项能力都在正常工作。")
        return "\n".join(lines)
