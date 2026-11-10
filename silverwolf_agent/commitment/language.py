"""Lv27: 承诺场景的确定性自然语言渲染（兜底层）。

语料库 + 模型只负责让措辞更好听；这里保证即使模型不可用、
语料库为空、或输出被判为不合格，承诺相关的话仍然说得像人话，
而不是"提醒你一下：计划已创建"。
"""

from __future__ import annotations

from hashlib import sha256

from .contracts import (
    SLOT_CLOCK,
    SLOT_START,
    SLOT_WEEKDAYS,
    SLOT_WEEKS,
    Commitment,
    CommitmentSeed,
    weekday_list_label,
)


def _pick(options: tuple[str, ...], key: str) -> str:
    if not options:
        return ""
    digest = sha256(key.encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _rotate(
    options: tuple[str, ...],
    key: str,
    turn_index: int,
) -> str:
    """同一槽位连续追问时保证换说法，而不是靠散列碰运气。"""
    if not options:
        return ""
    digest = sha256(key.encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16) % len(options)
    index = (offset + max(0, int(turn_index) - 1)) % len(options)
    return options[index]


def clock_human(clock: str) -> str:
    """把 10:00 说成 10点，把 10:30 说成 10点半。"""
    try:
        hour_text, minute_text = clock.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        return clock or "到点"
    if minute == 0:
        return f"{hour}点"
    if minute == 30:
        return f"{hour}点半"
    return f"{hour}点{minute}分"


def date_human(value: str, *, today_label: bool = False) -> str:
    try:
        raw = value.split("T", 1)[0]
        _, month, day = raw.split("-")
        prefix = "今天" if today_label else ""
        return f"{prefix}{int(month)}月{int(day)}日"
    except (ValueError, AttributeError):
        return value or "那天"


# ---------------- 追问 ----------------

def weekly_phrase(weekdays: tuple[int, ...] | list[int]) -> str:
    """(5,) -> 每周六；(5,6) -> 每周六、周日。"""
    label = weekday_list_label(weekdays)
    if not label:
        return "每周"
    if label.startswith("周"):
        return "每" + label
    return "每" + label


def render_question(
    *,
    slot: str,
    seed: CommitmentSeed,
    alias: str = "宝",
    variant_key: str = "",
    turn_index: int = 1,
) -> str:
    title = seed.title or "这件事"
    key = f"{variant_key}|{slot}|{title}"

    if slot == SLOT_START:
        options = (
            f"{title}啊，行。你打算这周就开始，还是下周再进状态？",
            f"可以。{title}这件事，从这周算起还是下周？",
            f"嗯，记下了。{title}你想什么时候正式开始？这周还是下周？",
        )
        return _rotate(options, key, turn_index)

    if slot == SLOT_CLOCK:
        options = (
            "那几点开始？上午还是下午，给我个大概钟点就行。",
            f"{alias}，那天你一般几点能坐下来？说个时间我照着喊你。",
            "时间上你定，几点开始比较现实？",
        )
        return _rotate(options, key, turn_index)

    if slot == SLOT_WEEKDAYS:
        options = (
            "安排在周末哪天？周六、周日，还是两天哪个方便算哪天？",
            "具体是哪几天？周六、周日，还是两天都留出来？",
            "周末两天你更想固定哪一天？也可以两天随便挑一天做。",
        )
        return _rotate(options, key, turn_index)

    if slot == SLOT_WEEKS:
        options = (
            "这一轮你想先排几周？四周、八周，还是到考试前？",
            "大概持续多久？先来几周看看也行。",
            "你打算连着做几周？我按周数给你排。",
        )
        return _rotate(options, key, turn_index)

    return "再说清楚一点，我好照着安排。"


_SLOT_SHORT = {
    SLOT_START: "这周还是下周",
    SLOT_CLOCK: "几点开始",
    SLOT_WEEKDAYS: "周末哪天",
    SLOT_WEEKS: "先排几周",
}


def render_question_multi(
    *,
    slots: tuple[str, ...] | list[str],
    seed: CommitmentSeed,
    alias: str = "宝",
    variant_key: str = "",
    turn_index: int = 1,
) -> str:
    """一次问两个信息点（默认上限），比连问两轮更像真人说话。"""
    picked = [slot for slot in slots if slot in _SLOT_SHORT]
    if not picked:
        return "再说清楚一点，我好照着安排。"
    if len(picked) == 1:
        return render_question(
            slot=picked[0],
            seed=seed,
            alias=alias,
            variant_key=variant_key,
            turn_index=turn_index,
        )

    title = seed.title or "这件事"
    first = _SLOT_SHORT[picked[0]]
    second = _SLOT_SHORT[picked[1]]
    key = f"{variant_key}|multi|{title}|{picked[0]}|{picked[1]}"
    options = (
        f"{title}啊，行。{first}，{second}？",
        f"行。{first}，还有{second}？",
        f"可以。{first}，{second}？说个大概就行。",
    )
    return _rotate(options, key, turn_index)


# ---------------- 确认 ----------------

def render_confirmation(
    commitment: Commitment,
    *,
    alias: str = "宝",
) -> str:
    weekdays = weekday_list_label(commitment.weekdays)
    clock = clock_human(commitment.clock)
    start = date_human(commitment.starts_on)
    head = f"好，{commitment.title}"
    if commitment.soft_weekend:
        tail = (
            f"那就从{start}开始，每个周末 {clock} 我喊你，"
            f"周末哪天做完都算一次，一共 {commitment.total_weeks} 周。"
        )
    else:
        tail = (
            f"那就从{start}开始，{weekly_phrase(commitment.weekdays)} {clock}，"
            f"我喊你，一共 {commitment.total_weeks} 周。"
        )
    return f"{head}。{tail}"


def render_long_commitment_warning(
    commitment: Commitment,
) -> str:
    if commitment.total_weeks <= 12:
        return ""
    return "周数不短，中间想调随时跟我说。"


# ---------------- 到期提醒 ----------------

def render_occurrence_start(
    commitment: Commitment,
    *,
    week_index: int,
    is_primary: bool = True,
    alias: str = "宝",
    variant_key: str = "",
) -> str:
    title = commitment.title
    clock = clock_human(commitment.clock)
    key = f"{variant_key}|due|{commitment.commitment_id}|{week_index}|{is_primary}"

    if week_index == 1:
        options = (
            f"{alias}，{title}今天开始，第 1/{commitment.total_weeks} 周。{clock}了，动起来。",
            f"开始了。{title}第 1/{commitment.total_weeks} 周，就今天。",
            f"{clock} 到，{title}第 1/{commitment.total_weeks} 周。先做起来，别等状态。",
        )
        return _pick(options, key)

    if week_index >= commitment.total_weeks:
        options = (
            f"{alias}，{title}最后一周了，第 {week_index}/{commitment.total_weeks} 周。收个尾。",
            f"最后一期，{title}第 {week_index}/{commitment.total_weeks} 周。做完这轮就结束了。",
        )
        return _pick(options, key)

    options = (
        f"{alias}，{title}第 {week_index}/{commitment.total_weeks} 周。{clock}了，该开始了。",
        f"{clock} 到，{title}这周的部分。第 {week_index}/{commitment.total_weeks} 周。",
        f"第 {week_index}/{commitment.total_weeks} 周，{title}。别拖到晚上。",
    )
    return _pick(options, key)


def render_soft_nudge(
    commitment: Commitment,
    *,
    week_index: int,
    alias: str = "宝",
    variant_key: str = "",
) -> str:
    title = commitment.title
    key = f"{variant_key}|soft|{commitment.commitment_id}|{week_index}"
    options = (
        f"这周的{title}还没动吧？今天是最后一天周末了。",
        f"{alias}，周末要过完了，{title}这周还差一次。",
        f"第 {week_index}/{commitment.total_weeks} 周，{title}今天还来得及。",
    )
    return _pick(options, key)


def render_progress(
    commitment: Commitment,
    *,
    alias: str = "宝",
) -> str:
    done = len(commitment.completed_weeks)
    skipped = len(commitment.skipped_weeks)
    tail = f"，跳过 {skipped} 周" if skipped else ""
    return (
        f"{commitment.title}：已完成 {done}/{commitment.total_weeks} 周{tail}，"
        f"接下来是第 {commitment.current_week()} 周。"
    )


def render_finish(
    commitment: Commitment,
    *,
    alias: str = "宝",
    variant_key: str = "",
) -> str:
    key = f"{variant_key}|finish|{commitment.commitment_id}"
    options = (
        f"{commitment.title}这一轮做完了，{commitment.total_weeks} 周全清。",
        f"全部完成，{commitment.title} {commitment.total_weeks} 周没断。",
        f"{commitment.title}收官，{commitment.total_weeks} 周。做完了。",
    )
    return _pick(options, key)


def render_week_done(
    commitment: Commitment,
    *,
    week_index: int,
    alias: str = "宝",
    variant_key: str = "",
) -> str:
    key = f"{variant_key}|weekdone|{commitment.commitment_id}|{week_index}"
    options = (
        f"记下了，第 {week_index}/{commitment.total_weeks} 周完成。",
        f"好，这周算完成（{week_index}/{commitment.total_weeks}）。",
        f"收到，第 {week_index} 周打勾。",
    )
    return _pick(options, key)


def render_skip_ack(
    commitment: Commitment,
    *,
    week_index: int,
    alias: str = "宝",
) -> str:
    return (
        f"这周跳过，记下了。{commitment.title}还剩 "
        f"{commitment.remaining_weeks()} 周，下周照旧。"
    )


def render_cancel_ack(
    commitment: Commitment,
    *,
    alias: str = "宝",
) -> str:
    return f"好，{commitment.title}这个安排我停了，之后不喊你了。"


def render_edit_ack(
    commitment: Commitment,
    *,
    alias: str = "宝",
) -> str:
    weekdays = weekday_list_label(commitment.weekdays)
    clock = clock_human(commitment.clock)
    if weekdays == "周六、周日":
        schedule = f"每个周末 {clock}"
    else:
        schedule = f"{weekly_phrase(commitment.weekdays)} {clock}"
    return (
        f"改好了：{commitment.title}，{schedule}，"
        f"还剩 {commitment.remaining_weeks()} 周。"
    )


def render_nothing_pending(alias: str = "宝") -> str:
    return "现在没有正在进行的长期安排。"
