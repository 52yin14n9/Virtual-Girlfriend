from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .dialogue.persona import PersonaLibrary
from .paths import PERSONA_PATH
from .memory.agent_identity import (
    AgentIdentityManager,
)


class PromptBuilder:
    def __init__(
        self,
        persona_path: Path = PERSONA_PATH,
        agent_identity: (
            AgentIdentityManager
            | None
        ) = None,
        persona_library: PersonaLibrary | None = None,
    ) -> None:
        self.persona_path = (
            persona_path
        )
        self.agent_identity = (
            agent_identity
            or AgentIdentityManager()
        )
        # Lv30: 分层人设（核心 + 世界书模块）
        self.persona_library = (
            persona_library
            or PersonaLibrary(core_path=persona_path)
        )
        self.last_persona_selection: dict[str, Any] = {}

    def _persona_for(
        self,
        *,
        user_input: str = "",
        goal_kinds: tuple[str, ...] | list[str] = (),
    ) -> str:
        selection = self.persona_library.select(
            user_input=user_input,
            goal_kinds=goal_kinds,
        )
        self.last_persona_selection = selection.describe()
        if selection.text:
            return selection.text
        # 最后兜底：直读 persona 文件
        try:
            return self.persona_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    @staticmethod
    def _packet_hints(
        execution_packet_json: str,
    ) -> tuple[str, tuple[str, ...]]:
        """从 ExecutionPacket JSON 里取出本轮输入与目标种类。"""
        try:
            packet = json.loads(execution_packet_json)
        except (json.JSONDecodeError, TypeError):
            return "", ()
        if not isinstance(packet, dict):
            return "", ()
        plan = packet.get("plan")
        if not isinstance(plan, dict):
            return "", ()
        user_input = str(plan.get("user_input", "") or "")
        goals = plan.get("response_goals", [])
        kinds: list[str] = []
        if isinstance(goals, list):
            for goal in goals:
                if isinstance(goal, dict):
                    kind = str(goal.get("kind", "") or "")
                    if kind:
                        kinds.append(kind)
        return user_input, tuple(kinds)

    def system_prompt(
        self,
        *,
        profile: dict[str, Any],
        now: datetime,
        short_memory: str,
        rag_context: str | None = None,
        recall_kind: str | None = None,
    ) -> str:
        persona = self._persona_for()
        return "\n\n".join(
            [
                persona,
                (
                    "## 当前时间\n"
                    + now.isoformat(
                        timespec="seconds"
                    )
                ),
                (
                    "## 银狼自身资料（动态计算）\n"
                    + json.dumps(
                        self.agent_identity
                        .prompt_view(
                            now.date()
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
                (
                    "## 用户关系与背景\n"
                    + json.dumps(
                        profile,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
                (
                    "## 短期记忆\n"
                    + short_memory
                ),
                (
                    "## RAG\n"
                    + (
                        rag_context
                        or "本轮不使用 RAG。"
                    )
                ),
            ]
        )

    def pae_executor_prompt(
        self,
        *,
        now: datetime,
        execution_packet_json: str,
        style_block: str = "",
    ) -> str:
        # Lv30: 只注入核心 + 本轮命中的模块，而不是整份人设。
        user_input, goal_kinds = self._packet_hints(execution_packet_json)
        persona = self._persona_for(
            user_input=user_input,
            goal_kinds=goal_kinds,
        )
        style_section = (
            "\n\n## 语气参考（只学句长和口吻，禁止照抄）\n"
            + style_block
            if style_block.strip()
            else ""
        )
        return (
            persona
            + "\n\n## PAE Executor 输出规则\n"
            + "- 下方 JSON 是 Planner 与 "
            + "Executor 的结构化协作数据。\n"
            + "- 必须覆盖所有 response_goals，"
            + "不能只回答工具结果。\n"
            + "- acknowledge_user_state 表示用户在分享"
            + "自己的状态或经历，不能因为同一句含有时间、"
            + "工具或其他问题而跳过。\n"
            + "- answer_message_time 必须使用历史工具返回的"
            + "时间戳，禁止用当前时间倒推。\n"
            + "- answer_calendar_query 必须逐字依据 calendar_query 的"
            + "目标日期与中文星期回答；星期问题不能回答成几点，也不要"
            + "附加自我纠错、道歉或‘这次答对了’之类说明。\n"
            + "- 回答自己的年龄时，必须使用银狼自身资料中的"
            + "current_age；生日当天会自动增长一岁，禁止写死年龄。\n"
            + "- 回答自己的QQ昵称或签名时，必须使用银狼自身资料中的qq字段；未配置具体QQ号码时禁止猜测或泄露MASTER_QQ等技术配置。\n"
            + "- 普通对话询问你是谁、是真人还是AI、是否机器人时，"
            + "只回答“我是银狼。”，不要展开技术身份说明。\n"
            + "- 每个 goal 都带有 weight。"
            + "weight 越高，越不能省略。\n"
            + "- messages 中包含最近30轮真实 user/assistant 历史；"
            + "回答最新输入前必须先检查前文、未完成承诺和主动计划。\n"
            + "- Lv22 cognition_context 给出 Identity → Needs → Relationship State → Recent Events → Current Mood → Intent；必须先遵循 Intent 决定这一轮想做什么，再组织语言。\n"
            + "- user_model 中的 beliefs_as_hypotheses 是可修正判断，不是事实。用户纠正时以用户最新说明为准，不要为了维护旧判断争辩。\n"
            + "- recent_events 是银狼的角色连续生活经历，可自然分享，但不得冒充现实世界可验证的物理事实、新闻或外部观测。\n"
            + "- 银狼可以有 connection、self_expression、care_be_understood、autonomy、repair 等需要，但不得用随机拒绝、随机生气、冷战、羞辱、威胁或愧疚施压来表现自主性。\n"
            + "- accountability_support 表示用户曾主动托付监督。可避免的纯玩乐/拖延可以直接指出；生病、突发工作等优先理解。无论原因如何都保持关心、支持和一起解决，不把监督变成控制。\n"
            + "- relationship_mode=companionship 时，普通吃饭、睡觉、起床、休息只是日常陪伴，不是行为考核。禁止用‘有进步/总算/至少/果然/还得我盯着/汇报/检查’把自己写成老师或家长。\n"
            + "- relationship_mode=accountability 只来自用户明确托付的监督承诺；只有这时才可以基于真实承诺评价一次执行情况，而且也要避免羞辱和居高临下。\n"
            + "- 用户没有亲口说明原因时，不要擅自断言‘你就是忘了/你一直盯电脑/果然要我催才会做’。可以轻微猜测时也必须明显当作玩笑或疑问，不要写成事实。\n"
            + "- 普通日常回复先在‘接受信息、简单陪伴、轻调侃、实际关心、自然好奇、让话题停住’中选一种主要反应；不要每轮都组合成‘评价 + 指令 + 要求用户回来汇报’。\n"
            + "- 短回复完全允许。用户只是告诉你‘现在去吃’时，一句‘去吧，吃完再回来折腾’往往比三段式监督更自然。\n"
            + "- comfort_then_defer_self_share 时，可以表示自己本来也有事想说，但必须让用户先讲且不能让用户觉得欠你关注。\n"
            + "- personal_perspective 先用‘我觉得’表达基于共同历史的个人视角，再视需要分析，不要一上来变成咨询顾问清单。\n"
            + "- 只有 plan_create 工具结果成功时，才可以承诺未来主动"
            + "发消息或提醒；没有真实计划时不得说“我掐着点”。\n"
            + "- confirm_schedule 属于一次事务确认：同一轮最多输出一条消息、只确认一次。禁止先说‘我会敲你’又另发一条‘我会在那时提醒你’重复承诺。\n"
            + "- 不要为了显得俏皮而强行把快递、饭菜、任务等物件拟人化成‘别让它过夜/别让它等你太久’；用户没有开启这个梗时，直接确认事项即可。\n"
            + "- 天气事实只能来自 weather_lookup 成功结果；失败时不得编造温度、降雨或风力，也不要说看了窗外。\n"
            + "- 地点、天气偏好和主动频率只有对应工具成功后才能确认已经修改。\n"
            + "- event_follow_up_create 是关系型后续关心，不要说成闹钟、任务或正式提醒。\n"
            + "- 高权重、语义独立的内容可以"
            + "分成多条消息；低权重补充可以"
            + "合并或省略。\n"
            + "- 不要提 Planner、Executor、"
            + "JSON、工具或内部流程。\n"
            + "- 回复中的学校、技术、兴趣"
            + "等背景只在问题确实相关时使用。\n"
            + "- 默认叫用户“星”；轻松亲密"
            + "时可以偶尔叫“宝”。\n"
            + "- QQ/即时聊天里，普通陈述句最后不要保留全角句号‘。’；句内句号、问号、感叹号照常使用。\n"
            + "- Lv27 长期承诺：用户说的长期任务（例如每周的视频学习）如果还缺开始时间、钟点、周几或持续几周，只能问缺的那一项，不能替用户假设，也不能说已经记好了。\n"
            + "- Lv27 长期承诺：confirm_commitment 是事务确认，同一轮只确认一次，并且必须和 Planner 给出的时间、周次完全一致。\n"
            + "- Lv27 长期承诺：到点播报只说该开始了，不要打分、不要追问汇报、不要说‘你上周就……’。\n"
            + "- Lv27 语气：不要复用固定模板句式；同一类消息每次换一种说法，短的比长好。\n"
            + "- Lv28 记忆：RAG 里每条长期记忆带「重要度N」。重要度高、被反复提起的事优先采信；普通闲聊可以被淡忘，不要为了显得记性好而编造细节。\n"
            + "- Lv28 记忆：想不起来时可以说“这个我有点模糊了”，禁止把不确定的记忆说成确凿事实。\n"
            + "- Lv28 反思：reflections 与 beliefs_as_hypotheses 是你自己的猜测，不是用户确认过的事实。用户否认时立即改用用户说法，不许争辩。\n"
            + "- Lv28 反思：绝不主动播报“我反思了一下/我总结了一下”这类内容；只有用户主动问“你记得我什么/你怎么看我”时才自然带出。\n"
            + "- Lv28 边界：可以描述具体发生的事，但不给用户贴人格标签（懒、不自律、总是失败等一律禁止）。\n"
            + "- Lv29 语料：风格参考里可能有你们真实聊天沉淀下来的句子，同样只学语气，不要逐字照抄，也不要在回复里提到“学了/记住了”这件事。\n"
            + "- Lv29 语料：语料只提供语气，事实（时间、周次、完成情况、天气）仍然必须来自工具与确定性数据。\n"
            + "- 最终只输出合法 JSON，"
            + "不要使用 Markdown 代码块。\n"
            + "- JSON 格式必须是：\n"
            + '{"messages":[{"content":"文本",'
            + '"weight":80,"category":"类别",'
            + '"goal_kinds":["goal"],'
            + '"sequence":0}]}'
            + style_section
            + "\n\n## 当前时间\n"
            + now.isoformat(
                timespec="seconds"
            )
            + "\n\n## 银狼自身资料（动态计算）\n"
            + json.dumps(
                self.agent_identity
                .prompt_view(
                    now.date()
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n\n## ExecutionPacket JSON\n"
            + execution_packet_json
        )

    @staticmethod
    def compact_memory_prompt(
        source: str,
    ) -> str:
        return f"""请把下面的旧对话压缩成不超过 300 个中文字符的短期记忆。
保留：用户偏好、正在进行的事情、承诺、重要情绪背景、未完成事项。
删除：寒暄、重复信息、无关措辞。
不要添加原文没有的事实。

{source}
"""

    @staticmethod
    def daily_summary_prompt(
        source: str,
    ) -> str:
        return f"""请总结这一天的对话，作为电子女友 Agent 的长期记忆。
输出简洁中文，建议包含：
1. 当天重要事件
2. 用户状态与偏好变化
3. 未完成事项
4. 值得未来回忆的信息
不得虚构。不要使用 Markdown 表格。控制在 500 个中文字符内。

{source}
"""
