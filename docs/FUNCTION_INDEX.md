# 银狼 Lv21 函数与类索引

自动扫描 `silverwolf_agent/`：70 个 Python 模块，97 个类，436 个类方法，21 个模块函数。

行号对应历史索引；Lv19 新增时间日历组件如下。

## `silverwolf_agent/__init__.py`（27 行）

- 无顶层类或函数。

## `silverwolf_agent/agent.py`（921 行）

### `SilverWolfAgent` — 第 70 行

- `__init__()` — 第 71 行
- `_build_default_llm()` — 第 399 行
- `_build_planner_llm()` — 第 430 行
- `_build_reply_gate_llm()` — 第 467 行
- `offline()` — 第 511 行
- `now()` — 第 517 行
- `_complete_text()` — 第 522 行
- `_compact_memory_if_needed()` — 第 542 行
- `_rollover_if_needed()` — 第 568 行
- `chat_bundle()` — 第 590 行
- `chat()` — 第 681 行
- `async handle_user_message()` — 第 695 行
- `async start()` — 第 734 行
- `async stop()` — 第 742 行
- `async run_proactive_once()` — 第 745 行
- `identity_snapshot()` — 第 758 行
- `reply_decision_snapshot()` — 第 774 行
- `plans_snapshot()` — 第 783 行
- `time_snapshot()` — 第 793 行
- `pae_debug()` — 第 801 行
- `generate_daily_summary()` — 第 866 行

## `silverwolf_agent/config.py`（271 行）

### `AppConfig` — 第 74 行

- `from_env()` — 第 104 行
- `zoneinfo()` — 第 265 行

### 模块函数

- `_load_dotenv_fallback()` — 第 14 行
- `_env_bool()` — 第 42 行
- `load_project_env()` — 第 58 行

## `silverwolf_agent/delivery.py`（384 行）

### `OutboundMessage` — 第 17 行

- `validate()` — 第 43 行
- `to_dict()` — 第 59 行
- `from_dict()` — 第 64 行

### `ReplyBundle` — 第 126 行

- `selected_messages()` — 第 136 行
- `joined_text()` — 第 191 行
- `to_dict()` — 第 200 行
- `to_json()` — 第 215 行
- `from_dict()` — 第 223 行
- `from_json()` — 第 258 行

### `MessageSink` — 第 271 行

- `async send()` — 第 273 行

### `ConsoleMessageSink` — 第 280 行

- `__init__()` — 第 281 行
- `async send()` — 第 300 行

### `CallbackMessageSink` — 第 318 行

- `__init__()` — 第 319 行
- `async send()` — 第 328 行

### `CollectingMessageSink` — 第 339 行

- `__init__()` — 第 340 行
- `async send()` — 第 345 行

### `MessageDispatcher` — 第 354 行

- `__init__()` — 第 355 行
- `async dispatch()` — 第 364 行

## `silverwolf_agent/llm/__init__.py`（11 行）

- 无顶层类或函数。

## `silverwolf_agent/llm/anthropic_compatible.py`（173 行）

### `AnthropicCompatibleClient` — 第 14 行

- `__init__()` — 第 17 行
- `_normalize_endpoint()` — 第 46 行
- `_retry_delay()` — 第 54 行
- `_perform_request()` — 第 66 行
- `complete()` — 第 122 行

## `silverwolf_agent/llm/base.py`（18 行）

### `BaseLLMClient` — 第 9 行

- `complete()` — 第 11 行

## `silverwolf_agent/llm/echo.py`（22 行）

### `EchoLLMClient` — 第 9 行

- `complete()` — 第 12 行

## `silverwolf_agent/llm/errors.py`（16 行）

### `LLMServiceError` — 第 4 行

- `__init__()` — 第 7 行

## `silverwolf_agent/memory/__init__.py`（14 行）

- 无顶层类或函数。

## `silverwolf_agent/memory/agent_identity.py`（273 行）

### `AgentIdentityManager` — 第 16 行

- `__init__()` — 第 24 行
- `_load()` — 第 31 行
- `name()` — 第 60 行
- `qq_profile()` — 第 70 行
- `birthday()` — 第 107 行
- `birthday_display()` — 第 116 行
- `age_on()` — 第 136 行
- `birthday_in_year()` — 第 167 行
- `next_birthday()` — 第 178 行
- `age_after_next_birthday()` — 第 206 行
- `prompt_view()` — 第 222 行

## `silverwolf_agent/memory/daily_summary.py`（82 行）

### `DailySummaryManager` — 第 14 行

- `__init__()` — 第 15 行
- `_read_state()` — 第 30 行
- `_write_state()` — 第 36 行
- `should_rollover()` — 第 42 行
- `mark_active_date()` — 第 49 行
- `generate()` — 第 55 行

## `silverwolf_agent/memory/profile.py`（475 行）

### `UserProfileManager` — 第 18 行

- `__init__()` — 第 23 行
- `_read_raw()` — 第 40 行
- `_migrate_profile()` — 第 47 行
- `load()` — 第 137 行
- `save()` — 第 140 行
- `age_on()` — 第 164 行
- `set_path()` — 第 188 行
- `preferred_name()` — 第 232 行
- `casual_alias()` — 第 245 行
- `set_preferred_name()` — 第 260 行
- `infer_explicit_updates()` — 第 302 行
- `prompt_view()` — 第 420 行

## `silverwolf_agent/memory/rag.py`（83 行）

### `RAGDocument` — 第 16 行

- 无显式方法。

### `JsonlRAGStore` — 第 23 行

- `__init__()` — 第 26 行
- `add()` — 第 31 行
- `all()` — 第 42 行
- `_tokens()` — 第 55 行
- `search()` — 第 66 行

