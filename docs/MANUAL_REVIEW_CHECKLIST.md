# 银狼 lv16 人工复审清单

## A. 启动与隔离

- [ ] `.env` 没有被提交或打包；
- [ ] `python examples/run_web.py` 只监听 `127.0.0.1:5000`；
- [ ] `use_reloader=False`，避免启动两个 Scheduler；
- [ ] 关闭进程后确认主动消息停止；
- [ ] 使用测试账号/API Key，避免真实隐私数据进入日志。

## B. 交互对话 PAE

- [ ] `/api/debug/pae` 中 Planner JSON 能看到所有语义目标；
- [ ] 多目标句不会只回答工具结果；
- [ ] `render_mode=local` 与 `render_mode=llm` 行为合理；
- [ ] 最近 30 轮以真实 role 消息进入模型；
- [ ] 模型异常时能回退本地回复；
- [ ] 回复拆分顺序与 weight 符合预期。

建议用例：

```text
今天中午睡得很不错，对了现在几点了
一直在开发东西，感觉有点晕
我刚才问你的时候是什么时间
```

## C. 日程模型裁决

- [ ] “更新晚饭时间到 17:40”调用 `time_preferences_set`；
- [ ] “一分钟后叫我”调用 `plan_create`；
- [ ] 模型返回非法 25:70 时拒绝；
- [ ] Planner API 失败时规则回退；
- [ ] 没有成功工具结果时不做虚假承诺；
- [ ] `/api/debug/pae` 中 `schedule_resolution_source` 正确。

## D. 主动模板多样化

- [ ] 连续多天晚间主动消息不会相邻重复；
- [ ] 前端标签能看到 `template_group/template_id`；
- [ ] `/api/debug/proactive` 中模板历史只记录实际发送消息；
- [ ] `SILVERWOLF_PROACTIVE_TEMPLATE_HISTORY_LIMIT` 生效；
- [ ] 全部措辞已在 `PROACTIVE_MESSAGE_CATALOG.md` 人工审查；
- [ ] 已吃过晚饭后不再询问“晚饭吃了吗”；
- [ ] 最近说“忙/开发”时能进入 busy 组；
- [ ] 最近说“累/不舒服”且未确认吃饭时能进入 tired 组。

## E. 未回复追问

- [ ] `expects_reply=true` 后建立 pending_follow_up；
- [ ] 两分钟内回复立即取消；
- [ ] 恰好两分钟回复时不同时发送追问；
- [ ] 两分钟无回复只追问一次；
- [ ] 15 分钟后陈旧追问过期；
- [ ] 程序重启后短期等待可恢复；
- [ ] 普通闹钟/休息结束不催回复；
- [ ] 新主动关心替换旧 pending 时行为可接受。

## F. 记忆与历史

- [ ] `short_term.json` 保存 user_at/assistant_at；
- [ ] 最近 30 轮不被过早摘要；
- [ ] 主动消息进入短期记忆；
- [ ] 用户询问历史时间时读取实际时间戳；
- [ ] 日总结写入 RAG；
- [ ] 普通对话不会无故触发 RAG；
- [ ] 用户档案背景不被频繁主动暴露。

## G. 时间与年龄

- [ ] 业务时区为预期时区；
- [ ] 2027-06-06 银狼回答 18 岁；
- [ ] 2027-06-07 银狼回答 19 岁；
- [ ] 相对提醒保留秒/微秒精度；
- [ ] 修改 morning/noon/evening 后次日 routine 正确。

## H. Web 与 SSE

- [ ] 用户消息先出现在页面；
- [ ] 多条助手消息分开发送；
- [ ] 主动消息无需用户新请求即可出现；
- [ ] EventSource 断线后自动重连；
- [ ] MessageStore 不出现重复 event_id；
- [ ] `/api/status` 信息正确；
- [ ] `/api/debug/proactive` 不应暴露给公网；
- [ ] 页面 HTML 插入使用 `textContent`，不执行模型输出 HTML。

## I. 持久化与并发

- [ ] JSON 文件损坏时能恢复默认结构；
- [ ] 单个进程内线程锁有效；
- [ ] 不使用 Flask reloader 产生双调度器；
- [ ] 评估未来多进程部署前迁移到数据库/队列；
- [ ] PlanManager 不重复触发同一计划；
- [ ] Scheduler `_run_lock` 防止并发重复发送。

## J. 自动化测试映射

| 测试文件 | 主要测试函数 |
|---|---|
| `tests/lv10_identity_test.py` | `test_dynamic_age_boundary`, `test_prompt_dynamic_age`, `test_local_self_identity_answers` |
| `tests/lv11_memory_scheduler_test.py` | `test_exact_two_minute_message_request`, `test_no_fake_promise_without_due_time`, `test_thirty_turn_real_history`, `background_delivery_case`, `test_background_delivery` |
| `tests/lv12_model_planner_test.py` | `test_dinner_time_update`, `reminder_delivery_case`, `test_one_minute_reminder`, `test_clarification`, `test_invalid_model_output_falls_back` |
| `tests/lv13_follow_up_test.py` | `no_reply_follow_up_case`, `prompt_reply_cancels_case`, `exact_boundary_reply_case`, `expiry_case`, `restart_persistence_case`, `cancellation_during_planning_case`, `scheduled_reminder_does_not_nag_case` |
| `tests/lv14_message_variation_test.py` | `routine_variation_case`, `context_group_case`, `follow_up_variation_case`, `review_observability_case`, `template_inventory_case` |
| `tests/lv9_regression_test.py` | `test_relative_two_minute_reminder`, `test_exact_conversation_times`, `test_flask_frontend` |
| `tests/smoke_test.py` | `test_config_and_imports`, `test_mixed_goal_and_split_messages`, `test_schedule_importance_and_creation`, `test_low_importance_is_not_persisted`, `test_time_preference_edit`, `test_async_proactive_scheduler`, `test_lv6_failure_regression` |

## K. 复审记录模板

```text
复审日期：
复审版本：银狼 lv16
复审人：

高风险问题：
1.
2.

中风险问题：
1.
2.

文案问题：
1.
2.

通过项：
1.
2.

建议进入 lv15 的改动：
1.
2.
```
