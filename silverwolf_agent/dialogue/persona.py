"""Lv30: Persona 分层与世界书。

整份人设曾在每轮注入约 1.1 万 token，占单轮输入的七成，而且里面堆着
Lv17→Lv29 十几个历史版本的规则，大部分与当前这句话无关。

这里把它拆成两层：

* **核心**（`silverwolf_lv30.md`）：身份、性格、说话底线、关系边界，常驻；
* **模块**（`modules/*.md`）：按关键词与本轮 goal 命中的历史规则。

两条铁律：

1. 规则一条都不能丢 —— 模块没命中时行为可以更简洁，但常驻模块（relation/style）永远在；
2. 读取失败必须能降级 —— 模块目录缺失就用核心，核心缺失就退回上一版整份人设。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..paths import (
    CONFIG_DIR,
    PERSONA_PATH,
    PERSONA_MODULES_DIR,
)

DEFAULT_CORE_MAX_CHARS = 4000
DEFAULT_BUDGET_CHARS = 8000


@dataclass(frozen=True)
class PersonaModule:
    name: str
    resident: bool
    priority: int
    triggers: tuple[str, ...]
    scenes: tuple[str, ...]
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class PersonaSelection:
    text: str
    core_chars: int = 0
    modules: list[dict[str, object]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    fallback: str = ""

    @property
    def total_chars(self) -> int:
        return len(self.text)

    def describe(self) -> dict[str, object]:
        return {
            "total_chars": self.total_chars,
            "core_chars": self.core_chars,
            "modules": self.modules,
            "skipped": self.skipped,
            "fallback": self.fallback,
        }


class PersonaLibrary:
    """加载核心人设与模块，并按本轮输入/目标挑选要注入的部分。"""

    def __init__(
        self,
        *,
        core_path: Path | None = None,
        modules_dir: Path | None = None,
        enabled: bool = True,
        core_max_chars: int = DEFAULT_CORE_MAX_CHARS,
        budget_chars: int = DEFAULT_BUDGET_CHARS,
    ) -> None:
        self.core_path = core_path or PERSONA_PATH
        self.modules_dir = modules_dir or PERSONA_MODULES_DIR
        self.enabled = bool(enabled)
        self.core_max_chars = max(500, int(core_max_chars))
        self.budget_chars = max(self.core_max_chars, int(budget_chars))
        self._modules: list[PersonaModule] | None = None
        self._core: str = ""

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load_core(self) -> str:
        if self._core:
            return self._core
        if self.core_path.exists():
            self._core = self.core_path.read_text(encoding="utf-8")
            return self._core
        # 兜底：核心文件没了，退回上一版整份人设
        for candidate in sorted(
            CONFIG_DIR.glob("persona/silverwolf_lv*.md"),
            reverse=True,
        ):
            if candidate == self.core_path:
                continue
            try:
                self._core = candidate.read_text(encoding="utf-8")
                return self._core
            except OSError:
                continue
        self._core = ""
        return self._core

    def modules(self) -> list[PersonaModule]:
        if self._modules is not None:
            return self._modules
        loaded: list[PersonaModule] = []
        if self.modules_dir.exists():
            for path in sorted(self.modules_dir.glob("*.md")):
                module = self._parse_module(path)
                if module is not None:
                    loaded.append(module)
        loaded.sort(key=lambda item: (-item.priority, item.name))
        self._modules = loaded
        return loaded

    def reload(self) -> None:
        self._modules = None
        self._core = ""

    @staticmethod
    def _parse_module(path: Path) -> PersonaModule | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None

        lines = raw.splitlines()
        meta: dict[str, str] = {}
        body_start = 0
        if lines and lines[0].strip() == "---":
            for index in range(1, len(lines)):
                line = lines[index].strip()
                if line == "---":
                    body_start = index + 1
                    break
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        body = "\n".join(lines[body_start:]).strip()
        if not body:
            return None

        def split_list(value: str) -> tuple[str, ...]:
            return tuple(
                item.strip()
                for item in value.replace("，", ",").split(",")
                if item.strip()
            )

        try:
            priority = int(meta.get("priority", "50"))
        except ValueError:
            priority = 50

        return PersonaModule(
            name=meta.get("name", path.stem) or path.stem,
            resident=meta.get("resident", "false").strip().lower()
            in {"true", "1", "yes"},
            priority=priority,
            triggers=split_list(meta.get("triggers", "")),
            scenes=split_list(meta.get("scenes", "")),
            text=body,
        )

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------

    def select(
        self,
        *,
        user_input: str = "",
        goal_kinds: tuple[str, ...] | list[str] = (),
        scene: str = "",
    ) -> PersonaSelection:
        core = self._load_core()
        core_chars = len(core)

        if not self.enabled:
            return PersonaSelection(
                text=core,
                core_chars=core_chars,
                fallback="layers_disabled",
            )

        modules = self.modules()
        if not modules:
            # 模块全没了：核心照常工作，行为退化为"只有核心"
            return PersonaSelection(
                text=core,
                core_chars=core_chars,
                fallback="no_modules",
            )

        text = user_input or ""
        kinds = {str(item) for item in goal_kinds if str(item)}
        scene_key = str(scene or "")

        chosen: list[PersonaModule] = []
        skipped: list[str] = []
        budget = self.budget_chars

        for module in modules:
            reason = self._match_reason(
                module,
                text=text,
                kinds=kinds,
                scene=scene_key,
            )
            if not reason:
                continue
            if core_chars + sum(item.chars for item in chosen) + module.chars > budget:
                skipped.append(module.name)
                continue
            chosen.append(module)

        parts = [core] if core else []
        parts.extend(module.text for module in chosen)
        selection = PersonaSelection(
            text="\n\n".join(parts).strip(),
            core_chars=core_chars,
            modules=[
                {
                    "name": module.name,
                    "chars": module.chars,
                    "resident": module.resident,
                    "reason": self._match_reason(
                        module,
                        text=text,
                        kinds=kinds,
                        scene=scene_key,
                    ),
                }
                for module in chosen
            ],
            skipped=skipped,
            fallback="" if core else "core_missing",
        )
        return selection

    @staticmethod
    def _match_reason(
        module: PersonaModule,
        *,
        text: str,
        kinds: set[str],
        scene: str,
    ) -> str:
        if module.resident:
            return "resident"
        for kind in kinds:
            if kind in module.scenes:
                return f"scene:{kind}"
        if scene and scene in module.scenes:
            return f"scene:{scene}"
        for trigger in module.triggers:
            if trigger and trigger in text:
                return f"trigger:{trigger}"
        return ""

    # ------------------------------------------------------------------
    # 调试与兼容
    # ------------------------------------------------------------------

    def full_text(self) -> str:
        """核心 + 全部模块（给"整份人设"的断言与极端兜底用）。"""
        parts = [self._load_core()]
        parts.extend(module.text for module in self.modules())
        return "\n\n".join(part for part in parts if part).strip()

    def stats(self) -> dict[str, object]:
        modules = self.modules()
        return {
            "enabled": self.enabled,
            "core_chars": len(self._load_core()),
            "core_path": self.core_path.name,
            "modules": len(modules),
            "resident": [item.name for item in modules if item.resident],
            "module_chars": {item.name: item.chars for item in modules},
            "budget_chars": self.budget_chars,
        }
