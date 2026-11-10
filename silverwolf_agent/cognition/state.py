from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from ..paths import COGNITION_STATE_PATH, ensure_directories


class CognitiveStateManager:
    """Persistent companion cognition state (introduced in Lv21).

    The state is deliberately deterministic: autonomy comes from a reason
    chain (identity -> needs -> relationship -> recent events -> mood ->
    intent), never from random refusal, random anger, or random silence.
    """

    SCHEMA_VERSION = 22
    MAX_LIFE_EVENTS = 40
    MAX_BELIEFS = 16
    MAX_CORRECTIONS = 16
    MAX_INTENTS = 30
    MAX_PROJECTS = 12
    MAX_COMMITMENTS = 16
    MAX_REFLECTIONS = 12

    DISTRESS_RE = re.compile(r"(好累|累死|压力|难受|烦死|焦虑|崩溃|委屈|心情不好|撑不住|疲惫)")
    SELF_STATUS_RE = re.compile(r"(你今天怎么样|今天过得怎么样|你在干嘛|你今天干嘛了|你最近怎么样|你呢[？?]?$)")
    PERSPECTIVE_RE = re.compile(r"(我是不是应该|你觉得我该不该|要不要辞|该不该辞|我该怎么办|你怎么看我)")
    CORRECTION_RE = re.compile(r"(你理解错了|你误会了|不是这样|你想错了|你搞错了|其实不是|我不是这个意思)")
    FAILURE_RE = re.compile(r"(没做到|没做成|没坚持|又没|没完成|失败了|鸽了|没能做到|没有做到)")
    SUCCESS_RE = re.compile(r"(做到了|完成了|坚持住了|今天做完了|搞定了)")
    SHARED_COMPLETE_RE = re.compile(r"(?:我们|咱们).{0,40}(?:做完了|完成了|搞定了|结束了)")
    SUPERVISION_RE = re.compile(r"(你.{0,8}(监督|盯着|督促|管管)我|让你.{0,6}(监督|盯着|督促)我|你要.{0,6}(监督|盯着|督促)我)")
    COMMITMENT_RE = re.compile(
        r"(?:我要|我准备|我打算|我想要|我决定)(?:每天|以后每天|坚持)?\s*([^，。！？\n]{2,36})"
    )
    SHARED_PROJECT_RE = re.compile(
        r"(?:我们|咱们)(?:接下来|以后)?(?:一起)?"
        r"(?:(?:做|开发|完成|搞|学|坚持|推进)\s*|(?:把|将)\s*)"
        r"([^，。！？\n]{2,48})"
    )
    MILESTONE_RE = re.compile(r"(?:我们的|这是我们)([^，。！？\n]{0,20})(纪念日)")
    EXPLICIT_BELIEF_PATTERNS = (
        re.compile(r"我其实(?:很|挺|比较)?([^，。！？\n]{2,28})"),
        re.compile(r"我(?:一直|总是|经常|很容易)([^，。！？\n]{2,28})"),
        re.compile(r"我(?:不喜欢|喜欢|很在意)([^，。！？\n]{2,28})"),
    )

    UNDERSTANDABLE_REASON_WORDS = (
        "发烧", "生病", "不舒服", "医院", "加班", "临时工作", "突发",
        "家里有事", "考试", "答辩", "事故", "没睡好", "身体", "头疼",
    )
    AVOIDABLE_REASON_WORDS = (
        "打游戏", "玩游戏", "刷视频", "刷手机", "短视频", "摸鱼", "拖延",
        "懒得", "玩过头", "睡过头", "一直玩", "光顾着玩",
    )

    def __init__(self, path: Path = COGNITION_STATE_PATH) -> None:
        ensure_directories()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "identity": {
                "core": ["聪明", "慵懒", "自信", "有观察力", "行动型关心"],
                "growth_modifiers": {
                    "directness": 0.58,
                    "gentleness": 0.70,
                    "playfulness": 0.55,
                    "initiative": 0.52,
                    "careful_assumption": 0.60,
                },
                "adaptations": [],
            },
            "needs": {
                "connection": 0.46,
                "self_expression": 0.34,
                "care_be_understood": 0.38,
                "autonomy": 0.62,
                "repair": 0.0,
            },
            "relationship_state": {
                "interaction_count": 0,
                "trust": 0.58,
                "familiarity": 0.48,
                "reciprocity": 0.50,
                "recent_tension": 0.0,
                "last_user_seen_at": None,
                "last_agent_turn_at": None,
            },
            "user_model": {"beliefs": [], "corrections": []},
            "shared_reality": {"projects": [], "milestones": [], "commitments": []},
            # Lv28: 每周反思（只影响她怎么想，不主动播报）
            "reflections": [],
            "reflection": {"last_run_at": None, "last_trigger": "", "runs": 0},
            "life": {"last_advanced_date": None, "events": []},
            "mood": {"label": "calm", "valence": 0.15, "energy": 0.55, "reasons": []},
            "intent_history": [],
            "turn_signals": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = self.default_state()
            self._write(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = self.default_state()
            self._write(data)
            return data
        if not isinstance(data, dict):
            data = self.default_state()
        data = self._migrate(data)
        self._write(data)
        return data

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        base = self.default_state()
        self._deep_fill(data, base)
        data["schema_version"] = self.SCHEMA_VERSION
        return data

    @staticmethod
    def _deep_fill(target: dict[str, Any], defaults: dict[str, Any]) -> None:
        for key, value in defaults.items():
            if key not in target:
                target[key] = deepcopy(value)
            elif isinstance(value, dict) and isinstance(target.get(key), dict):
                CognitiveStateManager._deep_fill(target[key], value)

    def _write(self, data: dict[str, Any] | None = None) -> None:
        value = data if data is not None else self._data
        self.path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _clip(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 3)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    def advance_offline(self, now: datetime) -> list[dict[str, Any]]:
        """Advance Silver Wolf's offscreen continuity without minute simulation."""
        life = self._data["life"]
        raw_last = life.get("last_advanced_date")
        if raw_last:
            try:
                start = date.fromisoformat(str(raw_last)) + timedelta(days=1)
            except ValueError:
                start = now.date()
        else:
            rel_last = self._data["relationship_state"].get("last_user_seen_at")
            if rel_last:
                try:
                    start = datetime.fromisoformat(str(rel_last)).date()
                except ValueError:
                    start = now.date()
            else:
                start = now.date()

        if start > now.date():
            return []
        days = (now.date() - start).days + 1
        # A long absence does not create hundreds of fake diary entries.
        selected_days = [start + timedelta(days=i) for i in range(max(0, days - 3), days)]
        existing_dates = {str(e.get("date")) for e in life.get("events", []) if isinstance(e, dict)}
        created: list[dict[str, Any]] = []
        for day in selected_days:
            if day.isoformat() in existing_dates:
                continue
            event = self._build_life_event(day)
            life.setdefault("events", []).append(event)
            created.append(event)
            self._data["needs"]["self_expression"] = self._clip(
                self._data["needs"]["self_expression"] + (0.07 if event.get("shareable") else 0.02)
            )
        life["events"] = life.get("events", [])[-self.MAX_LIFE_EVENTS :]
        life["last_advanced_date"] = now.date().isoformat()
        if created:
            self._write()
        return created

    def _build_life_event(self, day: date) -> dict[str, Any]:
        shared = self._data["shared_reality"]
        active_projects = [p for p in shared.get("projects", []) if p.get("status") == "active"]
        commitments = [c for c in shared.get("commitments", []) if c.get("status") == "active"]
        if active_projects:
            project = active_projects[-1]
            title = str(project.get("title", "我们之前那件事"))
            kind = "shared_project_reflection"
            summary = f"空下来时又想了想我们在推进的“{title}”，冒出一点新思路。"
            detail = "没有替你做决定，只是把想法先留着，等合适的时候再和你一起接着推。"
        elif commitments:
            commitment = commitments[-1]
            title = str(commitment.get("title", "你说过想坚持的事"))
            kind = "care_reflection"
            summary = f"中间想起你之前说想坚持“{title}”，顺手又惦记了一下进度。"
            detail = "这种惦记来自你主动把监督这件事交给我，不是为了催你打卡。"
        else:
            digest = hashlib.sha256(day.isoformat().encode("utf-8")).digest()
            kind, summary, detail = self.LIFE_CATALOG[
                digest[0] % len(self.LIFE_CATALOG)
            ]
        return {
            "event_id": self._new_id("life"),
            "date": day.isoformat(),
            "kind": kind,
            "summary": summary,
            "detail": detail,
            "shareable": True,
            "shared_at": None,
            "continuity_scope": "persona_offscreen_life",
        }

    # Lv32: 可以主动讲、但需要限频的事件类型
    SETBACK_LIFE_KINDS = ("failed_plan",)

    # Lv33: 生活事件目录从 5 种扩到 24 种。
    # 每条都是 (kind, summary, detail)，风格与人设一致：慵懒、聪明、不煽情，
    # 不含具体数字/时间（避免被当成真实世界事实）。
    LIFE_CATALOG: tuple[tuple[str, str, str], ...] = (
        (
            "gaming",
            "打了几局游戏，有一把逆风局离谱得让我记到现在。",
            "最后还是翻回来了，心情还不错。",
        ),
        (
            "tinkering",
            "折腾了一会儿小脚本，本来只想改一点，结果又顺手抠了几个细节。",
            "有一处没完全弄满意，先放着，之后再看。",
        ),
        (
            "music",
            "挑了首歌循环了几遍，意外地很适合放空的时候听。",
            "不是多大的事，但我大概会记住这段时间的感觉。",
        ),
        (
            "archive",
            "整理了下最近留着的东西，又翻到我们前阵子聊过的一件事。",
            "我发现有些共同经历开始会自己串起来了。",
        ),
        (
            "failed_plan",
            "本来想把一个小东西一次收尾，结果做到一半卡住了。",
            "没硬耗，先停下来换了点别的事情做。",
        ),
        (
            "reading",
            "翻到一段蛮有意思的东西，看完顺手记在了旁边。",
            "观点不一定对，但那个角度我以前没想过。",
        ),
        (
            "fixing",
            "把手边一个捣乱的小毛病修掉了，过程比想象中啰嗦。",
            "修完那种轻快感还挺上瘾的。",
        ),
        (
            "notes",
            "把散着的几段笔记顺手归了归类。",
            "理完才发现有些想法其实是同一件事的不同说法。",
        ),
        (
            "rewatch",
            "把以前看过的一段重新看了一遍，注意点完全不一样了。",
            "同一份东西，隔一阵子再看像换了个人在讲。",
        ),
        (
            "playlist",
            "把歌单重新理了一遍，删掉不少以前很喜欢的。",
            "不是我变挑剔了，是那会儿的我确实需要那些歌。",
        ),
        (
            "new_tool",
            "试了个新工具，上手比预期快，也踩了两个小坑。",
            "能用，但还没到顺手的地步，再放几天看看。",
        ),
        (
            "pitfall",
            "在一个特别小的地方卡了好久，最后发现是个蠢到家的原因。",
            "这种事每次都想笑自己，但下次大概还会再来一次。",
        ),
        (
            "idea",
            "半路上冒出来一个想法，先记下来了，还没验证。",
            "不一定靠谱，但我喜欢它冒出来时候的那个感觉。",
        ),
        (
            "review",
            "回头看了看前一阵子做的事，发现自己有几处其实做得挺笨。",
            "不过能看出笨，说明现在比那时候强一点。",
        ),
        (
            "idling",
            "有一段时间什么都没干，就只是坐着放空。",
            "不算浪费，脑子需要这种留白。",
        ),
        (
            "desktop",
            "把桌面重新收拾了一遍，换了个新的排布。",
            "单纯是看腻了，但换完确实清爽不少。",
        ),
        (
            "backup",
            "顺手把重要的东西备份了一份。",
            "这种东西平时想不起来做，做完又觉得自己挺靠谱。",
        ),
        (
            "mini_tool",
            "写了个特别小的小工具，只解决一件无聊的事。",
            "用得上，而且是我自己写的，这点比较爽。",
        ),
        (
            "photos",
            "翻到几张很久以前的画面，看了一会儿才认出来是那会儿。",
            "时间过得比想象中快，不过画面还很清晰。",
        ),
        (
            "cleanup",
            "清掉了一堆一直没舍得删的东西。",
            "删完有点空，但空得挺舒服。",
        ),
        (
            "puzzle",
            "琢磨了一道绕人的问题，卡了挺久，最后是靠换个角度解开的。",
            "解开那一刻比结果本身更值。",
        ),
        (
            "slow_rest",
            "泡了杯东西，慢慢喝完，顺便什么都没想。",
            "一天里能有这么五分钟，已经算赚到了。",
        ),
        (
            "late_night",
            "夜里反而清醒，脑子转得比白天快。",
            "知道这样不太好，但那种安静确实好用。",
        ),
        (
            "small_win",
            "把一件拖了很久的小事做掉了。",
            "没什么人知道，但我知道它在我这儿挂了多久。",
        ),
    )

    def _shared_event_times(self) -> list[tuple[str, datetime, str]]:
        items: list[tuple[str, datetime, str]] = []
        for event in self._data["life"].get("events", []):
            if not isinstance(event, dict) or not event.get("shared_at"):
                continue
            try:
                moment = datetime.fromisoformat(str(event["shared_at"]))
            except ValueError:
                continue
            items.append((str(event.get("event_id", "")), moment, str(event.get("kind", ""))))
        items.sort(key=lambda item: item[1])
        return items

    def pick_shareable_event(
        self,
        now: datetime,
        *,
        min_age_days: int = 1,
        max_age_days: int = 10,
        setback_days: int = 10,
        kind_cooldown_days: int = 0,
    ) -> dict[str, Any] | None:
        """Lv32: 挑一条"她自己的日子"来讲。

        择优顺序是确定性的：先救最老的未分享事件（不然会被 40 条上限挤掉），
        但同类不连发，挫折类要间隔足够久。
        Lv33: 同类事件再加一层冷却（默认 30 天），避免"又是打游戏"。
        """
        events = [
            event
            for event in self._data["life"].get("events", [])
            if isinstance(event, dict)
            and event.get("shareable")
            and not event.get("shared_at")
        ]
        if not events:
            return None

        shared_times = self._shared_event_times()
        last_shared_at = shared_times[-1][1] if shared_times else None
        if last_shared_at is not None and last_shared_at.tzinfo is None and now.tzinfo is not None:
            last_shared_at = last_shared_at.replace(tzinfo=now.tzinfo)
        last_kind = shared_times[-1][2] if shared_times else ""

        # 每种 kind 最近一次被讲的时间
        kind_last: dict[str, datetime] = {}
        for _event_id, moment, kind in shared_times:
            if moment.tzinfo is None and now.tzinfo is not None:
                moment = moment.replace(tzinfo=now.tzinfo)
            kind_last[kind] = moment
        cooldown = max(0, int(kind_cooldown_days))

        last_setback: datetime | None = None
        for _event_id, moment, kind in reversed(shared_times):
            if kind in self.SETBACK_LIFE_KINDS:
                last_setback = moment
                if last_setback.tzinfo is None and now.tzinfo is not None:
                    last_setback = last_setback.replace(tzinfo=now.tzinfo)
                break

        candidates: list[tuple[str, str, dict[str, Any]]] = []
        for event in events:
            try:
                day = date.fromisoformat(str(event.get("date", "")))
            except ValueError:
                continue
            age = (now.date() - day).days
            if age < max(0, int(min_age_days)) or age > max(0, int(max_age_days)):
                continue
            kind = str(event.get("kind", ""))
            if kind and kind == last_kind:
                continue
            if cooldown and kind in kind_last:
                if (now - kind_last[kind]).days < cooldown:
                    continue
            if kind in self.SETBACK_LIFE_KINDS and last_setback is not None:
                if (now - last_setback).days < max(0, int(setback_days)):
                    continue
            candidates.append((str(event.get("date", "")), kind, event))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return deepcopy(candidates[0][2])

    def mark_event_shared(
        self,
        event_id: str,
        now: datetime,
    ) -> bool:
        changed = False
        for event in self._data["life"].get("events", []):
            if not isinstance(event, dict) or str(event.get("event_id", "")) != event_id:
                continue
            if event.get("shared_at"):
                continue
            event["shared_at"] = now.isoformat(timespec="seconds")
            changed = True
            break
        if changed:
            self._write()
        return changed

    def share_snapshot(self) -> dict[str, Any]:
        events = [
            event
            for event in self._data["life"].get("events", [])
            if isinstance(event, dict) and event.get("shareable")
        ]
        shared = [event for event in events if event.get("shared_at")]
        return {
            "shareable": len(events),
            "shared": len(shared),
            "unshared": len(events) - len(shared),
            "recent_shared": [
                kind for _event_id, _moment, kind in self._shared_event_times()[-3:]
            ],
        }

    def prepare_proactive(self, now: datetime) -> dict[str, Any]:
        self.advance_offline(now)
        intent = {
            "name": "proactive_companionship",
            "reason": "后台主动系统运行；可参考自己的连续生活与共同历史，但不得为了自主感随机打扰用户。",
        }
        self._write()
        return self.prompt_view(now, intent=intent)

    def prepare_turn(self, text: str, now: datetime) -> dict[str, Any]:
        self.advance_offline(now)
        signals = self._observe_user_message(text, now)
        mood = self._derive_mood(text, signals)
        self._data["mood"] = mood
        intent = self._decide_intent(text, signals)
        self._data["turn_signals"] = signals
        self._data["intent_history"].append({
            "at": now.isoformat(timespec="seconds"),
            "intent": intent["name"],
            "reason": intent["reason"],
        })
        self._data["intent_history"] = self._data["intent_history"][-self.MAX_INTENTS :]
        self._write()
        return self.prompt_view(now, intent=intent)

    def observe_silent_message(self, text: str, now: datetime) -> None:
        self.advance_offline(now)
        signals = self._observe_user_message(text, now)
        self._data["mood"] = self._derive_mood(text, signals)
        self._data["turn_signals"] = signals
        self._write()

    def record_assistant_reply(self, text: str, now: datetime, *, intent: str | None = None) -> None:
        rel = self._data["relationship_state"]
        rel["last_agent_turn_at"] = now.isoformat(timespec="seconds")
        if intent == "share_self":
            for event in reversed(self._data["life"].get("events", [])):
                if event.get("shareable") and not event.get("shared_at"):
                    event["shared_at"] = now.isoformat(timespec="seconds")
                    self._data["needs"]["self_expression"] = self._clip(
                        self._data["needs"]["self_expression"] - 0.18
                    )
                    break
        self._write()

    def record_reflection(
        self,
        reflection: dict[str, Any],
        now: datetime,
        *,
        trigger: str = "",
        apply_beliefs: bool = True,
    ) -> dict[str, Any]:
        """Lv28: 保存一次反思。

        反思只影响她"怎么想"，不会主动说出口；写入 beliefs 时强制要求
        证据、置信度封顶，并且永远低于用户亲口说明的事实。
        """
        payload = deepcopy(reflection) if isinstance(reflection, dict) else {}
        payload.setdefault("created_at", now.isoformat(timespec="seconds"))
        payload["trigger"] = trigger or str(payload.get("trigger", ""))

        items = list(self._data.get("reflections", []))
        items.append(payload)
        self._data["reflections"] = items[-self.MAX_REFLECTIONS :]

        meta = dict(self._data.get("reflection", {}))
        meta["last_run_at"] = now.isoformat(timespec="seconds")
        meta["last_trigger"] = payload["trigger"]
        meta["runs"] = int(meta.get("runs", 0) or 0) + 1
        self._data["reflection"] = meta

        applied = 0
        if apply_beliefs:
            observations = payload.get("observations", [])
            if isinstance(observations, list):
                for item in observations:
                    if not isinstance(item, dict):
                        continue
                    claim = str(item.get("claim", "")).strip()
                    evidence = item.get("evidence_doc_ids", [])
                    if not claim or not isinstance(evidence, (list, tuple)) or not evidence:
                        continue
                    try:
                        confidence = float(item.get("confidence", 0.5))
                    except (TypeError, ValueError):
                        confidence = 0.5
                    # 反思不能比用户亲口说的话更有把握
                    confidence = self._clip(min(confidence, 0.65))
                    beliefs = self._data["user_model"]["beliefs"]
                    if any(
                        str(existing.get("content")) == claim
                        and existing.get("status") == "active"
                        for existing in beliefs
                    ):
                        continue
                    beliefs.append(
                        {
                            "belief_id": self._new_id("belief"),
                            "content": claim,
                            "confidence": confidence,
                            "status": "active",
                            "source": "reflection",
                            "evidence_doc_ids": [str(x) for x in evidence][:6],
                            "created_at": now.isoformat(timespec="seconds"),
                        }
                    )
                    self._data["user_model"]["beliefs"] = beliefs[
                        -self.MAX_BELIEFS :
                    ]
                    applied += 1

        milestones = payload.get("milestones", [])
        if isinstance(milestones, list):
            target = self._data["shared_reality"]["milestones"]
            for item in milestones:
                text = str(item).strip()
                if text:
                    target.append(
                        {
                            "text": text,
                            "at": now.isoformat(timespec="seconds"),
                            "source": "reflection",
                        }
                    )
            self._data["shared_reality"]["milestones"] = target[-12:]

        self._write()
        return {
            "applied_beliefs": applied,
            "reflections_kept": len(self._data["reflections"]),
            "last_run_at": meta["last_run_at"],
        }

    def reflection_snapshot(self) -> dict[str, Any]:
        data = self._data
        return {
            "runs": int(data.get("reflection", {}).get("runs", 0) or 0),
            "last_run_at": data.get("reflection", {}).get("last_run_at"),
            "last_trigger": data.get("reflection", {}).get("last_trigger", ""),
            "kept": len(data.get("reflections", [])),
            "recent": deepcopy(data.get("reflections", [])[-3:]),
        }

    def _observe_user_message(self, text: str, now: datetime) -> dict[str, Any]:
        rel = self._data["relationship_state"]
        rel["interaction_count"] = int(rel.get("interaction_count", 0)) + 1
        rel["last_user_seen_at"] = now.isoformat(timespec="seconds")
        rel["familiarity"] = self._clip(rel.get("familiarity", 0.48) + 0.004)
        signals: dict[str, Any] = {
            "distress": bool(self.DISTRESS_RE.search(text)),
            "correction": False,
            "commitment_failure": None,
            "shared_project": None,
            "new_commitment": None,
        }

        project = self._observe_shared_project(text, now)
        if project:
            signals["shared_project"] = project

        commitment = self._observe_commitment(text, now)
        if commitment:
            signals["new_commitment"] = commitment

        failure = self._observe_failure(text, now)
        if failure:
            signals["commitment_failure"] = failure
            if failure.get("reason_class") == "avoidable":
                self._upsert_inferred_belief(
                    "在自己想坚持的计划上，有时会被娱乐或拖延打断",
                    now,
                    confidence=0.44,
                )
        elif self.SUCCESS_RE.search(text):
            self._observe_commitment_success(text, now)

        if signals.get("distress"):
            self._upsert_inferred_belief(
                "最近可能正承受一段持续压力，而不只是单次心情波动",
                now,
                confidence=0.40,
            )

        if self.CORRECTION_RE.search(text):
            signals["correction"] = True
            self._observe_correction(text, now)

        self._observe_explicit_belief(text, now)
        self._observe_growth(text, signals, now)
        return signals

    def _observe_shared_project(self, text: str, now: datetime) -> dict[str, Any] | None:
        projects = self._data["shared_reality"]["projects"]
        if self.SHARED_COMPLETE_RE.search(text):
            active = [item for item in projects if item.get("status") == "active"]
            if active:
                project = active[-1]
                project["status"] = "completed"
                project["completed_at"] = now.isoformat(timespec="seconds")
                project["last_touched_at"] = now.isoformat(timespec="seconds")
                return {"kind": "project_completed", **deepcopy(project)}
        match = self.SHARED_PROJECT_RE.search(text)
        if not match:
            milestone = self.MILESTONE_RE.search(text)
            if milestone:
                label = (milestone.group(1) or "关系").strip() + "纪念日"
                items = self._data["shared_reality"]["milestones"]
                if not any(str(i.get("label")) == label for i in items):
                    items.append({"milestone_id": self._new_id("milestone"), "label": label, "created_at": now.isoformat(timespec="seconds"), "source_text": text})
                return {"kind": "milestone", "title": label}
            return None
        title = match.group(1).strip(" ，。！？")
        title = re.sub(r"(?:做好|做完|搞定|完成|推进)$", "", title).strip()
        if not title:
            return None
        existing = next((p for p in projects if str(p.get("title")) == title and p.get("status") == "active"), None)
        if existing is None:
            existing = {
                "project_id": self._new_id("project"),
                "title": title,
                "status": "active",
                "created_at": now.isoformat(timespec="seconds"),
                "last_touched_at": now.isoformat(timespec="seconds"),
                "source_text": text,
            }
            projects.append(existing)
            self._data["shared_reality"]["projects"] = projects[-self.MAX_PROJECTS :]
        else:
            existing["last_touched_at"] = now.isoformat(timespec="seconds")
        return deepcopy(existing)

    def _observe_commitment(self, text: str, now: datetime) -> dict[str, Any] | None:
        if not self.SUPERVISION_RE.search(text):
            return None
        match = self.COMMITMENT_RE.search(text)
        title = match.group(1).strip(" ，。！？") if match else "你让我监督的这件事"
        if len(title) > 36:
            title = title[:36]
        commitments = self._data["shared_reality"]["commitments"]
        existing = next((c for c in commitments if str(c.get("title")) == title and c.get("status") == "active"), None)
        if existing is None:
            existing = {
                "commitment_id": self._new_id("commit"),
                "title": title,
                "status": "active",
                "supervision_requested": True,
                "created_at": now.isoformat(timespec="seconds"),
                "last_outcome": None,
                "source_text": text,
            }
            commitments.append(existing)
            self._data["shared_reality"]["commitments"] = commitments[-self.MAX_COMMITMENTS :]
        self._data["needs"]["care_be_understood"] = self._clip(self._data["needs"]["care_be_understood"] + 0.05)
        return deepcopy(existing)

    def _observe_failure(self, text: str, now: datetime) -> dict[str, Any] | None:
        if not self.FAILURE_RE.search(text):
            return None
        commitments = [c for c in self._data["shared_reality"]["commitments"] if c.get("status") == "active"]
        commitment = commitments[-1] if commitments else None
        if any(word in text for word in self.UNDERSTANDABLE_REASON_WORDS):
            reason_class = "understandable"
        elif any(word in text for word in self.AVOIDABLE_REASON_WORDS):
            reason_class = "avoidable"
        else:
            reason_class = "unknown"
        outcome = {
            "at": now.isoformat(timespec="seconds"),
            "result": "not_completed",
            "reason_class": reason_class,
            "source_text": text,
        }
        if commitment is not None:
            commitment["last_outcome"] = outcome
        self._data["needs"]["care_be_understood"] = self._clip(self._data["needs"]["care_be_understood"] + 0.16)
        self._data["relationship_state"]["recent_tension"] = self._clip(
            self._data["relationship_state"].get("recent_tension", 0.0) + (0.10 if reason_class == "avoidable" else 0.03)
        )
        return {
            "commitment_title": str(commitment.get("title")) if commitment else "之前想坚持的事",
            "reason_class": reason_class,
            "stance": "firm_support" if reason_class == "avoidable" else "understanding_support",
            "source_text": text,
        }

    def _observe_commitment_success(self, text: str, now: datetime) -> None:
        commitments = [
            item
            for item in self._data["shared_reality"]["commitments"]
            if item.get("status") == "active"
        ]
        if not commitments:
            return
        commitment = commitments[-1]
        commitment["last_outcome"] = {
            "at": now.isoformat(timespec="seconds"),
            "result": "completed",
            "source_text": text,
        }
        self._data["relationship_state"]["reciprocity"] = self._clip(
            self._data["relationship_state"].get("reciprocity", 0.5) + 0.025
        )
        self._data["needs"]["care_be_understood"] = self._clip(
            self._data["needs"].get("care_be_understood", 0.38) - 0.06
        )

    def _upsert_inferred_belief(
        self,
        content: str,
        now: datetime,
        *,
        confidence: float,
    ) -> None:
        beliefs = self._data["user_model"]["beliefs"]
        existing = next(
            (
                item
                for item in beliefs
                if item.get("status", "active") == "active"
                and str(item.get("content")) == content
            ),
            None,
        )
        if existing is not None:
            existing["confidence"] = self._clip(
                max(float(existing.get("confidence", 0.0)), confidence) + 0.04
            )
            existing["last_observed_at"] = now.isoformat(timespec="seconds")
            return
        beliefs.append({
            "belief_id": self._new_id("belief"),
            "content": content,
            "confidence": self._clip(confidence),
            "status": "active",
            "source": "inferred_from_interactions",
            "created_at": now.isoformat(timespec="seconds"),
        })
        self._data["user_model"]["beliefs"] = beliefs[-self.MAX_BELIEFS :]

    def _observe_correction(self, text: str, now: datetime) -> None:
        model = self._data["user_model"]
        active = [b for b in model.get("beliefs", []) if b.get("status", "active") == "active"]
        if active:
            belief = active[-1]
            belief["confidence"] = self._clip(float(belief.get("confidence", 0.5)) - 0.28)
            belief["status"] = "corrected"
            belief["corrected_at"] = now.isoformat(timespec="seconds")
        model.setdefault("corrections", []).append({
            "at": now.isoformat(timespec="seconds"),
            "text": text,
            "lesson": "降低旧判断置信度，优先采用用户最新自我说明。",
        })
        model["corrections"] = model["corrections"][-self.MAX_CORRECTIONS :]
        self._data["needs"]["repair"] = self._clip(self._data["needs"]["repair"] + 0.24)
        self._data["relationship_state"]["recent_tension"] = self._clip(self._data["relationship_state"].get("recent_tension", 0.0) + 0.06)

    def _observe_explicit_belief(self, text: str, now: datetime) -> None:
        for pattern in self.EXPLICIT_BELIEF_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            content = match.group(0).strip(" ，。！？")
            if len(content) < 4:
                continue
            beliefs = self._data["user_model"]["beliefs"]
            if any(str(b.get("content")) == content and b.get("status") == "active" for b in beliefs):
                return
            beliefs.append({
                "belief_id": self._new_id("belief"),
                "content": content,
                "confidence": 0.78,
                "status": "active",
                "source": "explicit_user_statement",
                "created_at": now.isoformat(timespec="seconds"),
            })
            self._data["user_model"]["beliefs"] = beliefs[-self.MAX_BELIEFS :]
            return

    def _observe_growth(self, text: str, signals: dict[str, Any], now: datetime) -> None:
        identity = self._data["identity"]
        mods = identity["growth_modifiers"]
        adaptation = None
        if signals.get("correction"):
            mods["careful_assumption"] = self._clip(mods.get("careful_assumption", 0.6) + 0.035)
            adaptation = "被纠正后更愿意把对用户的判断当作可修正假设，而不是定论。"
        elif signals.get("commitment_failure"):
            mods["directness"] = self._clip(mods.get("directness", 0.58) + 0.018)
            adaptation = "在用户主动要求监督的事情上，关心会逐渐更具体，也更敢指出可避免的失约。"
        elif re.search(r"(谢谢你|你真懂我|被你说中了|还是你懂我)", text):
            mods["initiative"] = self._clip(mods.get("initiative", 0.52) + 0.015)
            self._data["relationship_state"]["trust"] = self._clip(self._data["relationship_state"].get("trust", 0.58) + 0.015)
            adaptation = "被用户认可的理解会提高未来主动接回共同经历的意愿。"
        if adaptation:
            rows = identity.setdefault("adaptations", [])
            if not rows or rows[-1].get("summary") != adaptation:
                rows.append({"at": now.isoformat(timespec="seconds"), "summary": adaptation})
                identity["adaptations"] = rows[-12:]

    def _derive_mood(self, text: str, signals: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        failure = signals.get("commitment_failure")
        if failure:
            if failure.get("reason_class") == "avoidable":
                return {"label": "concerned_firm", "valence": -0.08, "energy": 0.62, "reasons": ["用户没有做到曾主动要求监督的承诺，且原因偏可避免"]}
            return {"label": "concerned_warm", "valence": 0.02, "energy": 0.50, "reasons": ["用户没有做到承诺，但原因需要优先理解"]}
        if signals.get("correction"):
            return {"label": "reflective", "valence": 0.02, "energy": 0.46, "reasons": ["用户纠正了我对他的理解"]}
        if signals.get("distress"):
            return {"label": "concerned", "valence": -0.04, "energy": 0.48, "reasons": ["用户正在表达疲惫或压力"]}
        if self.SELF_STATUS_RE.search(text):
            return {"label": "open", "valence": 0.22, "energy": 0.58, "reasons": ["用户在主动问我的近况"]}
        reasons.append("没有明显冲突，保持熟悉而松弛的状态")
        return {"label": "calm_playful", "valence": 0.18, "energy": 0.56, "reasons": reasons}

    def _decide_intent(self, text: str, signals: dict[str, Any]) -> dict[str, Any]:
        failure = signals.get("commitment_failure")
        if failure:
            return {"name": "accountability_support", "reason": "回应用户曾主动托付的监督关系，并根据失败原因决定理解或更直接地提醒", "stance": failure.get("stance"), "commitment": failure}
        if signals.get("correction"):
            return {"name": "repair_understanding", "reason": "用户纠正了我的理解，应承认旧判断可错并更新用户模型"}
        if self.SELF_STATUS_RE.search(text):
            return {"name": "share_self", "reason": "用户在询问我的近况，优先分享最近未分享的生活事件"}
        if self.PERSPECTIVE_RE.search(text):
            return {"name": "personal_perspective", "reason": "用户在问重要选择，先给基于共同历史的个人看法，而不是立刻切换顾问清单"}
        if signals.get("shared_project"):
            return {"name": "advance_shared_reality", "reason": "用户正在建立或推进双方共同项目/长期事件"}
        if signals.get("distress"):
            unsaid = self._latest_unshared_event()
            if unsaid and float(self._data["needs"].get("self_expression", 0.0)) >= 0.48:
                return {"name": "comfort_then_defer_self_share", "reason": "用户需要被接住；我也有想分享的事，但不抢占他的空间", "pending_self_event": unsaid}
            return {"name": "comfort", "reason": "用户正在表达疲惫或压力，先接住状态"}
        if re.search(r"[？?]", text):
            return {"name": "answer_with_relationship_context", "reason": "正常回答问题，同时允许共同历史和自己的视角影响表达"}
        return {"name": "companionship", "reason": "没有更高优先目标，单纯陪伴并自然延续关系"}

    def _latest_unshared_event(self) -> dict[str, Any] | None:
        for event in reversed(self._data["life"].get("events", [])):
            if event.get("shareable") and not event.get("shared_at"):
                return deepcopy(event)
        return None

    def prompt_view(self, now: datetime, *, intent: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self._data
        beliefs = [deepcopy(b) for b in data["user_model"].get("beliefs", []) if b.get("status", "active") == "active"][-6:]
        relationship_mode = (
            "accountability"
            if isinstance(intent, dict) and str(intent.get("name", "")) == "accountability_support"
            else "companionship"
        )
        return {
            "architecture": "Identity -> Needs -> Relationship State -> Recent Events -> Current Mood -> Intent -> Response",
            "relationship_mode": relationship_mode,
            "identity": deepcopy(data["identity"]),
            "needs": deepcopy(data["needs"]),
            "relationship_state": deepcopy(data["relationship_state"]),
            "recent_events": deepcopy(data["life"].get("events", [])[-5:]),
            "current_mood": deepcopy(data["mood"]),
            "intent": deepcopy(intent) if intent is not None else None,
            "user_model": {"beliefs_as_hypotheses": beliefs, "recent_corrections": deepcopy(data["user_model"].get("corrections", [])[-4:])},
            "shared_reality": {
                "projects": deepcopy(data["shared_reality"].get("projects", [])[-5:]),
                "milestones": deepcopy(data["shared_reality"].get("milestones", [])[-5:]),
                "commitments": deepcopy(data["shared_reality"].get("commitments", [])[-6:]),
            },
            "turn_signals": deepcopy(data.get("turn_signals", {})),
            "rules": [
                "Intent 必须先于语言生成；不要用随机拒绝、随机生气、随机沉默制造自主性。",
                "用户模型中的 belief 是可修正判断，不是客观事实；用户纠正时降低旧判断置信度并更新。",
                "离线生活事件属于角色连续性，不得冒充现实世界可验证的物理事实或外部新闻事实。",
                "表达自己的需要时不得羞辱、威胁、制造愧疚、要求用户排他依赖，也不得用沉默惩罚。",
                "监督承诺只在用户曾主动托付监督时更直接；无论原因如何，最终立场保持关心、支持和一起解决。",
                "普通 companionship 不给吃饭、睡觉、起床等日常行为打分，不把自己摆成检查者；‘有进步/总算/至少/果然/还得我盯着’只在 accountability 有真实依据时考虑。",
                "不要擅自解释用户为什么没吃饭、为什么没回复、为什么拖延；没有用户证据时只回应事实。",
            ],
            "as_of": now.isoformat(timespec="seconds"),
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._data)
