# 银狼 Lv27 数据、配置、工具与 API

## 1. 环境变量

| 变量 | 默认值 | 作用 |
|---|---:|---|
| `ANTHROPIC_API_KEY` | 无 | DeepSeek/Anthropic-compatible API Key |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | 兼容接口根地址 |
| `SILVERWOLF_MODEL` | `deepseek-v4-flash` | 主模型与 Planner 模型名称 |
| `SILVERWOLF_TIMEZONE` | `Asia/Shanghai` | Agent 业务时区 |
| `SILVERWOLF_MAX_TOKENS` | `1000` | 主回复 token 上限 |
| `SILVERWOLF_TEMPERATURE` | `0.8` | 主对话温度 |
| `SILVERWOLF_MAX_RETRIES` | `3` | 模型请求最大重试 |
| `SILVERWOLF_RETRY_BASE_SECONDS` | `1.5` | 指数退避基数 |
| `SILVERWOLF_SCHEDULER_POLL_SECONDS` | `5` | 主动调度轮询间隔 |
| `SILVERWOLF_MESSAGE_GAP_SECONDS` | `0.9` | 多条消息发送间隔 |
| `SILVERWOLF_PLANNER_LLM_ENABLED` | `true` | 开启模型日程裁决 |
| `SILVERWOLF_PLANNER_MIN_CONFIDENCE` | `0.72` | 日程裁决最低置信度 |
| `SILVERWOLF_PLANNER_MAX_TOKENS` | `700` | 日程裁决 token 上限 |
| `SILVERWOLF_PLANNER_TEMPERATURE` | `0.1` | 日程裁决低温度 |
| `SILVERWOLF_PROACTIVE_FOLLOW_UP_ENABLED` | `false` | 是否开启关系型二次追问；Lv24 默认关闭，普通关心不要求回执 |
| `SILVERWOLF_PROACTIVE_FOLLOW_UP_SECONDS` | `900` | 开启二次追问后，默认至少等待 15 分钟 |
| `SILVERWOLF_PROACTIVE_FOLLOW_UP_EXPIRY_SECONDS` | `3600` | 陈旧追问过期秒数 |
| `SILVERWOLF_PROACTIVE_TEMPLATE_HISTORY_LIMIT` | `6` | 主动模板近期去重深度 |
| `SILVERWOLF_COMMITMENT_ENABLED` | `true` | 开启长期任务承诺（澄清 + 周期提醒） |
| `SILVERWOLF_COMMITMENT_CLARIFY_MAX_QUESTIONS` | `2` | 每轮最多追问几个信息点（1-3） |
| `SILVERWOLF_COMMITMENT_CLARIFY_EXPIRY_HOURS` | `24` | 澄清会话过期小时数 |
| `SILVERWOLF_COMMITMENT_DEFAULT_CLOCK` | `10:00` | 用户没给钟点时的兜底时间 |
| `SILVERWOLF_COMMITMENT_MAX_WEEKS` | `52` | 单个承诺最大周数 |
| `SILVERWOLF_COMMITMENT_SOFT_WEEKEND` | `true` | 周末柔性模式：任一天做完即算完成 |
| `SILVERWOLF_CORPUS_ENABLED` | `true` | 开启语料库驱动生成 |
| `SILVERWOLF_CORPUS_SAMPLES` | `3` | 生成时参考的语料条数 |
| `SILVERWOLF_CORPUS_CHAT_SAMPLES` | `2` | 普通聊天注入的语气样本条数 |
| `SILVERWOLF_CORPUS_MAX_OVERLAP` | `0.35` | 与语料的最大 3-gram Jaccard 相似度 |
| `SILVERWOLF_CORPUS_COOLDOWN` | `8` | 语料样句冷却条数 |
| `SILVERWOLF_CORPUS_TEMPERATURE` | `0.85` | 语料重写温度（只影响措辞） |
| `SILVERWOLF_MEMORY_DECAY_ENABLED` | `true` | 记忆检索是否走重要度 + 遗忘曲线 |
| `SILVERWOLF_MEMORY_WEIGHT_RELEVANCE` | `0.55` | 三因子权重：相关性 |
| `SILVERWOLF_MEMORY_WEIGHT_IMPORTANCE` | `0.25` | 三因子权重：重要度 |
| `SILVERWOLF_MEMORY_WEIGHT_RECENCY` | `0.20` | 三因子权重：新鲜度 |
| `SILVERWOLF_MEMORY_STABILITY_BASE_DAYS` | `14` | 遗忘曲线基础稳定度（天） |
| `SILVERWOLF_RAG_IMPORTANCE_LLM_ENABLED` | `false` | 是否让模型给记忆打分（默认关闭） |
| `SILVERWOLF_REFLECTION_ENABLED` | `true` | 开启每周反思 |
| `SILVERWOLF_REFLECTION_WEEKDAY` | `6` | 周触发：0=周一 … 6=周日 |
| `SILVERWOLF_REFLECTION_HOUR` | `21` | 周触发：几点之后 |
| `SILVERWOLF_REFLECTION_IMPORTANCE_THRESHOLD` | `150` | 累积触发阈值（本周重要度合计） |
| `SILVERWOLF_REFLECTION_MAX_EVIDENCE` | `12` | 反思最多引用多少条记忆 |
| `SILVERWOLF_SILENCE_RETURN_HOURS` | `18` | 沉默多久后改用续接式回归 |
| `SILVERWOLF_CORPUS_LEARNING_ENABLED` | `true` | 语料自我生长总开关 |
| `SILVERWOLF_CORPUS_LEARN_FROM_USER` | `false` | 是否也学用户口头表达 |
| `SILVERWOLF_CORPUS_PHRASE_MODE` | `false` | 是否允许 ≤8 字语气片段原样复用 |
| `SILVERWOLF_CORPUS_CANDIDATE_MIN_CHARS` | `5` | 候选最短字数 |
| `SILVERWOLF_CORPUS_CANDIDATE_MAX_CHARS` | `30` | 候选最长字数 |
| `SILVERWOLF_CORPUS_LEARNED_SHARE` | `0.3` | 一次采样里学来条目占比上限 |
| `SILVERWOLF_CORPUS_RETIRE_DAYS` | `90` | 多久未用且用得少就淘汰 |
| `SILVERWOLF_CORPUS_SCENE_LIMIT` | `120` | 每个场景已转正条目上限 |
| `SILVERWOLF_CORPUS_PRIVACY_FILTER` | `true` | 隐私过滤（语料会进 prompt，建议保持 true） |
| `SILVERWOLF_PERSONA_LAYERS_ENABLED` | `true` | 人设分层开关；关闭后退回每轮整份人设 |
| `SILVERWOLF_PERSONA_CORE_MAX_CHARS` | `4000` | 核心人设建议上限 |
| `SILVERWOLF_PERSONA_BUDGET_CHARS` | `8000` | 单轮注入总量上限（核心 + 模块） |
| `SILVERWOLF_PROACTIVE_JITTER_ENABLED` | `true` | 关系型关心的时机抖动 |
| `SILVERWOLF_PROACTIVE_JITTER_MINUTES` | `10` | 抖动幅度（±分钟） |
| `SILVERWOLF_PROACTIVE_PINNED_DAYS` | `7` | 手动改过时间后保持准点的天数 |
| `SILVERWOLF_PROACTIVE_SPEECH_ENABLED` | `true` | 主动消息语料化总开关；关闭后等于 Lv30 行为 |
| `SILVERWOLF_PROACTIVE_SPEECH_TIMEOUT_SECONDS` | `8` | 单条生成硬超时，超时走确定性兜底 |
| `SILVERWOLF_PROACTIVE_SPEECH_MAX_CHARS` | `80` | 主动消息长度上限 |
| `SILVERWOLF_PROACTIVE_SPEECH_SCENES` | `morning,noon,evening,callback,follow_up,self_share` | 允许语料化的场景 |
| `SILVERWOLF_PROACTIVE_SPEECH_SAMPLES` | `3` | 生成时参考的语料条数 |
| `SILVERWOLF_SELF_SHARE_ENABLED` | `true` | 她自己的事（自我分享）总开关 |
| `SILVERWOLF_SELF_SHARE_PER_WEEK` | `2` | 每周最多讲几次（硬上限） |
| `SILVERWOLF_SELF_SHARE_MIN_AGE_DAYS` | `1` | 当天的事不讲 |
| `SILVERWOLF_SELF_SHARE_MAX_AGE_DAYS` | `10` | 太久远的不讲（避免翻旧账感） |
| `SILVERWOLF_SELF_SHARE_SETBACK_DAYS` | `10` | 「没做成」类事件的最小间隔 |
| `SILVERWOLF_CORPUS_IMPLICIT_SIGNAL_ENABLED` | `true` | 隐式正向信号（只影响排序） |
| `SILVERWOLF_CORPUS_IMPLICIT_WINDOW_MINUTES` | `10` | 多少分钟内继续说才算「继续聊」 |
| `SILVERWOLF_DOCTOR_STALE_DAYS` | `3` | 数据多少天没更新算「旧」（`/doctor` 用） |
| `SILVERWOLF_SELF_SHARE_KIND_COOLDOWN_DAYS` | `30` | 同类生活事件的最小间隔 |

