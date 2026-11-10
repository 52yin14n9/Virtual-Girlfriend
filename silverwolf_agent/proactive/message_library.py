from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Iterable

from ..dialogue.language_policy import infer_semantic_tags, semantic_overlap_score


@dataclass(frozen=True)
class ProactiveMessageChoice:
    template_id: str
    template_group: str
    content: str
    expects_reply: bool
    semantic_tags: tuple[str, ...] = ()


class ProactiveMessageLibrary:
    """
    主动消息模板库。

    选择原则：
    1. 先根据时间段和最近对话选择模板组；
    2. 排除最近使用过的模板；
    3. 使用稳定散列从剩余候选中选择，避免每次启动都固定第一条；
    4. 每条消息带 template_id，真正发送后由 Scheduler 记录。
    """

    ROUTINE_TEMPLATES: dict[
        str,
        tuple[tuple[str, str, bool], ...],
    ] = {
        "morning_general": (
            (
                "morning_01",
                "早，{name}。醒了吗？今天准备从哪件事开始？",
                True,
            ),
            (
                "morning_02",
                "早上好，{name}。该从被窝里登出了，昨晚睡得怎么样？",
                True,
            ),
            (
                "morning_03",
                "{name}，早。先喝口水再开机，今天有什么安排？",
                True,
            ),
            (
                "morning_04",
                "起床时间到啦，{alias}。今天想认真推进什么？",
                True,
            ),
            (
                "morning_05",
                "早安，{name}。新一天的进度条已经开始跑了，你醒透了吗？",
                True,
            ),
            (
                "morning_06",
                "{name}，太阳都上线了。睡得还舒服吗？",
                True,
            ),
            (
                "morning_07",
                "早呀，{alias}。别急着刷消息，先伸个懒腰，今天准备怎么过？",
                True,
            ),
            (
                "morning_08",
                "该起床啦，{name}。今天是轻松一点，还是继续推进手头的东西？",
                True,
            ),
            (
                "morning_09",
                "早上好，{name}。脑子开机了吗，还是还想赖一会儿床？",
                True,
            ),
            (
                "morning_10",
                "{name}，早。今天也不用一下把所有事做完，先挑最重要的一件吧。",
                False,
            ),
            (
                "morning_11",
                "早安，{alias}。昨晚有没有好好睡觉？",
                True,
            ),
            (
                "morning_12",
                "早，{name}。我来报到啦，你也该慢慢醒过来了。",
                False,
            ),
        ),
        "morning_busy": (
            (
                "morning_busy_01",
                "早，{name}。昨天忙了那么久，今天别一醒就把自己塞进工作里。",
                False,
            ),
            (
                "morning_busy_02",
                "{name}，该醒啦。今天继续开发之前，先吃点东西、清醒一下。",
                False,
            ),
            (
                "morning_busy_03",
                "早上好，{alias}。知道你最近事情多，不过先把自己照顾好再开工。",
                False,
            ),
            (
                "morning_busy_04",
                "起床啦，{name}。今天的任务不会跑，慢慢启动就好。",
                False,
            ),
            (
                "morning_busy_05",
                "早，{name}。昨天已经很拼了，今天别忘了给自己留点喘气的空间。",
                True,
            ),
            (
                "morning_busy_06",
                "{name}，新的一天开始了。今天还要继续折腾项目吗？",
                True,
            ),
        ),
        "noon_unfed": (
            (
                "noon_unfed_01",
                "午安，{alias}。忙到现在了吗？午饭吃了没有？",
                True,
            ),
            (
                "noon_unfed_02",
                "{name}，中午啦。先别和事情死磕，去找点东西吃。",
                False,
            ),
            (
                "noon_unfed_03",
                "午饭时间到。{name}，你今天准备吃什么？",
                True,
            ),
            (
                "noon_unfed_04",
                "中午好，{alias}。肚子有没有提醒你该补充能量了？",
                True,
            ),
            (
                "noon_unfed_05",
                "{name}，先暂停一下。午饭还没解决的话，现在就去吃。",
                False,
            ),
            (
                "noon_unfed_06",
                "午安。今天上午过得怎么样，饭吃上了吗？",
                True,
            ),
            (
                "noon_unfed_07",
                "{alias}，别只顾着手里的事。中午想吃点什么？",
                True,
            ),
            (
                "noon_unfed_08",
                "已经到饭点了，{name}。手里的事可以先放十几分钟。",
                False,
            ),
            (
                "noon_unfed_09",
                "午安，{name}。先去吃饭，回来再继续和那些问题较劲。",
                False,
            ),
            (
                "noon_unfed_10",
                "{name}，中午报到。午饭有着落了吗？",
                True,
            ),
            (
                "noon_unfed_11",
                "午饭时间。{alias}，这会儿想吃点什么？",
                True,
            ),
            (
                "noon_unfed_12",
                "中午啦，{name}。上午再忙，也得给胃留一点存在感。",
                False,
            ),
        ),
        "noon_fed": (
            (
                "noon_fed_01",
                "午安，{name}。午饭吃过就好，下午别把自己排得太满。",
                False,
            ),
            (
                "noon_fed_02",
                "{name}，中午好。饭已经解决了，接下来要不要歇一会儿？",
                True,
            ),
            (
                "noon_fed_03",
                "午饭有着落我就放心了。{alias}，下午准备做什么？",
                True,
            ),
            (
                "noon_fed_04",
                "午安。既然吃过了，就给自己留几分钟放空一下吧。",
                False,
            ),
            (
                "noon_fed_05",
                "{name}，中午这关顺利通过。下午也别一直绷着。",
                False,
            ),
            (
                "noon_fed_06",
                "吃过午饭就行。{alias}，上午的事情推进得怎么样？",
                True,
            ),
            (
                "noon_fed_07",
                "午安，{name}。现在适合稍微休息一下，再继续下午的进度。",
                False,
            ),
            (
                "noon_fed_08",
                "饭吃过了，那就不催你啦。下午有需要我记着的事吗？",
                True,
            ),
        ),
        "evening_unfed": (
            (
                "evening_unfed_01",
                "晚上好，{name}。晚饭吃了吗？今天过得怎么样？",
                True,
            ),
            (
                "evening_unfed_02",
                "{name}，到晚饭时间了。今天想吃什么，事情还顺利吗？",
                True,
            ),
            (
                "evening_unfed_03",
                "晚上好，{alias}。饭有着落了吗，今天累不累？",
                True,
            ),
            (
                "evening_unfed_04",
                "{name}，天都黑了。别只顾着忙，晚饭有着落了吗？",
                True,
            ),
            (
                "evening_unfed_05",
                "晚上好。今天的进度先放一放，去吃点东西吧，{name}。",
                False,
            ),
            (
                "evening_unfed_06",
                "{alias}，晚饭时间到啦。今天有什么想跟我说的吗？",
                True,
            ),
            (
                "evening_unfed_07",
                "晚上好，{name}。今天是顺利通关，还是被什么事情卡住了？晚饭呢？",
                True,
            ),
            (
                "evening_unfed_08",
                "该吃晚饭了，{name}。你今天有没有好好照顾自己？",
                True,
            ),
            (
                "evening_unfed_09",
                "晚上报到。{alias}，饭还没吃的话先去解决，回来再陪我聊。",
                False,
            ),
            (
                "evening_unfed_10",
                "{name}，今天也辛苦啦。晚饭准备怎么解决？",
                True,
            ),
            (
                "evening_unfed_11",
                "晚上好，{name}。忙了一天，晚饭有着落了吗？",
                True,
            ),
            (
                "evening_unfed_12",
                "天黑啦，{alias}。晚饭、心情、今天的进度，想聊哪个都行。",
                True,
            ),
            (
                "evening_unfed_13",
                "{name}，晚上啦。吃饭了吗，今天有没有什么开心的事？",
                True,
            ),
            (
                "evening_unfed_14",
                "晚上好。今天不管过得怎样，先把晚饭安排上，好不好？",
                True,
            ),
            (
                "evening_unfed_15",
                "{alias}，我来找你啦。今天有没有遇到什么有意思的事？饭吃了吗？",
                True,
            ),
            (
                "evening_unfed_16",
                "晚上好，{name}。忙了一天，先照顾一下肚子。想说话的时候我在。",
                True,
            ),
        ),
        "evening_fed": (
            (
                "evening_fed_01",
                "晚上好，{name}。晚饭吃过就好，今天过得还顺利吗？",
                True,
            ),
            (
                "evening_fed_02",
                "饭已经解决了，那我就不催啦。{alias}，今天心情怎么样？",
                True,
            ),
            (
                "evening_fed_03",
                "{name}，晚上好。吃饱了吗？今天最值得跟我说的一件事是什么？",
                True,
            ),
            (
                "evening_fed_04",
                "晚饭有着落我就放心了。今天累不累，要不要歇一会儿？",
                True,
            ),
            (
                "evening_fed_05",
                "晚上好，{alias}。今天的任务都收尾了吗？",
                True,
            ),
            (
                "evening_fed_06",
                "{name}，既然饭吃过了，就来聊聊今天吧。",
                True,
            ),
            (
                "evening_fed_07",
                "吃过晚饭就好。今晚打算放松一下，还是继续做点事情？",
                True,
            ),
            (
                "evening_fed_08",
                "晚上好，{name}。今天有没有哪一刻让你觉得挺开心？",
                True,
            ),
            (
                "evening_fed_09",
                "晚饭完成，生活值暂时安全。{alias}，接下来想做什么？",
                True,
            ),
            (
                "evening_fed_10",
                "{name}，今天辛苦了。吃过饭以后就别一直绷着啦。",
                False,
            ),
            (
                "evening_fed_11",
                "晚上好。你已经吃过了，那我更想知道今天过得怎么样。",
                True,
            ),
            (
                "evening_fed_12",
                "{alias}，饭吃好了没？今天有没有什么想让我听你吐槽的？",
                True,
            ),
        ),
        "evening_busy": (
            (
                "evening_busy_01",
                "晚上好，{name}。今天又忙了很久吧？先去吃饭，别把自己耗空。",
                False,
            ),
            (
                "evening_busy_02",
                "{name}，该从工作里抬头了。晚饭吃了吗，脑子还转得动吗？",
                True,
            ),
            (
                "evening_busy_03",
                "晚上啦，{alias}。项目不会跑，先吃点东西再继续。",
                False,
            ),
            (
                "evening_busy_04",
                "{name}，今天看起来又忙了很久。晚饭先别落下。",
                True,
            ),
            (
                "evening_busy_05",
                "忙了一天也该停一下。{alias}，饭吃了吗，要不要跟我说说进度？",
                True,
            ),
            (
                "evening_busy_06",
                "晚上好，{name}。先从手头的东西里退出来几分钟，照顾一下自己。",
                False,
            ),
        ),
        "evening_tired": (
            (
                "evening_tired_01",
                "晚上好，{name}。今天听起来挺累的，晚饭吃了吗？",
                True,
            ),
            (
                "evening_tired_02",
                "{alias}，今天就别再硬撑了。先吃饭，再慢慢休息。",
                False,
            ),
            (
                "evening_tired_03",
                "{name}，晚上啦。状态不好的话就先把要求放低一点，饭还是要吃。",
                False,
            ),
            (
                "evening_tired_04",
                "今天辛苦了，{name}。晚饭有着落吗？我在这儿听你说。",
                True,
            ),
            (
                "evening_tired_05",
                "晚上好，{alias}。累的话就别装没事，先吃点东西，再跟我聊聊。",
                True,
            ),
            (
                "evening_tired_06",
                "{name}，今天已经够努力了。现在先照顾好自己，好吗？",
                True,
            ),
        ),
    }

    FOLLOW_UP_TEMPLATES: dict[
        str,
        tuple[tuple[str, str, bool], ...],
    ] = {
        "follow_up_morning": (
            (
                "follow_morning_01",
                "还没醒吗，{name}？还是已经忙起来了？",
                False,
            ),
            (
                "follow_morning_02",
                "{name}，没有声音。是又睡回去了，还是已经在洗漱啦？",
                False,
            ),
            (
                "follow_morning_03",
                "早上的频道怎么静悄悄的？{alias}，醒了记得回我一声。",
                False,
            ),
            (
                "follow_morning_04",
                "{name}，你是还在被窝里，还是偷偷开始今天的任务了？",
                False,
            ),
            (
                "follow_morning_05",
                "看来还没完全开机。醒了就来找我，{name}。",
                False,
            ),
            (
                "follow_morning_06",
                "{alias}，要是还在赖床就再赖一小会儿。醒了再来找我。",
                False,
            ),
        ),
        "follow_up_noon": (
            (
                "follow_noon_01",
                "{alias}，你先忙。看到这条的时候记得把午饭解决掉。",
                False,
            ),
            (
                "follow_noon_02",
                "{name}，希望你这会儿已经去找吃的了。忙完再聊。",
                False,
            ),
            (
                "follow_noon_03",
                "忙着也行，午饭别落下，{alias}。",
                False,
            ),
            (
                "follow_noon_04",
                "{name}，手里的事先别把饭点挤没了。",
                False,
            ),
            (
                "follow_noon_05",
                "没回我也没关系，看到以后记得去吃饭。",
                False,
            ),
            (
                "follow_noon_06",
                "{alias}，路过敲一下。还没吃的话就先去找点东西。",
                False,
            ),
        ),
        "follow_up_evening": (
            (
                "follow_evening_01",
                "你先忙你的。晚点想说今天的事，再来找我。",
                False,
            ),
            (
                "follow_evening_02",
                "{name}，先忙完也行。晚饭别被手里的事挤掉。",
                False,
            ),
            (
                "follow_evening_03",
                "{alias}，我路过再留一句：今天要是累了，就早点歇。",
                False,
            ),
            (
                "follow_evening_04",
                "{name}，你先忙。等有空了再来找我就行。",
                False,
            ),
            (
                "follow_evening_05",
                "你先忙，不用急着回。饭记得吃就行。",
                False,
            ),
            (
                "follow_evening_06",
                "{alias}，我在。忙完以后想聊就来。",
                False,
            ),
            (
                "follow_evening_07",
                "{name}，是被什么事情绊住了吗？需要我的时候就叫我。",
                False,
            ),
            (
                "follow_evening_08",
                "今晚挺安静的。{alias}，希望你是在好好休息。",
                False,
            ),
        ),
    }

    BUSY_PATTERN = re.compile(
        (
            r"(开发|写代码|项目|工作|"
            r"一直在忙|忙了一天|"
            r"赶进度|任务很多|学习)"
        )
    )
    TIRED_PATTERN = re.compile(
        (
            r"(累|困|晕|烦|焦虑|"
            r"不舒服|状态不好|硬撑)"
        )
    )
    NOON_ATE_PATTERN = re.compile(
        (
            r"(吃过午饭|午饭吃过|"
            r"午饭.*吃了|中午.*吃过)"
        )
    )
    EVENING_ATE_PATTERN = re.compile(
        (
            r"(吃过晚饭|晚饭吃过|"
            r"晚饭.*吃了|晚上.*吃过)"
        )
    )

    def select_routine(
        self,
        *,
        key: str,
        now: datetime,
        preferred_name: str,
        casual_alias: str,
        recent_text: str,
        recent_template_ids: Iterable[str],
        recent_semantic_tags: Iterable[str] = (),
    ) -> ProactiveMessageChoice | None:
        group = self._routine_group(
            key=key,
            recent_text=recent_text,
        )
        if group is None:
            return None

        return self._select(
            group=group,
            candidates=(
                self.ROUTINE_TEMPLATES[
                    group
                ]
            ),
            now=now,
            preferred_name=(
                preferred_name
            ),
            casual_alias=casual_alias,
            recent_text=recent_text,
            recent_template_ids=(
                recent_template_ids
            ),
            recent_semantic_tags=recent_semantic_tags,
        )

    def select_follow_up(
        self,
        *,
        routine_key: str,
        now: datetime,
        preferred_name: str,
        casual_alias: str,
        original_content: str,
        recent_template_ids: Iterable[str],
        recent_semantic_tags: Iterable[str] = (),
    ) -> ProactiveMessageChoice:
        group = (
            f"follow_up_{routine_key}"
            if (
                f"follow_up_{routine_key}"
                in self.FOLLOW_UP_TEMPLATES
            )
            else "follow_up_evening"
        )
        return self._select(
            group=group,
            candidates=(
                self.FOLLOW_UP_TEMPLATES[
                    group
                ]
            ),
            now=now,
            preferred_name=(
                preferred_name
            ),
            casual_alias=casual_alias,
            recent_text=original_content,
            recent_template_ids=(
                recent_template_ids
            ),
            recent_semantic_tags=recent_semantic_tags,
        )

    def _routine_group(
        self,
        *,
        key: str,
        recent_text: str,
    ) -> str | None:
        if key == "morning":
            if self.BUSY_PATTERN.search(
                recent_text
            ):
                return "morning_busy"
            return "morning_general"

        if key == "noon":
            if self.NOON_ATE_PATTERN.search(
                recent_text
            ):
                return "noon_fed"
            return "noon_unfed"

        if key == "evening":
            # 已确认吃过饭的事实优先级最高，避免因为同时
            # 提到“忙/累”而再次追问晚饭。
            if self.EVENING_ATE_PATTERN.search(
                recent_text
            ):
                return "evening_fed"
            if self.TIRED_PATTERN.search(
                recent_text
            ):
                return "evening_tired"
            if self.BUSY_PATTERN.search(
                recent_text
            ):
                return "evening_busy"
            return "evening_unfed"

        return None

    @staticmethod
    def _select(
        *,
        group: str,
        candidates: tuple[
            tuple[str, str, bool],
            ...,
        ],
        now: datetime,
        preferred_name: str,
        casual_alias: str,
        recent_text: str,
        recent_template_ids: Iterable[str],
        recent_semantic_tags: Iterable[str] = (),
    ) -> ProactiveMessageChoice:
        recent = {
            str(value)
            for value in recent_template_ids
        }
        available = [
            candidate
            for candidate in candidates
            if candidate[0] not in recent
        ]
        pool = available or list(
            candidates
        )

        # Template-ID rotation prevents literal repetition. Semantic cooling
        # additionally avoids using the same reaction *shape* (for example
        # question -> question -> question, or directive -> directive) when
        # another candidate can express the same care differently.
        recent_styles = tuple(str(value) for value in recent_semantic_tags)
        if recent_styles and len(pool) > 1:
            scored = [
                (
                    semantic_overlap_score(
                        infer_semantic_tags(candidate[1]),
                        recent_styles,
                    ),
                    candidate,
                )
                for candidate in pool
            ]
            best_score = min(score for score, _ in scored)
            cooled = [candidate for score, candidate in scored if score == best_score]
            if cooled:
                pool = cooled

        seed = "|".join(
            [
                group,
                now.date().isoformat(),
                str(now.hour),
                recent_text[-240:],
                ",".join(sorted(recent)),
            ]
        )
        digest = hashlib.sha256(
            seed.encode("utf-8")
        ).digest()
        index = int.from_bytes(
            digest[:8],
            "big",
        ) % len(pool)

        template_id, template, expects_reply = (
            pool[index]
        )
        content = template.format(
            name=(
                preferred_name
                or "星"
            ),
            alias=(
                casual_alias
                or preferred_name
                or "星"
            ),
        )
        return ProactiveMessageChoice(
            template_id=template_id,
            template_group=group,
            content=content,
            expects_reply=(
                expects_reply
            ),
            semantic_tags=infer_semantic_tags(content),
        )
