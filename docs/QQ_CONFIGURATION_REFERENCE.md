# 银狼 lv16：QQ 配置与接口参考

## 1. QQBotConfig

源码：

```text
silverwolf_agent/qq/config.py
```

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `QQ_BOT_ENABLED` | `false` | 是否启用 QQ 网关 |
| `MASTER_QQ` | 空 | 唯一主人 QQ，必须配置 |
| `ONEBOT_WS_URL` | `ws://127.0.0.1:3001` | OneBot 11 正向 WebSocket |
| `ONEBOT_ACCESS_TOKEN` | 空 | OneBot 鉴权 Token |
| `QQ_ALLOW_EMPTY_ONEBOT_TOKEN` | `false` | 是否允许空 Token，仅隔离测试使用 |
| `QQ_AUTO_ACCEPT_MASTER_FRIEND` | `true` | 自动同意主人好友申请 |
| `QQ_REJECT_NON_MASTER_FRIEND` | `true` | 自动拒绝非主人好友申请 |
| `QQ_FRIEND_REQUEST_LOG_ENABLED` | `true` | 记录好友申请 |
| `QQ_NOTIFY_NON_MASTER_PRIVATE` | `true` | 非主人私聊通知主人 |
| `QQ_NOTIFY_NON_MASTER_GROUP` | `false` | 非主人群消息通知主人 |
| `QQ_ALLOW_MASTER_GROUP_MESSAGE` | `false` | 允许主人从群聊调用 Agent |
| `QQ_EMERGENCY_COMMAND` | `/qq shutdown` | 紧急关闭命令前缀 |
| `QQ_EMERGENCY_TOKEN` | 空 | 紧急关闭验证 Token |
| `ONEBOT_ACTION_TIMEOUT_SECONDS` | `15` | OneBot 动作超时 |
| `ONEBOT_RECONNECT_INITIAL_SECONDS` | `2` | 首次重连延迟 |
| `ONEBOT_RECONNECT_MAX_SECONDS` | `30` | 最大重连延迟 |
| `ONEBOT_PING_INTERVAL_SECONDS` | `20` | WebSocket Ping 间隔 |
| `ONEBOT_PING_TIMEOUT_SECONDS` | `20` | Pong 超时 |
| `QQ_NOTIFICATION_MAX_CHARS` | `1000` | 通知主人时的最大消息长度 |
| `QQ_EVENT_QUEUE_MAX_SIZE` | `1000` | 事件优先队列容量 |
| `QQ_AUDIT_LOG_PATH` | `data/qq/qq_gateway.jsonl` | JSONL 审计日志 |

## 2. 模块结构

```text
silverwolf_agent/qq/
├─ __init__.py
├─ config.py       # 环境变量和安全校验
├─ events.py       # OneBot 事件解析、消息段文本化
├─ onebot.py       # 正向 WebSocket、动作调用、重连
├─ sink.py         # Agent OutboundMessage → QQ
├─ audit.py        # JSONL 审计日志
└─ gateway.py      # 主人鉴权、好友申请、通知、命令
```

## 3. QQGateway 调用结构

```text
OneBot WebSocket 事件
    ↓
QQGateway.enqueue_event()
    ↓ PriorityQueue
主人消息 priority=0
    ↓
QQGateway.process_event()
    ├─ message
    │   ├─ 主人 → SilverWolfAgent.handle_user_message()
    │   └─ 非主人 → notify_master()，不进入 Agent
    ├─ request.friend
    │   ├─ 主人 → set_friend_add_request(approve=true)
    │   └─ 非主人 → set_friend_add_request(approve=false)
    └─ meta_event.lifecycle
        └─ refresh_bot_info()
```

## 4. 主人优先级

| 事件 | 优先级 |
|---|---:|
| 主人消息 | `0` |
| 主人好友申请 | `1` |
| 生命周期事件 | `10` |
| 非主人好友申请 | `20` |
| 非主人消息 | `30` |
| 其他事件 | `50` |

该优先级用于已进入本地队列的事件。当前正在执行的 LLM 请求不会被强制中断。

## 5. 支持的 OneBot 动作

| 动作 | 用途 |
|---|---|
| `send_private_msg` | 私聊主人、非主人通知 |
| `send_group_msg` | 可选的主人群聊回复 |
| `set_friend_add_request` | 同意主人、拒绝其他好友申请 |
| `get_login_info` | 获取机器人 QQ 与昵称 |
| `get_status` | 获取在线与运行状态 |
| `get_version_info` | 获取 OneBot 实现和版本 |
| `get_stranger_info` | 非主人昵称补充查询 |

## 6. 支持的事件

| OneBot 事件 | 行为 |
|---|---|
| `message.private` | 主人进入 Agent；其他人仅通知 |
| `message.group` | 默认忽略；可选择只允许主人 |
| `request.friend` | 按主人 QQ 自动同意或拒绝 |
| `meta_event.lifecycle` | 记录连接并刷新账号信息 |
| 其他事件 | 当前忽略 |

## 7. 本地命令

### 查询账号

```text
报告你的账号信息
报告账号信息
你的QQ账号信息
/qq info
/qq status
```

### 紧急关闭

```text
/qq shutdown <QQ_EMERGENCY_TOKEN>
```

只有主人消息能够进入命令处理器。

## 8. 消息段转换

OneBot 数组消息会转换为：

| 消息段 | Agent 可见文本 |
|---|---|
| `text` | 原文本 |
| `image` | `[图片]` |
| `record` | `[语音]` |
| `video` | `[视频]` |
| `file` | `[文件]` |
| `face` | `[表情]` |
| `at` | `[@QQ号]` |
| `reply` | 忽略 |
| 未知类型 | `[类型名]` |

非文本附件不会被直接读取或下载。

## 9. 非主人通知格式

```text
[通知] 收到来自 QQ: {sender_qq} 的消息
昵称: {nickname}
来源群: {group_id}   # 仅群消息
消息内容: {message}
时间: {timestamp}
```

通知失败会写入日志，但不会向非主人回复。

## 10. 安全不变量

1. `MASTER_QQ` 不在源码中；
2. 默认要求 OneBot Token；
3. 非主人消息不调用 Agent；
4. 非主人消息不写入短期记忆或 RAG；
5. 非主人好友申请默认拒绝；
6. 紧急关闭要求主人 QQ 和独立 Token 同时正确；
7. 机器人 QQ 不能等于主人 QQ；
8. 群聊默认关闭；
9. WebSocket 默认关闭系统代理，优先本机直连；
10. 日志不记录任何密钥。

## 11. 运行入口

```text
examples/check_qq_connection.py  # 只检查 OneBot 配置与账号
examples/run_qq.py               # 启动完整 QQ 网关
```

## 12. 测试

```text
tests/lv16_qq_gateway_test.py
tests/lv16_onebot_transport_test.py
```

覆盖：

- 主人消息进入 Agent；
- 非主人消息不回复，只通知主人；
- 身份失败日志；
- 主人/非主人好友申请；
- 账号信息查询；
- 紧急关闭成功与失败；
- 消息去重；
- 群聊默认关闭与可选开启；
- QQMessageSink；
- 真实本地 WebSocket Token 握手；
- 带 echo 的 OneBot 动作响应；
- WebSocket 事件接收。