## 2. 持久化文件与状态所有权
| 文件 | 所有者 | 写入时机 |
|---|---|---|
| `config/default_user_profile.json` | 配置 | 首次建立用户档案和 schema 迁移 |
| `config/default_agent_profile.json` | 配置 | 银狼生日与稳定身份 |
| `config/persona/silverwolf_lv33.md` | PromptBuilder | 核心人设，常驻注入 |
| `config/persona/modules/*.md` | PersonaLibrary | 9 个世界书模块，按关键词/goal 注入 |
| `config/corpus/*.jsonl` | 人工维护 | 语料库（5 文件 265 条，只作风格参照） |
| `data/corpus/corpus_usage.json` | CorpusStore | 语料冷却与最近发送内容 |
| `data/scheduler/commitments.json` | CommitmentStore | 长期承诺主数据与周次进度 |
| `data/scheduler/commitment_clarification.json` | ClarificationStore | 进行中的补全会话 |
| `data/rag/recall_stats.json` | JsonlRAGStore | 记忆被召回次数（Lv28） |
| `data/cognition/cognitive_state.json` | CognitiveStateManager | 认知状态 + reflections（Lv28，schema 22） |
| `data/profile/user_profile.json` | UserProfileManager | 用户称呼/属性更新 |
| `data/memory/short_term.json` | ShortTermMemory | 每轮对话、主动消息、压缩 |
| `data/rag/documents.jsonl` | JsonlRAGStore | 日总结/历史事件写入 |
| `data/summaries/daily_state.json` | DailySummaryManager | 活跃日期和跨日状态 |
| `data/scheduler/time_preferences.json` | TimeManager | 时间槽、时区、主动开关 |
| `data/scheduler/scheduled_plans.json` | PlanManager | 创建、触发、取消计划 |
| `data/scheduler/proactive_state.json` | ProactiveStateStore | routine、追问、模板历史 |

