# 个人 Agent 助手 · 说明文档

> 快速部署与使用说明见 [README.md](README.md)。

> 一个仿照 [nanobot](https://github.com/HKUDS/nanobot) 极简架构实现的 CLI Agent：
> **OpenAI 兼容 LLM + 工具调用循环 + 会话隔离记忆 + MCP 扩展**，纯 Python，模块化分层。

---

## 一、需求描述

### 1.1 项目定位

面向**本地命令行**的个人助手。核心是一个「工具调用循环」：

> 接收输入 → LLM 判断「直接回答」还是「调用工具」→ 执行工具 → 结果喂回 LLM → 循环直到给出结论。

不做多平台接入、不做 Web UI、不做定时任务，只把「一个能真正干活的 CLI Agent」拆解清楚，便于学习和二次开发。

### 1.2 功能需求

| 编号 | 需求 | 验收标准 |
| --- | --- | --- |
| F1 | **CLI 交互** | 命令行 REPL 循环；输入回车执行；`exit` / `quit` 退出；单次异常不退出 |
| F2 | **LLM 接入** | 调用 OpenAI 兼容接口；模型名固定从 `.env` 读取，代码内无切换逻辑 |
| F3 | **工具注册与执行** | 统一的 `Tool` 抽象 + `ToolRegistry`；至少内置 `read_file` / `write_file` / `run_shell` |
| F4 | **ReAct 循环** | 带 `max_steps` 上限；支持一次返回多个工具调用；工具结果回喂 |
| F5 | **配置** | API 配置写在 `.env`；提供 `.env.example` 模板 |
| F6 | **中文注释** | 全部注释中文；关键函数有中文 docstring（含参数与返回值） |
| F7 | **模块化分层** | LLM 封装 / 工具注册 / Agent 循环 / CLI 入口各自独立 |
| F8 | **联网能力** | 网页搜索 + 网页正文抓取（免 API Key） |
| F9 | **PDF 解析** | 提取正文与表格；**保留表格的缩进嵌套层级** |
| F10 | **短期记忆** | 会话对话持久化；超长时自动摘要压缩 |
| F11 | **长期记忆（RAG）** | 本地向量化 + 语义检索；按会话隔离 |
| F12 | **历史会话** | 列出 / 新建 / 切换 / 删除会话；会话间记忆默认不互通 |
| F13 | **MCP 扩展** | 作为 MCP 客户端接入外部 MCP 服务（已接入邮件发信） |

### 1.3 明确的非目标

- ❌ 多平台接入（微信 / Telegram / 飞书等）
- ❌ Web UI、图形侧边栏
- ❌ 定时任务 / 主动触发
- ❌ 模型切换、多模型路由
- ❌ 沙箱隔离：`read_file` / `write_file` / `run_shell` 直接操作本机，**仅建议本地学习使用**

---

## 二、业务流描述

### 2.1 启动流程

```
main.py / python -m mybot
        │
        ▼
  cli.main()
        │
        ├─ 1. load_config()           读 .env：API Key / Base URL / 模型名 / max_steps
        │
        ├─ 2. LLMClient(...)          创建 OpenAI 兼容客户端（仅记下模型名，不"加载模型"）
        │
        ├─ 3. load_memory_config()
        │      ├─ ShortTermMemory     → <MEMORY_DATA_DIR>/sessions/*.jsonl
        │      └─ LongTermMemory      → Chroma + 本地 bge 模型（失败则降级为禁用）
        │
        ├─ 4. SessionIndex            → sessions\index.json（会话标题/时间索引）
        │      └─ 启动时选一个会话：继承旧 default → 否则新建 → 否则用最近使用的
        │
        ├─ 5. create_default_registry(长期记忆)
        │      └─ 注册 6 个基础工具 + 2 个记忆工具
        │
        ├─ 6. 连接邮件 MCP（可选）
        │      └─ 发现工具 → 白名单过滤 → 包装成同步 Tool → 注册
        │
        └─ 7. 打印状态，进入 REPL
```

**降级原则**：记忆模型缺失、MCP 连不上，都只打印一行提示，**不阻断启动**。

### 2.2 单轮对话主流程

```
用户输入
   │
   ├─ 以 "/" 开头  → 交给 _handle_command() 处理（不消耗 LLM 调用）
   │
   ├─ exit / quit → 关闭 MCP 子进程 → 退出
   │
   └─ 普通文本
        │
        ▼
   Agent.run(user_input, session_id)
        │
        ├─ set_current_session(session_id)   ← 写入 ContextVar，供记忆工具读取
        ├─ session.compress_if_needed()      ← 只在回合开始压缩（保护 tool_call 配对）
        ├─ long_term.search(input, session)  ← 仅当前会话，命中则拼进 system
        ├─ messages.append({role: user})
        │
        ├─ ReAct 循环（最多 max_steps 步）
        │
        └─ return 最终结论
              │
              ▼
   cli 打印结论（不打印工具调用过程）
```

### 2.3 ReAct 循环

```
        ┌──────────────────────────────────────────┐
        │  for step in range(max_steps):           │
        │                                          │
        │   response = llm.chat_stream(messages,   │
        │                             tools_schema)│
        │            │                             │
        │            ├─ 无 tool_calls ─────────────┼──► 返回文本（任务完成）
        │            │                             │
        │            └─ 有 tool_calls              │
        │                  │                       │
        │                  ├─ append(assistant +   │
        │                  │        tool_calls)    │
        │                  │                       │
        │                  ├─ for call in calls:   │
        │                  │     result = registry │
        │                  │        .execute(...)  │
        │                  │     append({role:tool,│
        │                  │       tool_call_id,   │
        │                  │       content})       │
        │                  │                       │
        │                  └─ 继续下一轮            │
        └──────────────────────────────────────────┘
                          │
                 步数用尽 ──► 返回"已达到最大步数"提示
```

**关键约束**：assistant 消息里的每个 `tool_calls[].id`，后面必须有对应 `tool_call_id` 的 `tool` 消息，否则 OpenAI 兼容接口会直接报错。所以「先 append assistant，再 append 工具结果」的顺序不能颠倒，且**摘要压缩绝不能发生在一轮循环中间**。

**错误处理**：工具抛异常、参数非法、未知工具名，都转换成 `ToolResult.error(...)` 回喂给模型，让模型自行修正；不中断循环。

### 2.4 记忆读写流程

**短期记忆（对话上下文）**

```
每轮追加 user / assistant / tool 消息
        │
        ├─ 条数 > max_messages(30)
        │        │
        │        ▼
        │   调 LLM 把"较早的消息"压成一段摘要
        │        │
        │        ▼
        │   摘要 + 最近 keep_recent(10) 条原文 → 写回 JSONL
        │
        └─ 每个会话一个 JSONL；内存中最多缓存 200 个会话（LRU）
```

**长期记忆（RAG，按会话隔离）**

```
写入（模型主动调用 memory_save）
   │
   ├─ 校验 content 非空
   ├─ 取当前会话 session_id（来自 ContextVar，不是模型传参）
   └─ Chroma.add(向量, metadata={session_id, timestamp, type, tags})

读取（每轮自动触发一次）
   │
   ├─ 用本地 bge-small-zh-v1.5 把用户输入编码成 512 维向量
   ├─ collection.query(where={"session_id": 当前会话}, n_results=3)
   └─ 命中的记忆拼进【本轮】system 消息（不落盘）
```

**为什么要用 ContextVar 传会话？**
工具实例在启动时只创建一次，而会话会切换。若把 `session_id` 做成工具参数，模型就得自己填——既不可靠，也容易被对话内容带偏。所以由 `Agent.run()` 在入口处写入作用域，工具内部读取。

### 2.5 会话管理流程

| 动作 | 流程 |
| --- | --- |
| **新建** | 生成 `YYYYMMDD-HHMMSS-xxx` 形式的 ID → 写入 `index.json` → 切换过去（长期记忆检索范围立即变为新 ID） |
| **切换** | 更新 `updated_at` → 读取该会话 JSONL 并渲染最近 6 条对话 → 后续读写全部绑定新 ID |
| **删除** | 二次确认（需 `-y`）→ 删该会话全部向量 → 删 JSONL → 删索引 → 若删的是当前会话则自动切换到最近会话 |
| **自动命名** | 会话标题为空时，用首条用户输入的前 20 字作为标题 |

**隔离保证**：检索时 `where={"session_id": 当前会话}`，因此 A 会话写入的记忆在 B 会话**物理上检索不到**。跨会话检索只能由模型在用户明确要求后调用 `memory_search_other_sessions`，且结果会标注来源会话。

### 2.6 MCP 接入流程

```
启动
 ├─ 读取 MCP_EMAIL_COMMAND（如 uvx mcp-email-server@latest stdio）
 ├─ 后台守护线程建 asyncio 事件循环
 │     └─ stdio_client 拉起子进程 → initialize() 握手 → list_tools()
 ├─ 主线程等待就绪（threading.Event，超时即降级）
 ├─ 按 MCP_EMAIL_TOOLS 白名单过滤（默认只保留 send_email）
 ├─ 包装成同步 Tool（模型未填 account_name 时自动补全）
 └─ 注册进同一个 ToolRegistry
```

```
同步桥接：
  MCPToolWrapper.execute()  →  asyncio.run_coroutine_threadsafe(...)
                                   →  session.call_tool()
                                        →  stdio ⇄ MCP 子进程
```

---

## 三、实现说明

### 3.1 目录结构与模块职责

```
个人agent助手/
├── .env.example              配置模板（仅占位符）
├── README.md                 部署与使用说明
├── SECURITY.md               安全与 GitHub 上传说明
├── scripts/check_github_safety.py  上传前安全检查脚本
├── .gitignore                忽略 .env / .mybot / data / __pycache__ 等
├── requirements.txt          openai / python-dotenv / chromadb / sentence-transformers / pdfplumber / mcp / fastapi / uvicorn
├── main.py                   便捷入口
├── api_server.py             FastAPI 启动入口
├── ui/                       Vue 3 + Vite 前端
├── models/bge-small-zh-v1.5/ 本地嵌入模型（仓库内路径）
├── data/                    运行时记忆数据（默认生成，不提交）
├── setup_memory.py           下载本地嵌入模型到项目内 models/
├── mcp_server_demo.py        MCP 服务端教学示例（非运行依赖）
├── samples/                  PDF 测试样本
└── mybot/
    ├── __main__.py           python -m mybot
    ├── config.py             三组配置：LLM / Memory / MCP（支持外部 .env）
    ├── llm.py                OpenAI 兼容客户端（流式聚合）
    ├── agent.py              SYSTEM_PROMPT + ReAct 循环
    ├── memory.py             Session / ShortTermMemory（JSONL + 摘要压缩）
    ├── long_memory.py        LongTermMemory（Chroma + bge，按会话隔离）
    ├── sessions.py           SessionIndex（index.json，标题/时间）
    ├── session_scope.py      ContextVar：当前会话 ID
    ├── mcp_client.py         MCP 同步桥接 + 工具包装
    ├── cli.py                REPL + 斜杠命令
    ├── api.py                FastAPI 接口 + Agent 运行时装配
    └── tools/
        ├── base.py           Tool 抽象基类 + ToolResult
        ├── registry.py       注册表与执行分发
        ├── builtin.py        read_file / write_file / run_shell
        ├── web.py            web_search（Bing）/ web_fetch
        ├── pdf_tools.py      pdf_parse（含嵌套表格层级）
        └── memory_tools.py   memory_save / memory_search_other_sessions
```

**分层原则**：`llm` 只负责请求、`agent` 只负责循环、`tools` 只负责执行、`cli` 只负责展示。代码里所有 `print` 都收敛在 `cli.py`（MCP 诊断走 `stderr`）。

### 3.2 核心数据结构

**消息（OpenAI 格式）**

| role | 产生位置 | 说明 |
| --- | --- | --- |
| `system` | 每轮请求时组装 | 基础提示词 + 历史摘要 + 本轮检索到的长期记忆 |
| `user` | 用户输入 | — |
| `assistant` | LLM 回复 | 可能带 `tool_calls` |
| `tool` | 工具执行后 | 必须带与 `tool_calls[].id` 对应的 `tool_call_id` |

**工具（Tool）**

```python
name: str                              # 工具名
description: str                       # 给模型看的说明
parameters: dict                       # JSON Schema
execute(**kwargs) -> ToolResult        # 同步执行
```

**长期记忆 metadata**

```json
{
  "session_id": "20260927-153045-a1b",
  "timestamp": "2026-09-27T15:30:45",
  "type": "fact | preference | conclusion",
  "tags": "身份/项目"
}
```

**会话索引（index.json）**

```json
{"sessions": [{"session_id": "...", "title": "...", "created_at": "...", "updated_at": "..."}]}
```

### 3.3 关键技术决策

| 决策 | 理由 |
| --- | --- |
| 模型名只从 `.env` 读，无切换逻辑 | 「初始化」只是建 HTTP 客户端；模型选在每次请求的 `model` 字段 |
| 工具统一同步接口 | 简单、易调试；异步的 MCP 用后台线程桥接，不污染上层 |
| 记忆写入由**模型主动调用** `memory_save` | 由模型判断价值，避免寒暄入噪声；比每轮自动抽取省一次 LLM 调用 |
| 会话 ID 走 ContextVar 而非工具参数 | 工具实例全局唯一，会话会变；避免模型填错或被诱导 |
| 长期记忆只在**当前会话**检索 | 物理隔离，A 会话的信息不会"漏"到 B 会话 |
| 摘要压缩只在**回合开始**触发 | 避免切断 `assistant(tool_calls)` 与 `tool` 结果的配对 |
| 检索结果只在**请求期**注入，不落盘 | 否则每轮重复累积，上下文越滚越大 |
| MCP 工具按白名单过滤 | 服务有 18 个工具（含读信/删信），只暴露 `send_email` 才符合"只发件" |
| MCP 子进程 stderr 重定向到 `.mybot/mcp.log` | 否则 uvx 每次启动刷约 90 行 INFO；落盘后终端干净且可排查 |
| 会话时间戳用**微秒**精度 | 秒级精度会让同秒内的切换/新建排序并列，导致 `/switch` `/delete` 编号错位（已实测踩坑） |
| PDF 表格缩进按 **x 坐标聚类**换算层级 | 缩进没有显式结构，只能靠几何位置推断；并按列做基准归一化 |
| 拒绝"版式容器"被误判为表格 | 整列全空 / 单元格超 200 字 → 是分栏边框或整段散文，不是数据表格 |

### 3.4 工具清单

| 工具 | 能力 | 限制 |
| --- | --- | --- |
| `read_file` | 读本地文本文件 | 输出超 20,000 字符截断 |
| `write_file` | 写本地文件（自动建目录） | — |
| `run_shell` | 执行 shell 命令 | 默认超时 60 秒；输出截断 20,000 字符 |
| `web_search` | 联网搜索（解析 Bing 结果页） | 默认 5 条；依赖页面结构；需网络 |
| `web_fetch` | 抓取网页正文 | 默认 8,000 字符；内容类型白名单；**不执行 JS** |
| `pdf_parse` | 解析 PDF 正文 + 表格（保留缩进层级） | 默认 20,000 字符；不支持扫描件（无文本层） |
| `memory_save` | 写入当前会话的长期记忆 | 内容不能为空 |
| `memory_search_other_sessions` | 跨会话检索 | **仅用户明确要求时**使用，结果标注来源 |
| `send_email` | 通过 MCP 发邮件 | 仅发件；收件人受服务端白名单强制约束 |

### 3.5 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | （必填） | 缺失则启动报 `[配置错误]` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 兼容接口地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 模型名，代码内不切换 |
| `MYBOT_ENV_FILE` | 空 | 可选：指向仓库外的本地 `.env` 文件 |
| `MAX_STEPS` | `10` | 单轮 ReAct 最大步数 |
| `TEMPERATURE` | `0.0` | 采样温度 |
| `MEMORY_ENABLED` | `true` | 关闭后无记忆、无会话管理 |
| `MEMORY_DATA_DIR` | `<项目根>/data` | 记忆数据根目录；可用 `.env` 覆盖 |
| `MEMORY_MAX_MESSAGES` | `30` | 触发摘要压缩的条数 |
| `MEMORY_KEEP_RECENT` | `10` | 压缩后保留的近期消息数 |
| `MEMORY_TOP_K` | `3` | 每轮检索长期记忆条数 |
| `MEMORY_SESSIONS_DIR` / `MEMORY_CHROMA_DIR` | 空（从 `MEMORY_DATA_DIR` 推导） | 可单独覆盖 |
| `MEMORY_MODEL_DIR` | `<项目根>/models/bge-small-zh-v1.5` | 嵌入模型目录；留空使用项目内模型 |
| `MCP_EMAIL_ENABLED` | `false` | 默认关闭；配置邮件授权码后再开启 |
| `MCP_EMAIL_COMMAND` | `uvx mcp-email-server@latest stdio` | MCP 启动命令行 |
| `MCP_EMAIL_TOOLS` | `send_email` | 暴露给模型的 MCP 工具白名单 |
| `MCP_EMAIL_ACCOUNT` | 空 | `send_email` 的账号名默认值 |
| `MCP_EMAIL_TIMEOUT` | `60` | MCP 握手/调用超时（秒） |

### 3.6 已知限制

| 限制 | 影响 |
| --- | --- |
| 无沙箱 | `read_file` / `write_file` / `run_shell` 可操作本机任意路径 |
| 长期记忆无相似度阈值 | top-k 强制返回，可能注入不相关的记忆 |
| 会话文件为整份读写 | 会话极长时 JSONL 读写成本上升 |
| 仅支持一个 MCP 服务 | 配置项是邮件专用的单一槽位 |
| 网页解析依赖页面结构 | Bing 改版或目标站反爬时会失败（JS 渲染页面抓不到） |
| 不执行 JS | 知乎/微博等前端渲染站点正文可能缺失 |

---

## 四、使用示例（功能演示）

### 4.1 安装与启动

```powershell
cd "<项目根目录>"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

New-Item -ItemType Directory -Force "$HOME\.mybot" | Out-Null
Copy-Item .env.example "$HOME\.mybot\.env"
# 编辑 ~/.mybot/.env：填 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL

# 模型已随仓库放在 models/bge-small-zh-v1.5 时无需执行；
# 若模型缺失，运行下面命令下载到项目内（约 93MB）：
python setup_memory.py
python main.py              # 或 python -m mybot
```

启动输出：

```
========================================
  我的 CLI Agent 助手（仿 nanobot 极简版）
  输入内容回车执行；/help 查看命令；exit 或 quit 退出
========================================
模型：deepseek-flash    Base URL：https://api.deepseek.com/v1    最大步数：10
记忆：短期=开  长期=开（0 条）
会话：默认会话（default）    本会话长期记忆：0 条
MCP：已接入 1 个工具（send_email）

你 >
```

> 首次运行 `uvx` 需下载邮件 MCP 包，会慢一些；`MCP_EMAIL_ENABLED` 默认是 `false`，需要邮件时再改为 `true`。

> 真实密钥只放在仓库外：推荐 `~/.mybot/.env`，或通过 `MYBOT_ENV_FILE` 指定。详见 `SECURITY.md`。

> 仓库分发：默认模型路径是项目内 `models/bge-small-zh-v1.5`，不依赖盘符。如果模型文件未提交，克隆后运行 `python setup_memory.py`；若使用 Git LFS 管理模型，克隆后执行 `git lfs pull`。

### 4.2 基础对话

```
你 > 用一句话解释什么是 ReAct
助手 > ReAct 是让模型交替进行「推理（Reason）」和「行动（Act）」的范式：
        先想清楚下一步做什么，再调用工具获取信息，然后根据结果继续推理，直到得出结论。
```

> 输出只给**最终结论**，不显示工具调用过程与中间推理。

### 4.3 文件读写

```
你 > 读一下 requirements.txt，告诉我装了哪些库
助手 > 该项目依赖 6 个第三方库：openai、python-dotenv、chromadb、
        sentence-transformers、pdfplumber、mcp。

你 > 创建 notes/todo.txt，内容写「1. 学习 MCP 协议」
助手 > 已创建 notes/todo.txt 并写入内容。
```

对应工具：`read_file` / `write_file`（后者会自动创建 `notes/` 目录）。

### 4.4 执行命令

```
你 > 执行 git status，告诉我当前分支和工作区状态
助手 > 当前在 master 分支，工作区干净，没有未提交的改动。
```

对应工具：`run_shell`（默认 60 秒超时）。

### 4.5 联网搜索与抓取

```
你 > 联网搜索 nanobot 这个项目，概括它是做什么的
助手 > nanobot 是 HKUDS 开源的一个轻量级 AI Agent 框架……
```

Agent 的调用链为：`web_search` → 若需细节再 `web_fetch` → 汇总。

```
你 > 抓取 https://docs.python.org/3/library/asyncio.html，总结前三个概念
助手 > 依次是：事件循环（调度协程）、协程（async/await 定义的挂起点）、
        任务（被事件循环调度的协程包装）……
```

### 4.6 PDF 解析（含嵌套表格）

```
你 > 解析 samples/_synthetic_nested.pdf，把层级结构还原出来
助手 > 文档中的表格层级为：
        A
        └─ A-1
           └─ A-1-1
        └─ A-2
           └─ A-2-1
```

层级是靠**单元格 x 坐标聚类**推断出来的，输出用全角空格表示深度：

```
A                  ← 第 0 层
　A-1              ← 第 1 层
　　A-1-1          ← 第 2 层
　A-2
　　A-2-1
```

```
你 > 只解析 samples/_synthetic_big.pdf 的第 2 页
助手 > （返回第 2 页的内容，含表格与正文）
```

### 4.7 长期记忆（RAG）

```
你 > 记住：我叫小明，是一名后端工程师，喜欢喝美式咖啡
助手 > 好的，已记住。

（重启程序 —— 新进程）
你 > 我喜欢喝什么？
助手 > 你喜欢喝美式咖啡。
```

```
你 > 我是做什么工作的？
助手 > 你是后端工程师。
```

> 检索是**语义**匹配，不是关键词匹配，所以「喜欢喝什么」能命中「喜欢喝美式咖啡」。

### 4.8 会话管理（历史对话）

```
你 > /sessions
会话列表（最近使用在前）：
  1. 我不吃面包，我爱吃蛋糕   更新于 2026-09-27 15:04:12  ← 当前
  2. 默认会话                 更新于 2026-09-27 13:01:30

你 > /new 项目笔记
已新建并切换到会话：项目笔记（20260927-150812-x7k）
会话：项目笔记（20260927-150812-x7k）    本会话长期记忆：0 条

你 > /switch 2
已切换到会话：默认会话（default）
—— 最近 2 条对话 ——
你 > 你好
助手 > 你好！有什么可以帮你？
会话：默认会话（default）    本会话长期记忆：2 条

你 > /history 5
—— 最近 5 条对话 ——
...

你 > /delete 3 -y
已删除会话「项目笔记」：对话历史已清除，长期记忆清除 0 条。

你 > /help
可用命令：
  /sessions          列出所有会话
  /new [标题]        新建会话并切换过去
  /switch <编号>     切换到指定会话（并显示其近期对话）
  /delete <编号> -y  删除会话（含其长期记忆；必须带 -y 才真正执行）
  /history [N]       显示当前会话最近 N 条对话（默认 6）
  /help              显示本帮助
  exit / quit        退出程序
```

**会话隔离演示**（关键行为）：

```
（在「会话A」里）
你 > 我叫小明，喜欢喝美式咖啡，记住这一点
助手 > 已记住。

（/new 会话B 后）
你 > 我喜欢喝什么？
助手 > 咱们这个会话里您还没提过您喜欢喝什么。
        各会话的记忆是相互隔离的；如果您希望我去别的会话里查，
        请明确告诉我，我可以检索并标注来源。
```

**跨会话检索**（必须用户显式要求）：

```
你 > 查一下我在其他对话里提到过什么饮品
助手 > 我在其他会话中检索到 1 条相关记忆：
        [来源会话：20260927-130125-fb9] 用户喜欢喝美式咖啡，不加糖
```

### 4.9 邮件（MCP）

先一次性配置邮件服务（账号 + **收件人白名单**）：

```powershell
uvx mcp-email-server@latest ui
```

QQ 邮箱参数：`smtp.qq.com:465`（SSL）/ `imap.qq.com:993`（SSL），密码填 **16 位授权码**。

```
你 > 给 me@example.com 发一封测试邮件，主题「MCP 测试」，正文「这是一封通过 MCP 发送的测试邮件」
助手 > 邮件已发送，Message-Id: <...@qq.com>。

你 > 给 attacker@example.com 发一封邮件
助手 > 发送失败：该收件人不在允许列表中。（服务端拒绝）
```

> 白名单由**邮件服务端**强制校验 To/CC/BCC，模型无法绕过。

### 4.10 自定义 MCP 服务（教学）

`mcp_server_demo.py` 是一个最小 MCP 服务示例（2 个玩具工具 + 资源 + 提示模板）：

```powershell
python mcp_server_demo.py          # stdio（默认）
python mcp_server_demo.py http     # streamable-http
```

用项目自带的客户端验证：

```powershell
python -c "from mybot.mcp_client import connect_mcp_tools; t,c=connect_mcp_tools('python mcp_server_demo.py',['echo','add'],None,60); print([x.name for x in t]); print(t[0].execute(text='hi').content); print(t[1].execute(a=3,b=4).content); c.close()"
```

输出：

```
['echo', 'add']
hi
7
```

> 当前只支持**一个** MCP 服务；要接入自定义服务可临时把 `MCP_EMAIL_COMMAND` 指向它（属借用槽位）。

### 4.11 常见问题排查

| 现象 | 排查方式 |
| --- | --- |
| `[配置错误] 未找到 OPENAI_API_KEY` | 未建 `.env` 或没填 Key；从 `.env.example` 复制 |
| 启动提示"长期记忆已禁用" | 检查 `<项目根>/models/bge-small-zh-v1.5`，缺失则跑 `python setup_memory.py` |
| `MCP：已接入 0 个工具` | 看 `.mybot/mcp.log` 里的服务端报错；或 `MCP_EMAIL_ENABLED=false` 先关掉 |
| MCP 启动很慢 | `uvx` 每次解析依赖；把 `@latest` 换成固定版本；首次会下载包 |
| 检索到不相关的旧记忆 | 已知限制：无相似度阈值；可删会话重建 |
| PDF 表格层级不对 | 缩进步长与 `INDENT_CLUSTER_TOLERANCE`（3pt）不匹配，需按文档校准 |
| 网页抓不到正文 | 目标站反爬或 JS 渲染；换信息源 |

### 4.12 Web UI（Vue 3 + FastAPI）

前端位于 `ui/`，使用 Vue 3 + Vite + JavaScript；后端由 `mybot/api.py` 暴露 FastAPI 接口，`api_server.py` 是便捷启动入口。

**1. 安装 Python 依赖**

```powershell
pip install -r requirements.txt
```

**2. 启动 FastAPI**

```powershell
python api_server.py
# http://127.0.0.1:8000
# 接口文档：http://127.0.0.1:8000/docs
```

> `MCP_EMAIL_ENABLED` 默认关闭；需要邮件时再设为 `true`，并先在本地 MCP 配置中填写授权码。

**3. 开发模式启动前端**

```powershell
cd ui
npm install
npm run dev
# http://127.0.0.1:5173
```

Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。如果前后端分开部署，可以复制 `ui/.env.example` 为 `ui/.env.local`，设置 `VITE_API_BASE_URL`。

**4. 生产构建**

```powershell
cd ui
npm install
npm run build
cd ..
python api_server.py
```

仓库中已包含一份构建好的 `ui/dist`，克隆后直接启动 FastAPI 即可访问；修改前端源码后重新执行 `npm run build`。构建完成后 FastAPI 会自动托管 `ui/dist`，直接访问 `http://127.0.0.1:8000`。

**主要接口**

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/status` | 模型、记忆、工具与会话状态 |
| `GET` | `/api/sessions` | 会话列表 |
| `POST` | `/api/sessions` | 新建会话 |
| `PATCH` | `/api/sessions/{id}` | 修改会话标题 |
| `DELETE` | `/api/sessions/{id}` | 删除会话及其记忆 |
| `GET` | `/api/sessions/{id}/history` | 最近对话 |
| `POST` | `/api/chat` | 执行一次 Agent 对话 |

> 前端会把 Agent 的最终答复按 Markdown 渲染；工具调用过程仍保持静默。

### 4.13 上传 GitHub 前的安全检查

项目提供了独立检查脚本：

```powershell
python scripts\check_github_safety.py
```

检查内容包括：

- 项目根目录是否残留真实 `.env`
- 常见 API Key / Token / 私钥格式
- 疑似硬编码的密码、授权码
- 疑似手机号
- `samples/` 中是否出现非合成 PDF
- 项目内是否出现 SQLite 数据库文件

真实 LLM Key 推荐放在用户目录 `~/.mybot/.env`；邮件 MCP 授权码保存在其自己的本地配置库中，两者都不应进入项目仓库。详细说明见 `SECURITY.md`。