## `silverwolf_agent/memory/short_term.py`（547 行）

### `ShortTermMemory` — 第 18 行

- `__init__()` — 第 19 行
- `_read()` — 第 40 行
- `_write()` — 第 58 行
- `_timestamp()` — 第 77 行
- `add_turn()` — 第 90 行
- `add_user_message()` — 第 127 行
- `add_proactive_message()` — 第 143 行
- `latest_user_turn()` — 第 157 行
- `find_user_turn()` — 第 191 行
- `needs_compaction()` — 第 207 行
- `compact()` — 第 218 行
- `context_text()` — 第 331 行
- `recent_chat_messages()` — 第 416 行
- `recent_user_text()` — 第 519 行
- `snapshot()` — 第 544 行

## `silverwolf_agent/models.py`（24 行）

### `ChatMessage` — 第 8 行

- 无显式方法。

### `ToolCall` — 第 14 行

- 无显式方法。

### `LLMResponse` — 第 21 行

- 无显式方法。

## `silverwolf_agent/pae/__init__.py`（29 行）

- 无顶层类或函数。

## `silverwolf_agent/pae/contracts.py`（489 行）

### `ResponseGoal` — 第 14 行

- `from_dict()` — 第 23 行

### `ToolRequest` — 第 66 行

- `from_dict()` — 第 72 行

### `MemoryRequest` — 第 101 行

- `from_dict()` — 第 107 行

### `DeliveryPolicy` — 第 134 行

- `from_dict()` — 第 141 行

### `ConversationPlan` — 第 174 行

- `create()` — 第 199 行
- `validate()` — 第 242 行
- `to_dict()` — 第 276 行
- `to_json()` — 第 280 行
- `from_dict()` — 第 288 行
- `from_json()` — 第 370 行

### `ToolExecutionResult` — 第 384 行

- `from_dict()` — 第 392 行

### `ExecutionPacket` — 第 418 行

- `to_dict()` — 第 431 行
- `to_json()` — 第 434 行
- `from_json()` — 第 442 行

## `silverwolf_agent/pae/executor.py`（1469 行）

### `ConversationExecutor` — 第 42 行

- `__init__()` — 第 51 行
- `offline()` — 第 81 行
- `execute_json()` — 第 87 行
- `_execute_tools()` — 第 165 行
- `_retrieve_rag()` — 第 198 行
- `_render_with_llm()` — 第 230 行
- `_parse_llm_bundle()` — 第 292 行
- `_bundle_from_text()` — 第 440 行
- `_render_local()` — 第 501 行
- `_render_goal()` — 第 573 行
- `_tool_result_matching()` — 第 1278 行
- `_tool_result()` — 第 1289 行
- `_time_value()` — 第 1301 行
- `_friendly_due()` — 第 1332 行
- `_render_user_state_ack()` — 第 1380 行
- `_render_context_ack()` — 第 1445 行

## `silverwolf_agent/pae/planner.py`（1926 行）

### `ConversationPlanner` — 第 40 行

- `__init__()` — 第 262 行
- `plan()` — 第 315 行
- `plan_json()` — 第 1610 行
- `_extract_preferred_name()` — 第 1620 行
- `_extract_context_facts()` — 第 1639 行
- `_extract_user_state_facts()` — 第 1673 行
- `_history_time_request()` — 第 1764 行
- `_recent_identity_count()` — 第 1820 行
- `_recent_time_count()` — 第 1843 行
- `_choose_intent()` — 第 1867 行
- `_choose_render_mode()` — 第 1885 行

## `silverwolf_agent/pae/schedule_judge.py`（597 行）

### `ModelScheduleJudgement` — 第 46 行

- `to_dict()` — 第 66 行

### `ModelScheduleJudge` — 第 70 行

- `__init__()` — 第 92 行
- `available()` — 第 110 行
- `should_consult()` — 第 119 行
- `judge()` — 第 166 行
- `_compact_history()` — 第 261 行
- `_system_prompt()` — 第 289 行
- `_parse_json()` — 第 342 行
- `_validate()` — 第 382 行

## `silverwolf_agent/paths.py`（69 行）

### 模块函数

- `ensure_directories()` — 第 57 行

## `silverwolf_agent/proactive/__init__.py`（37 行）

- 无顶层类或函数。

## `silverwolf_agent/proactive/contracts.py`（263 行）

### `ScheduleDecision` — 第 15 行

- `to_dict()` — 第 24 行

### `ScheduledPlan` — 第 29 行

- `create()` — 第 45 行
- `to_dict()` — 第 76 行
- `from_dict()` — 第 80 行

### `RoutineEvent` — 第 145 行

- `to_dict()` — 第 154 行

### `ProactivePlan` — 第 159 行

- `create()` — 第 173 行
- `to_dict()` — 第 203 行
- `to_json()` — 第 206 行
- `from_json()` — 第 214 行

## `silverwolf_agent/proactive/executor.py`（69 行）

### `ProactiveExecutor` — 第 12 行

- `execute_json()` — 第 20 行

## `silverwolf_agent/proactive/message_library.py`（754 行）

### `ProactiveMessageChoice` — 第 11 行

- 无显式方法。

### `ProactiveMessageLibrary` — 第 18 行

- `select_routine()` — 第 579 行
- `select_follow_up()` — 第 614 行
- `_routine_group()` — 第 650 行
- `_select()` — 第 690 行

## `silverwolf_agent/proactive/plan_manager.py`（360 行）

### `PlanManager` — 第 19 行