## 3. proactive_state 关键结构

```json
{
  "schema_version": 6,
  "routine_sent": {
    "evening": "2026-08-04"
  },
  "last_user_activity_at": "2026-08-04T19:02:48+08:00",
  "pending_follow_up": null,
  "last_follow_up": {
    "status": "cancelled_by_user_reply"
  },
  "proactive_template_history": [
    {
      "template_id": "evening_unfed_12",
      "template_group": "evening_unfed",
      "content": "天黑啦，宝……",
      "category": "routine_evening",
      "sent_at": "2026-08-04T19:02:46+08:00"
    }
  ]
}
```

## 4. scheduled plan 关键结构

```json
{
  "plan_id": "uuid",
  "title": "结束休息",
  "details": "休息一分钟",
  "due_at": "2026-08-04T16:49:50+08:00",
  "recurrence": "none",
  "importance": 96,
  "status": "pending",
  "source_text": "一分钟后叫我"
}
```

## 5. HTTP API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/` | 渲染测试聊天页面 |
| `GET` | `/api/messages` | 读取当前内存消息事件 |
| `GET` | `/api/events` | SSE 持续推送消息 |
| `POST` | `/api/chat` | 提交用户消息并异步处理 |
| `GET` | `/api/status` | 运行时、模型、调度和追问状态 |
| `GET` | `/api/plans` | 读取全部计划 |
| `DELETE` | `/api/plans/<plan_id>` | 取消指定计划 |
| `GET` | `/api/time-settings` | 读取早中晚时间设置 |
| `PATCH` | `/api/time-settings/<slot>` | 修改时间槽 |
| `POST` | `/api/proactive/tick` | 手动执行一次主动检查 |
| `GET` | `/api/debug/pae` | 查看最近交互 PAE JSON |
| `GET` | `/api/debug/proactive` | 查看主动状态、模板历史和调度 JSON |

注意：

- `/api/debug/proactive` 会返回完整主动状态，可能包含用户近期行为信息；
- 所有接口仅适合本地测试；
- 项目没有鉴权、访问控制、CSRF 或速率限制。

## 6. ToolRegistry 白名单

| 工具名 | 类 | 源码 |
|---|---|---|
| `conversation_history_lookup` | `ConversationHistoryLookupTool` | `silverwolf_agent/tools/conversation_history_tool.py:14` |
| `plan_create` | `PlanCreateTool` | `silverwolf_agent/tools/plan_tools.py:11` |
| `plan_list` | `PlanListTool` | `silverwolf_agent/tools/plan_tools.py:105` |
| `plan_cancel` | `PlanCancelTool` | `silverwolf_agent/tools/plan_tools.py:144` |
| `profile_set_preferred_name` | `PreferredNameTool` | `silverwolf_agent/tools/preferred_name_tool.py:9` |
| `profile_update` | `ProfileUpdateTool` | `silverwolf_agent/tools/profile_tool.py:9` |
| `time_preferences_get` | `TimePreferencesGetTool` | `silverwolf_agent/tools/time_preferences_tools.py:11` |
| `time_preferences_set` | `TimePreferencesSetTool` | `silverwolf_agent/tools/time_preferences_tools.py:43` |
| `time_now` | `CurrentTimeTool` | `silverwolf_agent/tools/time_tool.py:11` |

工具执行流程：

```text
ConversationPlan.tool_requests
    → ConversationExecutor._execute_tools()
    → ToolRegistry.execute(name, arguments)
    → BaseTool.run()
    → ToolExecutionResult
```

## 7. JSON 边界

| 边界 | 输入 | 输出 |
|---|---|---|
| Conversation Planner | 用户输入 + now | `ConversationPlan JSON` |
| Conversation Executor | `ConversationPlan JSON` | `ReplyBundle + ExecutionPacket JSON` |
| Schedule Judge | 日程上下文 | `ModelScheduleJudgement JSON` |
| Proactive Planner | routines/plans/follow-up | `ProactivePlan JSON` |
| Proactive Executor | `ProactivePlan JSON` | `ReplyBundle + execution JSON` |

每个边界均通过 `json.loads()`、dataclass 构造或显式校验阻止无效结构继续传播。
