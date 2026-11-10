# 银狼 lv16：QQ / NapCat 部署指南

## 1. 架构

```text
手机 QQ 扫码
    ↓
NapCat 登录机器人 QQ
    ↓ OneBot 11 正向 WebSocket（本机 + Token）
银狼 lv16 QQGateway
    ↓
SilverWolfAgent / Planner / Tools / 主动调度器
    ↓
QQ 私聊主人
```

QQ 协议登录由 NapCat 完成。银狼项目不读取、不保存 QQ 密码，也不实现协议逆向登录。

本项目默认采用：

- NapCat 作为 QQ 登录端和 OneBot 11 服务端；
- 银狼作为 OneBot 11 正向 WebSocket 客户端；
- `MASTER_QQ` 作为唯一主人身份；
- 非主人消息不进入 LLM、短期记忆或 RAG；
- 主动消息固定发送给主人私聊。

其他框架只有在提供兼容的 OneBot 11 正向 WebSocket、事件格式和动作接口时才能替换 NapCat。

## 2. 账号准备

建议准备两个不同的 QQ 账号：

1. **主人账号**：你日常使用的 QQ，配置为 `MASTER_QQ`；
2. **机器人账号**：NapCat 登录的账号。

机器人账号与主人账号不能相同。`examples/check_qq_connection.py` 和 QQGateway 启动时都会检查这一点。

建议先让主人账号添加机器人账号为好友。若之后删除并重新添加，银狼会自动同意来自主人 QQ 的好友申请。

## 3. 安装并登录 NapCat

### Windows

1. 从 NapCat 官方发布页面下载 Windows 版本；
2. 按官方说明启动 NapCat；
3. 打开启动日志中显示的 WebUI 地址，默认端口通常为 `6099`；
4. 使用启动日志中的 WebUI Token 登录；
5. 在 WebUI 的“QQ 登录”页面选择 `QRCode`；
6. 使用机器人账号的手机 QQ 扫码确认；
7. 登录成功后进入“网络配置”。

### Linux

可以按 NapCat 官方 Shell / Docker 文档安装。首次登录或快速登录失效时，仍需通过二维码确认。

### 登录安全

- 不要把 NapCat WebUI 暴露到公网；
- 修改 WebUI 初始密码；
- QQ 登录凭证只保留在 NapCat 侧；
- 银狼 `.env` 中不应出现 QQ 密码。

## 4. 配置 NapCat 正向 WebSocket

在 NapCat WebUI：

1. 打开“网络配置”；
2. 点击“新建”；
3. 类型选择 **WebSocket 服务端**；
4. 监听地址填写 `127.0.0.1`；
5. 端口填写 `3001`，或选择其他未占用端口；
6. 设置一个高强度 OneBot Token；
7. 消息上报格式建议选择数组；
8. 勾选保存时启用；
9. 保存并确认服务已启用。

对应银狼配置：

```env
ONEBOT_WS_URL=ws://127.0.0.1:3001
ONEBOT_ACCESS_TOKEN=与NapCat完全相同的Token
```

不要将 WebSocket 监听地址设置为 `0.0.0.0` 后直接暴露公网。必须跨机器部署时，应使用防火墙、内网或安全隧道，并保持 Token 验证。

## 5. 安装银狼 lv16

### Windows PowerShell

```powershell
cd silverwolf-lv16

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item ".env.example" ".env"
notepad ".env"
```

### Linux

```bash
cd /opt/silverwolf-lv16

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
nano .env
```

## 6. 最小 `.env` 配置

```env
ANTHROPIC_API_KEY=你的DeepSeek或兼容API密钥
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
SILVERWOLF_MODEL=deepseek-v4-flash
SILVERWOLF_TIMEZONE=Asia/Shanghai

QQ_BOT_ENABLED=true
MASTER_QQ=你的主人QQ号

ONEBOT_WS_URL=ws://127.0.0.1:3001
ONEBOT_ACCESS_TOKEN=与NapCat相同的高强度Token
QQ_ALLOW_EMPTY_ONEBOT_TOKEN=false

QQ_AUTO_ACCEPT_MASTER_FRIEND=true
QQ_REJECT_NON_MASTER_FRIEND=true
QQ_NOTIFY_NON_MASTER_PRIVATE=true
QQ_NOTIFY_NON_MASTER_GROUP=false
QQ_ALLOW_MASTER_GROUP_MESSAGE=false

QQ_EMERGENCY_COMMAND=/qq shutdown
QQ_EMERGENCY_TOKEN=另一个高强度随机字符串
```

注意：

- `MASTER_QQ` 只能是纯数字；
- `ONEBOT_ACCESS_TOKEN` 与 NapCat 配置必须完全一致；
- `QQ_EMERGENCY_TOKEN` 不要与 OneBot Token 或 API Key 相同；
- `.env` 已从发布压缩包排除，不要上传到代码仓库。

## 7. 连接自检

确保 NapCat 已登录并启用 WebSocket，然后执行：

```powershell
python examples/check_qq_connection.py
```

正常输出应包含：

```text
连接成功。
QQ号：机器人QQ
昵称：机器人昵称
在线状态：True
运行状态：True
主人 QQ 配置：主人QQ
QQ 网关配置自检通过。
```