- `__init__()` — 第 20 行
- `_read()` — 第 36 行
- `_write()` — 第 53 行
- `create()` — 第 71 行
- `find_duplicate()` — 第 120 行
- `list_plans()` — 第 155 行
- `due()` — 第 187 行
- `mark_triggered()` — 第 224 行
- `cancel()` — 第 286 行
- `cancel_by_query()` — 第 313 行

## `silverwolf_agent/proactive/planner.py`（687 行）

### `ProactivePlanner` — 第 31 行

- `__init__()` — 第 43 行
- `plan_json()` — 第 94 行
- `_allow_routine()` — 第 517 行
- `_recent_template_ids()` — 第 570 行
- `_plan_content()` — 第 631 行

## `silverwolf_agent/proactive/schedule_intent.py`（641 行）

### `ScheduleIntentAnalyzer` — 第 75 行

- `__init__()` — 第 167 行
- `analyze()` — 第 173 行
- `is_future_message_request()` — 第 300 行
- `analyze_time_preference()` — 第 313 行
- `wants_plan_list()` — 第 335 行
- `cancellation_query()` — 第 345 行
- `_resolve_due_at()` — 第 361 行
- `_extract_relative_delta()` — 第 432 行
- `_extract_clock()` — 第 464 行
- `_normalize_hour()` — 第 533 行
- `_detect_slot()` — 第 567 行
- `_extract_title()` — 第 587 行

### 模块函数

- `chinese_number()` — 第 28 行

## `silverwolf_agent/proactive/scheduler.py`（484 行）

### `AsyncProactiveScheduler` — 第 27 行

- `__init__()` — 第 28 行
- `running()` — 第 100 行
- `note_user_activity()` — 第 106 行
- `async start()` — 第 120 行
- `async stop()` — 第 137 行
- `async run_once()` — 第 150 行
- `async _run_once_unlocked()` — 第 164 行
- `async _run_forever()` — 第 462 行

## `silverwolf_agent/proactive/state.py`（755 行）

### `ProactiveStateStore` — 第 15 行

- `__init__()` — 第 16 行
- `_default_state()` — 第 36 行
- `_migrate()` — 第 57 行
- `_read()` — 第 114 行
- `_write()` — 第 134 行
- `_as_datetime()` — 第 153 行
- `routine_sent()` — 第 163 行
- `mark_routine_sent()` — 第 177 行
- `set_last_run()` — 第 190 行
- `arm_follow_up()` — 第 199 行
- `note_user_activity()` — 第 299 行
- `due_follow_up()` — 第 380 行
- `is_follow_up_pending()` — 第 462 行
- `mark_follow_up_sent()` — 第 491 行
- `clear_follow_up()` — 第 531 行
- `weather_sent()` — 第 564 行
- `mark_weather_sent()` — 第 573 行
- `memory_callback_sent()` — 第 583 行
- `mark_memory_callback_sent()` — 第 589 行
- `weekend_suggestion_sent()` — 第 598 行
- `mark_weekend_suggestion_sent()` — 第 604 行
- `record_relationship_sent()` — 第 613 行
- `recent_template_ids()` — 第 644 行
- `record_template_use()` — 第 699 行
- `snapshot()` — 第 752 行

## `silverwolf_agent/proactive/time_manager.py`（369 行）

### `TimeManager` — 第 29 行

- `__init__()` — 第 61 行
- `_read()` — 第 79 行
- `_write()` — 第 95 行
- `_migrate()` — 第 113 行
- `snapshot()` — 第 161 行
- `timezone()` — 第 164 行
- `proactive_enabled()` — 第 178 行
- `set_proactive_enabled()` — 第 186 行
- `slot()` — 第 196 行
- `slot_time()` — 第 211 行
- `set_slot()` — 第 219 行
- `due_routines()` — 第 266 行
- `default_due_time()` — 第 338 行
- `_combine()` — 第 352 行

## `silverwolf_agent/prompts.py`（184 行）

### `PromptBuilder` — 第 14 行

- `__init__()` — 第 15 行
- `system_prompt()` — 第 31 行
- `pae_executor_prompt()` — 第 88 行
- `compact_memory_prompt()` — 第 160 行
- `daily_summary_prompt()` — 第 172 行

## `silverwolf_agent/qq/__init__.py`（31 行）

- 无顶层类或函数。

## `silverwolf_agent/qq/audit.py`（61 行）

### `QQAuditLogger` — 第 10 行

- `__init__()` — 第 18 行
- `write()` — 第 27 行

## `silverwolf_agent/qq/config.py`（245 行）

### `QQBotConfig` — 第 35 行

- `from_env()` — 第 66 行
- `validate()` — 第 203 行
- `emergency_enabled()` — 第 241 行

### 模块函数

- `_env_int()` — 第 14 行

## `silverwolf_agent/qq/events.py`（275 行）

### `QQMessageEvent` — 第 130 行

- `from_dict()` — 第 143 行
- `occurred_at()` — 第 218 行

### `QQFriendRequestEvent` — 第 233 行

- `from_dict()` — 第 242 行

### 模块函数

- `_as_int()` — 第 8 行
- `extract_message_text()` — 第 21 行

## `silverwolf_agent/qq/gateway.py`（1124 行）

### `QQBotAccountInfo` — 第 29 行

- `to_dict()` — 第 39 行
- `render()` — 第 44 行

### `QQGateway` — 第 85 行

