from __future__ import annotations

import re
from datetime import datetime

from .schedule_intent import clean_schedule_title


_FIRST_PERSON_ACTION_PREFIX = re.compile(
    r"^我(?:今天|明天|等会儿|待会儿)?(?:要|得|该|需要|应该|准备|打算|会)?"
    r"(?=(?:去|到|回|出发|上班|下班|开会|参加|学习|复习|写|做|交|提交|吃|喝|睡|起|买|拿|取|联系|打|看|训练|运动|工作|赶|收|发))"
)


def normalize_reminder_action(value: str) -> str:
    """Turn an internal reminder title into a phrase spoken *to* the user.

    The stored title may come from an LLM, old data, or a rule parser.  This
    function deliberately fixes perspective and strips reminder-system words
    before any user-facing sentence is produced.
    """
    action = clean_schedule_title(value)
    action = _FIRST_PERSON_ACTION_PREFIX.sub("", action).strip(" ，,。！？!?的")

    # Old/model-generated titles sometimes keep an imperative shell.
    action = re.sub(r"^(?:记得|别忘了|别忘|需要|应该|该)(?=\S)", "", action)
    action = action.strip(" ，,。！？!?的")
    return action or "那件事"


def spoken_action(value: str) -> str:
    """Return a naturally speakable action phrase for a due reminder."""
    action = normalize_reminder_action(value)

    # “到工作室” as a raw title sounds odd after “该”.  In a reminder the
    # natural conversational instruction is to go there now.
    arrive = re.fullmatch(r"到(?P<place>[^，,。！？!?\n]{1,24})", action)
    if arrive:
        place = arrive.group("place").strip()
        if place:
            return f"去{place}"

    return action


def render_due_reminder(
    *,
    title: str,
    casual_alias: str = "宝",
) -> str:
    """Render a scheduled reminder as something a close person would say.

    It intentionally avoids notification vocabulary such as “提醒你一下”,
    “我记着呢”, “计划”, and raw internal titles.
    """
    alias = casual_alias.strip() or "宝"
    action = spoken_action(title)

    if re.search(r"(?:睡觉|睡眠|上床睡|早点睡|去睡|睡下)", action):
        return f"{alias}，该睡觉啦"
    if re.search(r"^(?:起床|起来)$", action):
        return f"{alias}，该起床啦"
    if re.search(r"(?:吃药|服药|用药)", action):
        return f"{alias}，该吃药啦"
    if re.search(r"(?:吃早饭|吃早餐|早餐)", action):
        return f"{alias}，该吃早饭啦"
    if re.search(r"(?:吃午饭|午饭)", action):
        return f"{alias}，该吃午饭啦"
    if re.search(r"(?:吃晚饭|晚饭)", action):
        return f"{alias}，该吃晚饭啦"
    if action == "结束休息":
        return "时间到啦，星。休息结束，该起来活动一下了"
    if action == "主动联系星":
        return "时间到啦，星。我没忘，来找你了"

    return f"{alias}，该{action}啦"


def render_schedule_confirmation(
    *,
    title: str,
    due_at: str,
    now: datetime,
    recurrence: str,
    friendly_due: str,
    clock: str,
    weekday: str,
) -> str:
    """Confirm a successfully persisted reminder without sounding like UI."""
    action = spoken_action(title)

    if action == "主动联系星":
        when = friendly_due.strip()
        gap = " " if re.search(r"\d$", when) else ""
        return f"好，{when}{gap}我会主动来找你"

    if action == "结束休息":
        return f"好，你先休息，{friendly_due.strip()}我叫你起来"

    if recurrence == "daily":
        if re.search(r"(?:睡觉|睡眠|睡下|去睡)", action):
            return (
                f"好啊，以后每天 {clock} 我叫你睡觉。"
                "到点就别再偷偷熬夜了。"
            )
        if re.search(r"^(?:起床|起来)$", action):
            return f"好，以后每天 {clock} 我叫你起床"
        return f"好，以后每天 {clock} 我来喊你{action}"

    if recurrence == "weekly":
        return f"好，以后每周{weekday} {clock} 我来喊你{action}"

    when = friendly_due.strip()
    gap = " " if re.search(r"\d$", when) else ""
    if re.search(r"^(?:取|拿|收)快递", action):
        return f"好，{when}{gap}我敲你一下，记得{action}"
    return f"好，{when}{gap}我来喊你{action}"
