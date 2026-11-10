from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseTool, ToolResult
from ..temporal import WEEKDAY_CN


class CalendarQueryTool(BaseTool):
    name = "calendar_query"
    description = (
        "根据 Planner 已解析出的目标日期，返回准确日期和中文星期。"
    )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "ISO 日期 YYYY-MM-DD",
                },
                "relation_label": {
                    "type": "string",
                    "description": "今天、明天、下周一等自然语言标签",
                },
                "query_kind": {
                    "type": "string",
                    "enum": ["date", "weekday", "date_weekday"],
                },
                "include_year": {
                    "type": "boolean",
                },
            },
            "required": [
                "target_date",
                "query_kind",
            ],
            "additionalProperties": False,
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = str(arguments.get("target_date", "")).strip()
        try:
            target = date.fromisoformat(raw)
        except ValueError as exc:
            return ToolResult(
                ok=False,
                content=None,
                error=f"无效目标日期：{raw!r}（{exc}）",
            )

        query_kind = str(arguments.get("query_kind", "")).strip()
        if query_kind not in {"date", "weekday", "date_weekday"}:
            return ToolResult(
                ok=False,
                content=None,
                error=f"无效日期查询类型：{query_kind!r}",
            )

        return ToolResult(
            ok=True,
            content={
                "target_date": target.isoformat(),
                "year": target.year,
                "month": target.month,
                "day": target.day,
                "weekday": WEEKDAY_CN[target.weekday()],
                "weekday_index": target.weekday(),
                "relation_label": str(
                    arguments.get("relation_label", "")
                ).strip(),
                "query_kind": query_kind,
                "include_year": bool(arguments.get("include_year", False)),
            },
        )