- `__init__()` — 第 106 行
- `async start()` — 第 205 行
- `async run_forever()` — 第 274 行
- `async stop()` — 第 280 行
- `async enqueue_event()` — 第 341 行
- `async process_event()` — 第 358 行
- `async refresh_bot_info()` — 第 436 行
- `async notify_master()` — 第 561 行
- `async _worker_loop()` — 第 572 行
- `async _handle_friend_request()` — 第 603 行
- `async _handle_message()` — 第 694 行
- `async _handle_non_master_message()` — 第 831 行
- `async _handle_master_command()` — 第 909 行
- `async _send_command_reply()` — 第 991 行
- `async _lookup_nickname()` — 第 1014 行
- `_audit_preview()` — 第 1040 行
- `_is_duplicate()` — 第 1060 行
- `_priority()` — 第 1086 行

## `silverwolf_agent/qq/onebot.py`（545 行）

### `OneBotActionError` — 第 24 行

- 无显式方法。

### `OneBotNotConnectedError` — 第 30 行

- 无显式方法。

### `OneBot11Client` — 第 42 行

- `__init__()` — 第 51 行
- `connected()` — 第 126 行
- `set_event_handler()` — 第 129 行
- `async start()` — 第 135 行
- `async stop()` — 第 157 行
- `async wait_until_ready()` — 第 183 行
- `async call_action()` — 第 195 行
- `async send_private_msg()` — 第 277 行
- `async send_group_msg()` — 第 296 行
- `async set_friend_add_request()` — 第 315 行
- `async get_login_info()` — 第 337 行
- `async get_status()` — 第 352 行
- `async get_version_info()` — 第 367 行
- `async get_stranger_info()` — 第 382 行
- `async _run_forever()` — 第 405 行
- `async _receive_loop()` — 第 477 行
- `_fail_pending()` — 第 533 行

## `silverwolf_agent/qq/sink.py`（58 行）

### `QQMessageSink` — 第 10 行

- `__init__()` — 第 17 行
- `async send()` — 第 43 行

## `silverwolf_agent/reply_gate/__init__.py`（7 行）

- 无顶层类或函数。

## `silverwolf_agent/reply_gate/agent.py`（337 行）

### `ReplyDecisionAgent` — 第 12 行

- `__init__()` — 第 74 行
- `decide()` — 第 92 行
- `_model_decision()` — 第 189 行
- `_strong_reply_reason()` — 第 258 行
- `_last_assistant()` — 第 293 行
- `_parse_json()` — 第 302 行
- `_reply()` — 第 320 行
- `_silent()` — 第 330 行

## `silverwolf_agent/reply_gate/contracts.py`（27 行）

### `ReplyDecision` — 第 9 行

- `to_dict()` — 第 19 行
- `to_json()` — 第 22 行

## `silverwolf_agent/skills/__init__.py`（31 行）

- 无顶层类或函数。

## `silverwolf_agent/skills/address_recall_skill.py`（57 行）

### `AddressRecallSkill` — 第 15 行

- `__init__()` — 第 29 行
- `can_handle()` — 第 35 行
- `execute()` — 第 45 行

## `silverwolf_agent/skills/base.py`（33 行）

### `SkillContext` — 第 10 行

- 无显式方法。

### `SkillResult` — 第 17 行

- 无显式方法。

### `BaseSkill` — 第 23 行

- `can_handle()` — 第 28 行
- `execute()` — 第 32 行

## `silverwolf_agent/skills/identity_recall_skill.py`（130 行）

### `IdentityRecallSkill` — 第 18 行

- `__init__()` — 第 43 行
- `is_identity_check()` — 第 56 行
- `_recent_check_count()` — 第 66 行
- `can_handle()` — 第 88 行
- `execute()` — 第 96 行

## `silverwolf_agent/skills/memory_recall_skill.py`（98 行）

### `MemoryRecallSkill` — 第 18 行

- `__init__()` — 第 31 行
- `can_handle()` — 第 39 行
- `execute()` — 第 49 行

## `silverwolf_agent/skills/preferred_name_skill.py`（94 行）

### `PreferredNameSkill` — 第 13 行

- `__init__()` — 第 44 行
- `_extract_name()` — 第 50 行
- `can_handle()` — 第 64 行
- `execute()` — 第 75 行

## `silverwolf_agent/skills/registry.py`（20 行）

### `SkillRegistry` — 第 6 行

- `__init__()` — 第 7 行
- `register()` — 第 10 行
- `dispatch()` — 第 14 行

## `silverwolf_agent/skills/time_skill.py`（147 行）

### `TimeSkill` — 第 18 行

- `__init__()` — 第 31 行
- `is_time_question()` — 第 44 行
- `_recent_count()` — 第 52 行
- `can_handle()` — 第 72 行
- `execute()` — 第 80 行

## `silverwolf_agent/tools/__init__.py`（46 行）

- 无顶层类或函数。

## `silverwolf_agent/tools/base.py`（33 行）

### `ToolResult` — 第 9 行

- 无显式方法。

### `BaseTool` — 第 15 行

- `input_schema()` — 第 21 行
- `run()` — 第 25 行
- `as_anthropic_schema()` — 第 28 行

## `silverwolf_agent/tools/conversation_history_tool.py`（127 行）

### `ConversationHistoryLookupTool` — 第 14 行

- `__init__()` — 第 26 行
- `input_schema()` — 第 33 行
- `run()` — 第 54 行

## `silverwolf_agent/tools/plan_tools.py`（216 行）

### `PlanCreateTool` — 第 11 行

- `__init__()` — 第 18 行
- `input_schema()` — 第 25 行
- `run()` — 第 66 行

### `PlanListTool` — 第 105 行

- `__init__()` — 第 111 行
- `input_schema()` — 第 118 行
- `run()` — 第 125 行

### `PlanCancelTool` — 第 144 行

- `__init__()` — 第 150 行
- `input_schema()` — 第 157 行
- `run()` — 第 171 行

