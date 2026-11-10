# 银狼 Agent

An AI Companion Agent project with personal and persona-related private data removed, preserving the core architecture and code for learning, research, and version comparison.

一个带长期记忆、主动关心和计划能力的电子女友 Agent，Python 实现，通过 Anthropic 兼容接口调用大模型。

核心是一个 **PAE（Perceive → Analyze → Execute）** 循环：感知用户消息与时间，交给 Planner 判断意图，再由 Executor 执行闲聊、计划、提醒、承诺或主动行为。对话核心只用标准库；Web 界面需要 Flask，QQ 接入需要 websockets，配置加载用 python-dotenv。

## 特性

| 维度 | 能力 |
| --- | --- |
| 对话 | 混合语义判定（闲聊 / 计划 / 提醒 / 承诺 / 记忆回响），回复质量闸门，消息分条发送 |
| 记忆 | 短期记忆、日总结、RAG 检索、重要度加权与遗忘、每周反思、旧事回响 |
| 主动 | 按时间段主动关心、防重复打扰、自己的 24 种生活事件（同类冷却 30 天） |
| 计划 | 日程与长期承诺、到期触发、时间偏好学习、计划标题规范化 |
| 人格 | 人设分层：核心常驻 + 9 个规则模块按需加载，三级兜底保证任何情况下都能回复 |
| 语料 | 从真实对话里学习表达风格，自生长语料库 |
| 通道 | CLI、Web、QQ（NapCat / OneBot 11）、守护进程 |
| 可观测 | `/doctor` 只读体检（✓ 通过 / · 未生效 / ✗ 异常）、`/status` 总览 |

## 快速开始

### 环境要求

- Python 3.10+（Windows 会通过 `tzdata` 补充时区数据）
- 一个 Anthropic 兼容的模型接口（例如 DeepSeek 的 Anthropic 端点）

### 安装

```powershell
pip install -r requirements.txt
```

### 配置

```powershell
copy .env.example .env
```

编辑 `.env`，至少填写：

```env
ANTHROPIC_API_KEY=你的 API Key
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
SILVERWOLF_MODEL=deepseek-v4-flash
SILVERWOLF_TIMEZONE=Asia/Shanghai

SILVERWOLF_MAX_TOKENS=1000
SILVERWOLF_TEMPERATURE=0.8
SILVERWOLF_MAX_RETRIES=3
SILVERWOLF_RETRY_BASE_SECONDS=1.5

SILVERWOLF_SCHEDULER_POLL_SECONDS=30
SILVERWOLF_MESSAGE_GAP_SECONDS=0.9
```

完整配置项见 `.env.example`，字段含义见 `docs/DATA_CONFIG_API.md`。

### 运行

```powershell
python examples/run_cli.py      # 聊天 + 主动任务
python examples/run_daemon.py   # 只跑主动任务
python examples/run_once.py     # 检查一次到期任务（适合系统计划任务）
python examples/run_web.py      # Web 界面
python examples/run_qq.py       # 接入 QQ
```

第一次运行会在 `data/` 下生成记忆、日程等运行时文件；`config/` 里的两份 profile 是示例模板，可以直接改。

## 命令行

```text
/status                      # 总览：对话轮数、待触发计划、记忆、语料、人设体量
/doctor                      # 只读体检，不调用模型、不写文件
/persona [文本]              # 查看人设体量与命中；传文本可试算模块命中
/summary                     # 生成日总结
/memory                      # 查看当前记忆
/plans                       # 查看计划
/plan cancel 关键词           # 取消计划
/time                        # 查看时间偏好
/time set morning 08:00      # 设置时间段
/proactive on|off            # 开关主动消息
/tick                        # 手动触发一次调度
/pae                         # 查看上一轮 Planner / Executor JSON
/exit                        # 退出
```

## 架构

```text
用户消息 ──► Perceive ──► Planner ──► Executor ──► 回复
                │           │            │
                │           │            ├─ 闲聊 / 计划 / 提醒 / 承诺
                │           │            ├─ 主动行为（定时触发）
                │           │            └─ 工具调用（时间、记忆、日程）
                │           └─ 输出结构化 JSON（意图、置信度、槽位）
                └─ 上下文：记忆、人设模块、时间、历史消息
```

关键模块：

| 模块 | 职责 |
| --- | --- |
| `pae/` | Planner / Executor / 调度 |
| `memory/` | 短期记忆、日总结、RAG、遗忘曲线 |
| `proactive/` | 主动关心、生活事件、消息语料化 |
| `commitment/` | 长期承诺与到期提醒 |
| `cognition/` | 认知状态与反思 |
| `dialogue/` | 语料学习与表达风格 |
| `persona` 相关 | 人设分层加载（核心 + 模块） |
| `qq/` | NapCat / OneBot 11 接入 |
| `webapp/` | Web 界面 |
| `diagnostics.py` | `/doctor` 体检 |
| `temporal/` | 时间语义（日期、星期、时段） |

## 目录结构

```text
.
├─ config/                  # 示例配置（可替换成自己的）
│  ├─ default_agent_profile.json
│  ├─ default_user_profile.json
│  └─ napcat_onebot11_ws_server.example.json5
├─ data/                    # 运行时数据（记忆、日程、日志、RAG…）
├─ deploy/                  # systemd / Windows 部署脚本
├─ docs/                    # 架构、配置、QQ 接入等文档
├─ examples/                # 五种启动方式
├─ silverwolf_agent/        # 源码
├─ tests/                   # 回归与集成测试
├─ tools/                   # 运维脚本
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 数据与隐私

- `data/` 与 `.env` 都已在 `.gitignore` 中，不会进仓库。
- `config/` 里只有示例 profile，没有真实个人信息。
- 人设文件、语料库、记忆数据由使用者自己准备，本仓库不附带。
- 运行时生成的数据请自行备份，不要提交到公开仓库。

## 测试

测试是独立脚本，每个文件可直接运行：

```powershell
python tests/smoke_test.py
python tests/lv33_diagnostics_test.py
# 共 42 个测试脚本，按需逐个运行
```

覆盖对话流程、记忆、计划、主动行为、QQ 网关、诊断与语料学习。部分用例使用固定示例数据（`tests/data/`）。

## 文档

| 文档 | 内容 |
| --- | --- |
| `docs/CALL_FLOWS.md` | 消息与主动行为的完整调用流程 |
| `docs/DATA_CONFIG_API.md` | 配置项、数据文件、内部 API |
| `docs/FEATURE_CHECKLIST.md` | 功能自检清单与验证方法 |
| `docs/FUNCTION_INDEX.md` | 函数级索引 |
| `docs/MANUAL_REVIEW_CHECKLIST.md` | 人工验收清单 |
| `docs/QQ_*.md` | QQ 接入架构、配置、部署与测试 |

## 许可

未声明许可证。使用前请确认依赖项与服务条款。
