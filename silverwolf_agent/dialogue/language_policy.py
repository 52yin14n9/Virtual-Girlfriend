from __future__ import annotations

import re
from typing import Any, Iterable


# These tags describe *how* a message behaves, not only which nouns it uses.
# The proactive selector can cool down a recently over-used reaction style even
# when the literal template text is different.
_SEMANTIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("question", re.compile(r"[？?]")),
    ("directive", re.compile(r"(?:先|快|去|别|记得|该|要不要|可以去).{0,16}(?:吃|睡|休息|喝|拿|带|放|停|歇|走|做|继续)")),
    ("food_check", re.compile(r"(?:午饭|晚饭|饭|吃东西|吃点|吃了|吃过|肚子)")),
    ("progress_check", re.compile(r"(?:进度|项目|开发|工作|任务|推进|收尾|卡住)")),
    ("state_check", re.compile(r"(?:累不累|心情|过得怎么样|睡得怎么样|还好吗|开心吗)")),
    ("playful", re.compile(r"(?:开机|上线|通关|进度条|频道|被窝|键盘|项目不会跑|掉线|关卡)")),
    ("management", re.compile(r"(?:汇报|检查一下|检查点|盯着你|督促你|管着你|交差|打卡)")),
    ("evaluation", re.compile(r"(?:有进步|总算|终于|至少|果然)")),
)

# Styles that benefit from not appearing back-to-back. Topic tags such as
# food_check are intentionally excluded: lunch messages obviously still talk
# about lunch, but they can alternate between a question, a short directive,
# a playful line, and a simple acknowledgement.
_COOLDOWN_TAGS = {
    "question",
    "directive",
    "progress_check",
    "state_check",
    "playful",
    "management",
    "evaluation",
}


def infer_semantic_tags(text: str) -> tuple[str, ...]:
    value = str(text or "")
    return tuple(
        name
        for name, pattern in _SEMANTIC_RULES
        if pattern.search(value)
    )


def semantic_overlap_score(
    candidate_tags: Iterable[str],
    recent_tags: Iterable[str],
) -> int:
    candidate = set(candidate_tags) & _COOLDOWN_TAGS
    recent = set(recent_tags) & _COOLDOWN_TAGS
    return len(candidate & recent)


def relationship_mode_from_cognition(
    cognition_context: dict[str, Any] | None,
) -> str:
    if not isinstance(cognition_context, dict):
        return "companionship"
    intent = cognition_context.get("intent", {})
    if not isinstance(intent, dict):
        return "companionship"
    if str(intent.get("name", "")) == "accountability_support":
        return "accountability"
    return "companionship"


# Ordinary companionship must not silently turn into a teacher/parent scoring
# the user. The LLM prompt is the first defence; this guard is a deterministic
# last line for the recurring failure mode seen in real chats.
_HIGH_RISK_CLAUSE = re.compile(
    r"(?:"
    r"有进步|"
    r"(?:总算|终于).{0,18}(?:动起来|知道|记得|主动|肯|会)|"
    r"至少.{0,28}(?:记得|知道|肯|会|没忘)|"
    r"果然.{0,30}(?:盯|催|管|监督)|"
    r"还得我.{0,24}(?:盯|催|管|监督)|"
    r"(?:跟我|向我).{0,6}汇报|"
    r"我来检查一下|晚上的检查点|"
    r"吃完.{0,8}(?:跟我说|告诉我|汇报)|"
    r"不然我.{0,8}(?:怀疑|又得怀疑)"
    r")"
)

_PRESSURE_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"别又(?=\S)"), "别"),
    (re.compile(r"你不会又(?=\S)"), "你不会"),
    (re.compile(r"有没有又(?=\S)"), "有没有"),
)


def _fallback_for_input(user_input: str) -> str:
    text = str(user_input or "")
    if re.search(r"(?:买好|买了|拿饭|取饭|外卖)", text):
        return "买好了就行，等会儿趁热吃"
    if re.search(r"(?:没吃|吃饭|午饭|晚饭|去吃)", text):
        return "嗯，去吃吧，别空着肚子太久"
    if re.search(r"(?:困|睡觉|去睡|要睡)", text):
        return "嗯，先去睡吧"
    if re.search(r"(?:累|忙|开发|工作|学习)", text):
        return "嗯，我知道了。先按你自己的节奏来"
    return "嗯，我知道了"


def companionship_language_guard(
    text: str,
    *,
    relationship_mode: str,
    user_input: str = "",
) -> str:
    """Soften accidental management language outside explicit accountability.

    This intentionally does *not* forbid playful directness. It only removes
    clauses that score the user's ordinary self-care, claim supervisory credit,
    or demand a report without an explicit accountability commitment.
    """

    value = str(text or "").strip()
    if not value or relationship_mode == "accountability":
        return value
    if not _HIGH_RISK_CLAUSE.search(value):
        for pattern, replacement in _PRESSURE_REWRITES:
            value = pattern.sub(replacement, value)
        return value

    # Split into chat-sized clauses. If a clause contains a high-risk pattern,
    # drop that clause rather than trying to preserve the teacher-like premise.
    pieces = re.split(r"(?<=[。！？!?])|(?<=；)|(?<=;)\s*", value)
    kept: list[str] = []
    for piece in pieces:
        clause = piece.strip()
        if not clause:
            continue
        if _HIGH_RISK_CLAUSE.search(clause):
            continue
        for pattern, replacement in _PRESSURE_REWRITES:
            clause = pattern.sub(replacement, clause)
        if clause:
            kept.append(clause)

    softened = "".join(kept).strip()
    softened = re.sub(r"([。！？!?])\1+", r"\1", softened)
    softened = re.sub(r"^[，,、；;\s]+", "", softened)
    if len(re.sub(r"\W", "", softened)) < 3:
        return _fallback_for_input(user_input)
    return softened