## `silverwolf_agent/tools/preferred_name_tool.py`（63 行）

### `PreferredNameTool` — 第 9 行

- `__init__()` — 第 16 行
- `input_schema()` — 第 23 行
- `run()` — 第 36 行

## `silverwolf_agent/tools/profile_tool.py`（50 行）

### `ProfileUpdateTool` — 第 9 行

- `__init__()` — 第 16 行
- `input_schema()` — 第 20 行
- `run()` — 第 40 行

## `silverwolf_agent/tools/registry.py`（39 行）

### `ToolRegistry` — 第 12 行

- `__init__()` — 第 13 行
- `register()` — 第 16 行
- `get()` — 第 26 行
- `execute()` — 第 29 行
- `schemas()` — 第 38 行

## `silverwolf_agent/tools/time_preferences_tools.py`（118 行）

### `TimePreferencesGetTool` — 第 11 行

- `__init__()` — 第 17 行
- `input_schema()` — 第 24 行
- `run()` — 第 31 行

### `TimePreferencesSetTool` — 第 43 行

- `__init__()` — 第 49 行
- `input_schema()` — 第 56 行
- `run()` — 第 86 行

## `silverwolf_agent/tools/time_tool.py`（75 行）

### `CurrentTimeTool` — 第 11 行

- `__init__()` — 第 17 行
- `input_schema()` — 第 28 行
- `run()` — 第 35 行

## `silverwolf_agent/tools/world_tools.py`（203 行）

### `WeatherLookupTool` — 第 11 行

- `__init__()` — 第 15 行
- `input_schema()` — 第 20 行
- `run()` — 第 29 行

### `WorldContextGetTool` — 第 41 行

- `__init__()` — 第 45 行
- `input_schema()` — 第 50 行
- `run()` — 第 53 行

### `WorldContextUpdateTool` — 第 57 行

- `__init__()` — 第 61 行
- `input_schema()` — 第 65 行
- `run()` — 第 87 行

### `InteractionPreferencesSetTool` — 第 118 行

- `__init__()` — 第 122 行
- `input_schema()` — 第 131 行
- `run()` — 第 139 行

### `EventFollowUpCreateTool` — 第 163 行

- `__init__()` — 第 167 行
- `input_schema()` — 第 171 行
- `run()` — 第 185 行

## `silverwolf_agent/webapp/__init__.py`（27 行）

### 模块函数

- `create_app()` — 第 11 行

## `silverwolf_agent/webapp/app.py`（651 行）

### 模块函数

- `create_app()` — 第 25 行
- `_bootstrap_recent_history()` — 第 566 行
- `_parse_int()` — 第 642 行

## `silverwolf_agent/webapp/message_store.py`（165 行）

### `WebMessageEvent` — 第 14 行

- `to_dict()` — 第 26 行

### `MessageStore` — 第 30 行

- `__init__()` — 第 31 行
- `_timestamp()` — 第 48 行
- `publish()` — 第 64 行
- `snapshot()` — 第 127 行
- `wait_for_events()` — 第 141 行

## `silverwolf_agent/webapp/runtime.py`（256 行）

### `BrowserMessageSink` — 第 19 行

- `__init__()` — 第 22 行
- `async send()` — 第 31 行

### `AsyncAgentRuntime` — 第 54 行

- `__init__()` — 第 63 行
- `running()` — 第 98 行
- `start()` — 第 106 行
- `_thread_main()` — 第 129 行
- `submit_user_message()` — 第 158 行
- `trigger_proactive_once()` — 第 183 行
- `_report_error()` — 第 201 行
- `_require_running()` — 第 222 行
- `stop()` — 第 231 行

## `silverwolf_agent/world/__init__.py`（28 行）

- 无顶层类或函数。

## `silverwolf_agent/world/context.py`（243 行）

### `WorldContextManager` — 第 45 行

- `__init__()` — 第 46 行
- `ensure_defaults()` — 第 56 行
- `snapshot()` — 第 80 行
- `active_location()` — 第 92 行
- `_temporary_active()` — 第 112 行
- `ensure_resolved()` — 第 124 行
- `_resolve_query()` — 第 139 行
- `set_home_location()` — 第 151 行
- `set_temporary_location()` — 第 156 行
- `clear_temporary_location()` — 第 172 行
- `_replace_location()` — 第 180 行
- `weather_preferences()` — 第 186 行
- `set_weather_preferences()` — 第 192 行
- `interaction_preferences()` — 第 203 行
- `set_interaction_preferences()` — 第 232 行

## `silverwolf_agent/world/intents.py`（348 行）

### `Lv17Intent` — 第 10 行

- 无显式方法。

### `Lv17IntentAnalyzer` — 第 16 行

- `analyze()` — 第 39 行
- `_location_intents()` — 第 73 行
- `_clean_location()` — 第 133 行
- `_temporary_window()` — 第 140 行
- `_weather_preference_intent()` — 第 177 行
- `_interaction_intent()` — 第 198 行
- `_event_cancel_intent()` — 第 232 行
- `_event_follow_up_intent()` — 第 240 行
- `_event_due()` — 第 280 行
- `_extract_clock()` — 第 306 行
- `_deduplicate()` — 第 330 行

### 模块函数

- `_chinese_number()` — 第 341 行

## `silverwolf_agent/world/proactive.py`（84 行）

### `ContextualCareComposer` — 第 10 行

- `compose()` — 第 21 行
- `weather_alert()` — 第 56 行
- `_memory_callback()` — 第 67 行
- `_weekend_suggestion()` — 第 75 行

## `silverwolf_agent/world/weather.py`（626 行）

