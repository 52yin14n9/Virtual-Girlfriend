# 银狼 lv16：QQ 网关测试报告

## 结论

QQ 网关业务逻辑、OneBot 11 传输层和历史功能回归全部通过。

## QQ 业务测试

测试文件：

```text
tests/lv16_qq_gateway_test.py
```

通过项：

- `MASTER_QQ` 和紧急 Token 配置校验；
- OneBot 消息段安全文本化；
- 主人私聊进入 Agent；
- 主人消息使用最高队列优先级；
- 非主人私聊不进入 Agent；
- 非主人私聊按格式通知主人；
- 身份验证失败写入 JSONL 日志；
- 日志不包含 OneBot Token；
- 主人好友申请自动同意；
- 非主人好友申请自动拒绝；
- 账号信息指令返回 QQ、昵称、在线和实现版本；
- 错误紧急 Token 不关闭；
- 正确紧急 Token 停止网关；
- 重复 message_id 不重复处理；
- 主人群聊默认忽略；
- 开启群聊配置后只处理主人；
- QQMessageSink 私聊和群聊发送。

## OneBot 真实传输测试

测试文件：

```text
tests/lv16_onebot_transport_test.py
```

测试会在本机临时启动真实 WebSocket 服务，并验证：

- `Authorization: Bearer <token>` 握手头；
- `get_login_info` 动作和 echo 关联；
- `get_status` 动作；
- `send_private_msg` 参数；
- OneBot 事件主动推送；
- 客户端关闭后的连接状态。

该测试使用真实 `websockets.asyncio` 网络栈，不是只检查模拟方法调用。

## 历史回归

```text
smoke_test.py                         PASS
lv9_regression_test.py                PASS
lv10_identity_test.py                 PASS
lv11_memory_scheduler_test.py         PASS
lv12_model_planner_test.py            PASS
lv13_follow_up_test.py                 PASS
lv14_message_variation_test.py        PASS
lv15_identity_experience_test.py      PASS
lv15_final_boundary_dataset_test.py   PASS
lv16_qq_gateway_test.py               PASS
lv16_onebot_transport_test.py         PASS
```

其他检查：

```text
Python compileall                     PASS
Python AST parse                      PASS
JavaScript syntax                     PASS
Markdown internal links               PASS
```

## 未进行的测试

发布环境没有真实 QQ 账号和用户的 NapCat 实例，因此没有执行真实 QQ 登录、真实好友申请和公网网络测试。

真实部署前应按 `QQ_DEPLOYMENT_GUIDE.md` 完成：

1. NapCat 扫码登录；
2. OneBot WebSocket 配置；
3. `examples/check_qq_connection.py`；
4. 主人、非主人、好友申请和紧急关闭验收。