常见错误：

### `QQ_BOT_ENABLED=false`

在 `.env` 设置：

```env
QQ_BOT_ENABLED=true
```

### `MASTER_QQ` 缺失

设置真实主人 QQ：

```env
MASTER_QQ=123456789
```

### WebSocket 连接失败

检查：

- NapCat 是否已登录；
- WebSocket 服务端是否启用；
- 地址和端口是否一致；
- 系统防火墙是否拦截；
- 是否误把 WebUI 端口 `6099` 当成 OneBot 端口；
- NapCat 和银狼是否运行在同一网络命名空间。

### `403` 或握手失败

通常是 Token 不一致。重新核对：

```env
ONEBOT_ACCESS_TOKEN=...
```

## 8. 启动 QQ 网关

```powershell
python examples/run_qq.py
```

Windows 也可运行：

```powershell
.\deploy\windows\start_silverwolf_qq.ps1
```

启动后：

- 银狼后台主动调度器会将消息发给主人 QQ 私聊；
- 主人私聊会进入 Agent；
- 非主人私聊不会获得回复；
- 非主人消息会按配置通知主人；
- 非主人好友申请默认拒绝；
- 主人好友申请默认同意。

## 9. 验收测试

### 主人消息

从主人账号给机器人发送：

```text
你好
```

期望：

- 银狼正常回复；
- 日志出现 `master_message_accepted`；
- 消息进入短期记忆。

### 账号信息

发送：

```text
报告你的账号信息
```

期望返回：

```text
我的 QQ 账号信息：
QQ号：...
昵称：...
在线状态：在线
运行状态：正常
OneBot实现：...
```

该指令由 QQGateway 本地处理，不占用 LLM 请求。

### 非主人消息

从其他 QQ 私聊机器人：

```text
你好
```

期望：

- 非主人收不到回复；
- 主人收到：

```text
[通知] 收到来自 QQ: 发送者QQ 的消息
昵称: ...
消息内容: 你好
时间: ...
```

- 日志出现 `identity_verification_failed`；
- 该消息不进入 Agent 记忆。

### 好友申请

- 主人申请：自动同意并备注“主人”；
- 非主人申请：自动拒绝，并通知主人。

### 紧急关闭

主人私聊：

```text
/qq shutdown 你的QQ_EMERGENCY_TOKEN
```

期望：

```text
紧急关闭指令已验证，银狼 QQ 网关正在停止。
```

错误 Token 只会记录失败日志，不会执行关闭。

由于 Token 会出现在 QQ 消息历史中，日常关闭优先使用 `Ctrl+C`、任务管理器或系统服务命令；QQ 紧急指令只作为备用。

## 10. 稳定运行

### Windows

可使用任务计划程序：

- 程序：项目 `.venv\Scripts\python.exe`
- 参数：`examples\run_qq.py`
- 起始目录：银狼项目目录
- 设置失败后重新启动
- NapCat 应先于银狼启动

### Linux systemd

复制示例：

```bash
sudo cp deploy/linux/silverwolf-qq.service.example \
  /etc/systemd/system/silverwolf-qq.service
```

修改：

- `User=CHANGE_ME`
- `WorkingDirectory`
- `ExecStart`

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now silverwolf-qq
sudo systemctl status silverwolf-qq
journalctl -u silverwolf-qq -f
```

NapCat 和银狼应分别设置自动重启。银狼 OneBot 客户端断线后会指数退避重连。

## 11. 日志位置

默认：

```text
data/qq/qq_gateway.jsonl
```

主要事件：

```text
qq_gateway_started
qq_gateway_stopped
master_message_accepted
identity_verification_failed
master_friend_request
non_master_friend_request
bot_info_refreshed
emergency_shutdown_auth_failed
qq_event_processing_failed
```

日志不会写入 OneBot Token、API Key 或紧急关闭 Token；消息内容仅保留最多 200 字预览。

## 12. 升级与数据迁移

从 lv15 迁移：

```powershell
Copy-Item `
  "..\silverwolf-lv15\.env" `
  ".\.env"

Copy-Item `
  "..\silverwolf-lv15\data\*" `
  ".\data\" `
  -Recurse -Force
```

然后将本指南中的 QQ 配置追加到 `.env`。

## 13. 官方参考

- NapCat 安装：https://napneko.github.io/guide/install
- NapCat WebUI 与二维码登录：https://napneko.github.io/config/basic
- NapCat 框架接入：https://napneko.github.io/use/integration
- NapCat OneBot API 兼容性：https://napneko.github.io/develop/api
- OneBot 11 公共 API：https://283375.github.io/onebot_v11_vitepress/api/public.html


## 16. 官方参考

- NapCat 安装：https://napneko.github.io/guide/install
- NapCat WebUI 与 OneBot 网络配置：https://napneko.github.io/config/basic
- NapCat OneBot 网络说明：https://napneko.github.io/onebot/network
- OneBot 11 标准：https://11.onebot.dev/
- websockets asyncio client：https://websockets.readthedocs.io/en/latest/reference/asyncio/client.html