### `WeatherSnapshot` — 第 50 行

- `to_dict()` — 第 70 行
- `from_dict()` — 第 74 行
- `natural_brief()` — 第 106 行

### `WeatherProvider` — 第 137 行

- `geocode()` — 第 138 行
- `forecast()` — 第 191 行

### `OpenMeteoWeatherProvider` — 第 202 行

- `__init__()` — 第 208 行
- `_get_json()` — 第 211 行
- `geocode()` — 第 233 行
- `forecast()` — 第 273 行

### `WeatherService` — 第 352 行

- `__init__()` — 第 353 行
- `lookup()` — 第 368 行
- `_cache_key()` — 第 423 行
- `_read_cache()` — 第 432 行
- `_load_cached()` — 第 440 行
- `_temperature_comparison()` — 第 458 行
- `_save_cached()` — 第 497 行

### 模块函数

- `_geocoding_queries()` — 第 519 行
- `_location_tokens()` — 第 542 行
- `_select_geocoding_result()` — 第 558 行
- `_first()` — 第 581 行
- `_optional_float()` — 第 587 行
- `_optional_int()` — 第 596 行
- `_representative_temperature()` — 第 605 行
- `_temperature_range()` — 第 619 行


## Lv19 时间与日历

- `silverwolf_agent.temporal.TemporalQueryAnalyzer`：识别时钟、日期、星期与相对日期问题。
- `silverwolf_agent.temporal.TemporalQuery`：Planner 与 Executor 之间的确定性时间语义。
- `silverwolf_agent.tools.CalendarQueryTool`：根据 ISO 日期返回中文星期。
- `ConversationExecutor._calendar_answer`：本地渲染准确、简短的日历回答。


## Lv20 新增/修改函数

- `TemporalQueryAnalyzer._contains_current_clock_question()`：按独立语义片段识别真正的当前钟点问题。
- `clean_schedule_title()`：清洗提醒标题，只保留动作。
- `ScheduleIntentAnalyzer._normalize_hour()`：增加睡觉语义的晚间 6—11 点消歧。
- `ConversationExecutor._clock_from_due()`：周期提醒确认提取本地 HH:MM。
- `ConversationExecutor._weekday_from_due()`：每周提醒确认提取星期。

## Lv21 认知状态新增

- `CognitiveStateManager.advance_offline()`：按天推进角色离线连续生活。
- `CognitiveStateManager.prepare_turn()`：观察用户、更新长期状态、形成 mood 与 Intent。
- `CognitiveStateManager.prepare_proactive()`：后台主动调度读取认知状态并推进连续性。
- `CognitiveStateManager.observe_silent_message()`：静默回复场景仍更新关系与认知状态。
- `CognitiveStateManager.record_assistant_reply()`：记录 Agent 输出，并标记已分享 Life Event。
- `CognitiveStateManager.prompt_view()`：向 Planner/Executor 暴露可控的认知上下文。

## Lv27 长期承诺与语料库新增

### `silverwolf_agent/commitment/`

- `contracts.CommitmentSeed`：还没补全的承诺（`known_slots()` / `missing_slots()`）。
- `contracts.Commitment`：已落库承诺（`occurrences()` 展开周次、`current_week()`、`remaining_weeks()`）。
- `contracts.ClarificationSession`：进行中的补全会话（`is_open()` / `expired()`）。
- `contracts.CommitmentTurn`：一轮处理结果（mode / goal_kind / facts / fallback_text）。
- `intent.CommitmentIntentAnalyzer.detect()`：识别长期承诺并抽标题。
- `intent.CommitmentIntentAnalyzer.extract_slots()`：抽 start / clock / weekdays / weeks。
- `intent.CommitmentIntentAnalyzer.apply_slots()`：把用户回答合并进 seed。
- `intent.CommitmentIntentAnalyzer.wants_finish/skip/cancel/edit()`：承诺状态操作识别。
- `intent.chinese_number()` / `intent.resolve_start_date()`：中文数字与起始日解析。
- `store.CommitmentStore`：承诺持久化与周次进度（`mark_week()` / `finish()` / `cancel()`）。
- `store.ClarificationStore`：补全会话持久化（同时只有一个）。
- `service.CommitmentService.handle()`：检测 → 追问 → 补全 → 落库 → 物化。
- `service.CommitmentService.materialize()` / `sync_schedule()`：把 occurrence 写成普通计划。
- `service.CommitmentService.plan_wording()`：到点播报（带第 N/M 周）。
- `service.CommitmentService.has_pending_clarification()`：供 Reply Gate 放行判断。
- `language.render_question/confirmation/occurrence_start/soft_nudge/...`：确定性兜底话术。

### `silverwolf_agent/dialogue/`

- `corpus.CorpusStore.samples()`：按场景/标签采样，避开冷却中的样句。
- `corpus.CorpusStore.style_profile()`：把语料共性提炼成风格指令。
- `corpus.CorpusStore.record_use()` / `recent_texts()`：冷却与重复检测。
- `corpus.overlap_ratio()`：字符 3-gram Jaccard，用于识别照抄。
- `speech.SpeechComposer.compose()`：事实 + 语料 → 模型措辞 → 五道护栏 → 兜底。
- `speech.SpeechComposer.style_block()`：给普通聊天注入少量语气样本。

### 修改

- `SilverWolfAgent._build_corpus_llm()`、`SilverWolfAgent.commitment_snapshot()`。
- `ConversationPlanner._commitment_required_tokens()`、承诺优先分支与 `_choose_render_mode` 扩展。
- `ConversationExecutor._render_commitment_goal()`、`_render_with_llm()` 注入 `style_block`。
- `PromptBuilder.pae_executor_prompt(style_block=...)`。
- `ProactivePlanner._render_due_content()`、`AsyncProactiveScheduler` 的 `commitment_service`。

## Lv28 记忆与反思新增

### `silverwolf_agent/memory/rag.py`（重写）

- `score_importance(text)`：确定性重要度打分，返回 `(分值, 命中原因)`。
- `RAGDocument.importance`：缺失字段时回退默认值 5。
- `JsonlRAGStore.add(..., kind=, importance=)`：写入时补 kind 与重要度。
- `JsonlRAGStore.search_scored(query, top_k, now=)`：三因子加权，附分数明细。
- `JsonlRAGStore.search(query, top_k, now=)`：保持旧签名，供既有调用方使用。
- `JsonlRAGStore.mark_recalled(ids, at=)` / `recall_count()` / `recall_stats()`：复习统计。
- `JsonlRAGStore._stability_days()` / `_recency()`：遗忘曲线。
- `JsonlRAGStore.stats()`：条数、kind 分布、平均重要度、召回数。

### `silverwolf_agent/memory/reflection.py`（新增）

- `ReflectionEngine.due(now)`：周触发 / 阈值触发 / 一天一次限制。
- `ReflectionEngine.run(now, trigger=, force=)`：取证 → 生成 → 护栏 → 落库。
- `ReflectionEngine._draft_with_llm()` / `_draft_statistical()`：模型版与离线统计版。
- `ReflectionEngine._filter_observations()`：证据强制 + 禁词过滤。
- `ReflectionEngine.snapshot(now)`：`/memory-stats` 的数据来源。
- `BANNED_CLAIM_PATTERNS`：禁止的人格定性词表。

### `silverwolf_agent/cognition/state.py`

- `SCHEMA_VERSION` 21 → 22，新增 `reflections` / `reflection` 字段（`_deep_fill` 幂等补齐）。
- `CognitiveStateManager.record_reflection()`：写反思、按证据写 beliefs、写 milestones。
- `CognitiveStateManager.reflection_snapshot()`：反思运行状态。

### 其它

- `ConversationExecutor._retrieve_rag(plan, now=)`：带 now 检索、记召回、输出重要度标签。
- `ProactivePlanner._silence_hours()` / `_open_threads()`、`silence_return_hours` 参数。
- `ContextualCareComposer.silence_continuation()`、`compose(silence_return=, open_threads=)`。
- `SilverWolfAgent.maybe_reflect()` / `memory_snapshot()`。
- CLI：`/memory-stats`、`/reflect`。

## Lv29 语料生长新增

### `silverwolf_agent/dialogue/corpus_learn.py`（新增）

- `CorpusLearner.consider_assistant_text()` / `consider_user_text()` / `add_manual()`：候选采集入口。
- `CorpusLearner.guard()`：确定性护栏（长度/形态/事实/隐私/语气/人格/重复）。
- `CorpusLearner._privacy_reason()`：五类隐私拦截（账号/网络/身份/密钥/环境变量）。
- `CorpusLearner.review()` / `approve()` / `reject()` / `reject_text()` / `retire()`：审核。
- `CorpusLearner.maintain()`：到期淘汰 + 按场景上限裁剪。
- `CorpusLearner.flush()`：内存缓冲落盘（避免每轮写小文件）。
- `CorpusLearner.stats()` / `snapshot()` / `list_learned()`：查询与统计。
- `CorpusLearner._audit()`：审计（只记类型与时间，不记原句）。

### `silverwolf_agent/dialogue/corpus.py`

- `CorpusSample` 新增 `kind`（style/phrase）与 `source`（handwritten/learned）。
- `CorpusStore.RESERVED_FILES`：排除 candidates / learned，避免待审内容被当手写语料。
- `CorpusStore._load_lines()`：按来源加载，跳过 retired。
- `CorpusStore.samples(kind=...)`：按级别取样本。
- `CorpusStore._balance_learned()`：learned 占比配平。
- `CorpusStore.stats()`：新增 learned / handwritten / phrase_entries。

### `silverwolf_agent/dialogue/speech.py`

- `SpeechComposer.phrase_mode`、`maybe_phrase()`：语气片段原样复用（默认关闭）。

### 其它

- `SilverWolfAgent._handle_corpus_feedback()` / `_learn_from_reply()` / `corpus_snapshot()`。
- CLI：`/corpus review|approve|reject|retire|list|stats|add`。

## Lv30 人设分层与主动时机新增

### `silverwolf_agent/dialogue/persona.py`（新增）

- `PersonaLibrary.select(user_input, goal_kinds)`：核心 + 常驻 + 命中模块。
- `PersonaLibrary.modules()` / `_parse_module()`：读取 `modules/*.md` 的 front-matter。
- `PersonaLibrary._match_reason()`：resident / scene / trigger 三类命中原因。
- `PersonaLibrary.full_text()`：核心 + 全部模块（历史断言与兜底用）。
- `PersonaLibrary.stats()`：核心字符数、模块数、常驻列表、预算。
- 三级兜底：`no_modules` → 历史整份人设 → 直读 persona 文件。

### `silverwolf_agent/prompts.py`

- `PromptBuilder._persona_for(user_input, goal_kinds)`：按本轮内容取人设。
- `PromptBuilder._packet_hints(execution_packet_json)`：从 ExecutionPacket 提取
  `plan.user_input` 与 `response_goals[].kind`。
- `PromptBuilder.last_persona_selection`：本轮注入清单（供 `/persona`）。

### `silverwolf_agent/proactive/time_manager.py`

- `TimeManager.__init__(..., jitter_enabled, jitter_minutes, pinned_days)`。
- `TimeManager.apply_jitter(scheduled, key, slot, now)`：关系型关心触发时刻。
- `TimeManager._jitter_offset()`：sha256(日期+槽位+基准时间) 的确定性偏移。
- `TimeManager._is_pinned()`：用户近期改过的时间槽保持准点。
- `TimeManager.set_slot()`：写入 `updated_at` 作为 pinned 依据。
- 注意：`default_due_time()` 与 `PlanManager` 的 `due_at` **不经过抖动**。

### 其它

- `SilverWolfAgent.persona_snapshot(text="")`、CLI `/persona [试算句子]`。

## Lv31 主动消息语料化新增

### `silverwolf_agent/proactive/planner.py`

- `ProactivePlanner.__init__(..., speech, speech_enabled, speech_timeout_seconds,
  speech_max_chars, speech_scenes, speech_max_calls, speech_samples)`。
- `ProactivePlanner._speech_allowed(scene_key)`：场景白名单 + 每轮调用上限 + 可用性。
- `ProactivePlanner._speak(...)`：统一入口，返回 `(最终文案, 来源)`；异常一律兜底。
- `ProactivePlanner.plan_json()`：每轮重置 `_speech_calls` 与 `last_speech_sources`。
- `ProactivePlanner._render_due_content()`：仅 `relationship_event_follow_up` 走语料化，
  `commitment_occurrence` 与普通提醒保持确定性。

### `silverwolf_agent/dialogue/speech.py`

- `SpeechComposer.compose_bounded(timeout_seconds, **kwargs)`：线程 + `future.result(timeout)`
  硬超时；超时 `source=timeout`、异常 `source=error`，均返回兜底文案。
- `SpeechComposer.compose(..., samples=None)`：单次调用可覆盖语料条数。

### `silverwolf_agent/proactive/state.py` / `scheduler.py`

- `ProactiveStateStore.record_template_use(..., source="")`：记录生成来源。
- `AsyncProactiveScheduler`：投递后把 `speech_source` 写入模板历史。

### `silverwolf_agent/world/proactive.py`

- `ContextualCareComposer.compose()`：metadata 增加 `weather_location` / `weather_condition`
  作为语料重写时必须保留的事实词。

## Lv32 自我分享与隐式信号新增

### `silverwolf_agent/cognition/state.py`

- `CognitiveStateManager.pick_shareable_event(now, min_age_days, max_age_days, setback_days)`：
  确定性挑选"她自己的事"（最老未分享优先、同类不连发、挫折类限频）。
- `CognitiveStateManager.mark_event_shared(event_id, now)`：写 `shared_at`。
- `CognitiveStateManager.share_snapshot()`：可分享/已分享/未分享计数与最近 kind。
- `SETBACK_LIFE_KINDS`：需要限频的事件类型（`failed_plan`）。

### `silverwolf_agent/proactive/planner.py`

- `ProactivePlanner._maybe_self_share(now, casual_alias)`：选事件 → `_speak(scene="self_share")`
  → 世界断言检查 → 返回可追加的一句；写 `last_self_share`。
- `ProactivePlanner.WORLD_CLAIM_PATTERNS`：禁止把角色生活说成真实世界事实的词表。
- routine 消息 metadata 增加 `self_share` / `self_share_kind`。

### `silverwolf_agent/proactive/state.py`

- `ProactiveStateStore.self_share_allowed(now, per_week)`：近 7 天计数限制。
- `ProactiveStateStore.record_self_share(now)`：写入 `self_share_history`。

### `silverwolf_agent/dialogue/corpus_learn.py`

- `CorpusLearner.record_implicit_signal(text, at)` / `implicit_score(text)`：
  隐式正向信号（只影响排序，绝不自动转正）。
- `CorpusLearner.review()`：按 `(信号数, 创建时间)` 倒序返回待审。

### `silverwolf_agent/agent.py`

- `SilverWolfAgent._maybe_record_implicit_signal(text, now)`：窗口内的继续聊记弱正向。
- `SilverWolfAgent.last_interactive_reply`：上一条交互回复（时间 + 文本）。

## Lv33 可观测性新增

### `silverwolf_agent/diagnostics.py`（新增）

- `Check`：单项检查（category / name / status / detail / hint），三态 `OK|未生效|异常`。
- `DoctorReport.render()` / `to_dict()`：人话输出与结构化输出。
- `Doctor.run()`：依次跑配置、数据、目录三类检查并生成结论。
- `Doctor._config_checks()`：API Key、模型/时区、六个功能开关。
- `Doctor._data_checks()`：认知 schema、反思次数、RAG 重要度覆盖、召回统计、
  长期承诺、语料生长、自我分享、主动语料化、最后活动距今。
- `Doctor._directory_checks()`：`ensure_directories()` + 探针写入验证可写性。
- `Doctor._conclusion()`：按优先级生成可行动的结论。
- 设计约束：**只读**、不调模型、不联网。

### `silverwolf_agent/agent.py`

- `SilverWolfAgent.doctor_report(now=None)`：返回 `{checks, ok_count, total, problems, conclusion, text}`。
- `SilverWolfAgent.status_report(now=None)`：聚合各 snapshot 并渲染成一行一项。

### `silverwolf_agent/cognition/state.py`

- `CognitiveStateManager.LIFE_CATALOG`：生活事件目录 7 → 24 种。
- `pick_shareable_event(..., kind_cooldown_days=30)`：同类事件冷却。

### `silverwolf_agent/proactive/planner.py`

- `ProactivePlanner.self_share_kind_cooldown_days`：透传给事件选择。

### CLI

- `/doctor`、`/status`。
