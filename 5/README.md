# MyBot · 本地个人 Agent 助手

一个运行在本地的个人 Agent 助手，提供 **CLI** 和 **Web UI** 两种使用方式。

核心能力：

- OpenAI 兼容 LLM 接入
- ReAct 工具调用循环
- 短期记忆 + Chroma 长期记忆
- 多会话隔离
- 文件、Shell、网页、PDF 工具
- 抖音、B站、小红书、微博热点面板
- LLM 热点分级、评论、标签和灵感推荐
- 标准 SKILL.md 的搜索、安装、启停与上下文注入
- 官方 MCP Registry 搜索、安装、多服务管理与工具命名空间
- SSE 流式对话
- Agent 回复复制 / 重新生成
- 可选邮件 MCP

> 安全提醒：项目包含 `run_shell`、文件读写等本机工具，没有沙箱隔离，默认只适合个人本地使用。

> 当前状态：小红书热点数据源处于维护状态，面板显示“服务器正在维护”，不参与热点抓取和 LLM 分析；抖音、B站、微博和对话功能正常。

---

## 一、功能概览

| 能力 | 说明 |
| --- | --- |
| CLI | 命令行 REPL、工具调用、会话管理 |
| Web UI | Vue 3 界面、热点首页、对话页、状态面板、模型与 Skills 设置 |
| LLM | OpenAI 兼容 Chat Completions 接口 |
| ReAct | 多轮工具调用，最多 `MAX_STEPS` 步 |
| 文件工具 | 读取文件、写入文件 |
| Shell | 执行本机命令 |
| 网页工具 | Bing 搜索、网页正文抓取 |
| PDF | 提取正文与嵌套表格 |
| 短期记忆 | JSONL 持久化、滑动窗口、摘要压缩 |
| 长期记忆 | Chroma + 本地 `bge-small-zh-v1.5` |
| 会话 | 新建、切换、删除、查看历史 |
| 热点面板 | 四平台 Tab、AI 分级、评论、标签、灵感推荐 |
| 热点缓存 | SQLite 快照，默认 30 分钟有效 |
| Skills | 扫描 SKILL.md、搜索、启用/停用、GitHub 安装与自动匹配注入 |
| MCP Registry | 搜索官方 Registry、安装 stdio/Streamable HTTP 服务并注册命名空间工具 |
| 流式对话 | SSE 推送状态和文本 token |
| 消息操作 | 复制回复、重新生成最新回复 |
| 邮件 MCP | 可选发信工具 |

---

## 二、技术栈

### 后端

- Python 3.10+
- FastAPI
- Uvicorn
- OpenAI Python SDK
- Chroma
- sentence-transformers
- pdfplumber
- PyYAML
- MCP Python SDK

### 前端

- Vue 3
- Vite 8
- JavaScript
- marked
- DOMPurify

### 存储

- 短期记忆：JSONL
- 会话索引：JSON
- 长期记忆：Chroma
- 热点快照：SQLite
- Skills 索引：SQLite
- Skills 文件：`~/.mybot/skills`
- 邮件 MCP：由 MCP 服务自身管理

---

## 三、目录结构

```text
个人agent助手/
├── main.py                       CLI 启动入口
├── api_server.py                 FastAPI 启动入口
├── mybot/
│   ├── agent.py                  ReAct 循环、系统提示词
│   ├── api.py                    FastAPI 接口与运行时装配
│   ├── config.py                 LLM / 记忆 / 热点 / MCP 配置
│   ├── llm.py                    OpenAI 兼容客户端
│   ├── hotspots.py               60s API、LLM 热点分析、SQLite 缓存
│   ├── memory.py                 短期记忆
│   ├── long_memory.py            Chroma 长期记忆
│   ├── sessions.py               会话索引
│   ├── session_scope.py          ContextVar 当前会话
│   ├── skills.py                 Skills 扫描、索引、搜索与 GitHub 安装
│   ├── mcp_client.py             MCP 同步桥接
│   └── tools/
│       ├── base.py               Tool / ToolResult
│       ├── registry.py           工具注册表
│       ├── builtin.py            文件与 Shell
│       ├── web.py                搜索与网页抓取
│       ├── pdf_tools.py          PDF 解析
│       └── memory_tools.py       记忆工具
├── mcp_server_demo.py            MCP 服务端教学示例
├── ui/
│   ├── src/
│   │   ├── App.vue               页面导航、会话与热点联动
│   │   ├── api.js                后端 API 与 SSE 客户端
│   │   ├── markdown.js           Markdown 渲染与净化
│   │   ├── styles.css            低饱和浅色主题
│   │   └── components/
│   │       ├── ChatPanel.vue     对话、模型切换、复制与重新生成
│   │       ├── HotspotPanel.vue  四平台热点与灵感推荐
│   │       ├── SettingsPanel.vue 模型 API 与 Skills 管理
│   │       ├── SessionRail.vue   会话侧栏
│   │       └── TelemetryPanel.vue 运行状态面板
│   ├── public/favicon.png
│   ├── dist/                     已构建生产资源
│   ├── .env.example              前端开发环境变量模板
│   └── README.md                 前端开发说明
├── models/
│   ├── README.md
│   └── bge-small-zh-v1.5/        本地向量模型
├── samples/
│   ├── README.md
│   ├── _synthetic_big.pdf
│   └── _synthetic_nested.pdf
├── scripts/
│   └── check_github_safety.py
├── docs/
│   └── specs/
│       └── mybot-spec-v1.0.md    正式软件规格说明书
├── .env.example                  仅含占位符的配置模板
├── .gitignore
├── SECURITY.md
├── requirements.txt
└── setup_memory.py
```

实现分层：

- `llm.py` 负责 OpenAI 兼容请求与流式聚合。
- `agent.py` 负责 ReAct 循环、系统提示词和工具调用编排。
- `tools/` 只负责具体工具执行，统一返回 `ToolResult`。
- `api.py` 负责 FastAPI 接口、运行时装配和 SSE 推送。
- `ui/` 负责展示，不直接保存密钥或会话数据。
- `mcp_client.py` 通过后台线程把异步 MCP 调用桥接为同步工具。

---

## 四、环境要求

- Python **3.10+**
- Windows、macOS 或 Linux
- 开发前端时需要 Node.js **20.19+**
- 使用邮件 MCP 时需要 `uv` / `uvx`
- 一个 OpenAI 兼容 LLM API Key

仓库已包含：

- `ui/dist` 前端构建产物
- `models/bge-small-zh-v1.5` 本地向量模型

因此普通使用者只安装 Python 依赖即可启动 Web UI。

---

## 五、快速开始

### 1. 进入项目目录

```powershell
cd "<项目根目录>"
```

### 2. 创建虚拟环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 如果 PowerShell 提示找不到 `python`，可把命令中的 `python` 换成 `py -3`，或使用 Python 安装目录中的 `python.exe`。后续 `pip`、`python setup_memory.py`、`python api_server.py` 同理。

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```powershell
pip install -r requirements.txt
```

### 4. 配置环境变量

不要编辑 `.env.example` 后提交真实密钥。

推荐把真实配置放在用户目录：

```text
Windows: C:\Users\<用户名>\.mybot\.env
macOS/Linux: ~/.mybot/.env
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mybot" | Out-Null
Copy-Item .env.example "$HOME\.mybot\.env"
notepad "$HOME\.mybot\.env"
```

macOS / Linux：

```bash
mkdir -p ~/.mybot
cp .env.example ~/.mybot/.env
nano ~/.mybot/.env
```

至少填写：

```dotenv
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_MODEL_OPTIONS=gpt-4o-mini,gpt-4o,gpt-4.1-mini
```

桌面应用也支持先启动、再从页面右上角“配置 API”填写用户自己的 API Key；此时可以不在 `.env` 中保存真实 Key。

如果使用 DeepSeek：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-flash
```

配置读取顺序：

```text
MYBOT_ENV_FILE
  > 项目根目录 .env
  > 用户目录 ~/.mybot/.env
```

也可以显式指定配置路径：

```powershell
$env:MYBOT_ENV_FILE = "C:\path\to\your\.env"
```

### 5. 准备向量模型

仓库正常情况下已包含：

```text
models/bge-small-zh-v1.5/
```

如果模型缺失：

```powershell
python setup_memory.py
```

模型会下载到项目内 `models/bge-small-zh-v1.5`。

### 6. 启动 Web UI

```powershell
python api_server.py
```

打开：

```text
http://127.0.0.1:8000
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

### 7. 前端开发模式（可选）

仅在修改 `ui/src` 时需要。先保持 FastAPI 运行，再打开另一个终端：

```powershell
cd ui
npm install
npm run dev
```

开发地址：

```text
http://127.0.0.1:5173
```

Vite 默认把 `/api` 代理到 `http://127.0.0.1:8000`。前后端分开部署时，可复制 `ui/.env.example` 为 `ui/.env.local`，并设置 `VITE_API_BASE_URL`。

修改前端后必须重新构建，FastAPI 才会托管最新页面：

```powershell
npm run build
```

### 8. 启动 CLI

```powershell
python main.py
```

或：

```powershell
python -m mybot
```

---

## 六、配置说明

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 必填 | OpenAI 兼容接口密钥 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 接口地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 默认模型名称 |
| `OPENAI_MODEL_OPTIONS` | 空 | 自定义环境配置的模型下拉选项，逗号分隔，最多保留 3 个 |
| `MYBOT_LLM_CONFIG` | `~/.mybot/llm_config.json` | 用户服务商、模型和 API Key 的本地保存路径 |
| `MYBOT_ALLOW_REMOTE_LLM_SETTINGS` | `false` | 是否允许非本机请求修改 API 设置 |
| `MAX_STEPS` | `10` | 单轮最大 ReAct 步数 |
| `TEMPERATURE` | `0.0` | 采样温度 |
| `MYBOT_ENV_FILE` | 空 | 可选的仓库外配置文件路径 |
| `MEMORY_ENABLED` | `true` | 是否启用记忆 |
| `MEMORY_DATA_DIR` | `<项目根>/data` | 会话、Chroma 数据目录 |
| `MEMORY_MAX_MESSAGES` | `30` | 短期记忆压缩阈值 |
| `MEMORY_KEEP_RECENT` | `10` | 压缩后保留的近期消息数 |
| `MEMORY_TOP_K` | `3` | 长期记忆检索条数 |
| `MEMORY_SESSIONS_DIR` | 空 | 留空从 `MEMORY_DATA_DIR` 推导 |
| `MEMORY_CHROMA_DIR` | 空 | 留空从 `MEMORY_DATA_DIR` 推导 |
| `MEMORY_MODEL_DIR` | `<项目根>/models/bge-small-zh-v1.5` | 向量模型目录 |
| `HOTSPOT_ENABLED` | `true` | 是否启用热点面板 |
| `HOTSPOT_API_BASE` | `https://60s.viki.moe` | 60s API 地址 |
| `HOTSPOT_CACHE_TTL_MINUTES` | `30` | 热点快照缓存分钟数 |
| `HOTSPOT_MAX_ITEMS` | `8` | 每平台最多热点数 |
| `HOTSPOT_TIMEOUT` | `8` | 热点接口超时秒数 |
| `MYBOT_SKILLS_DIR` | `~/.mybot/skills` | 标准 Skills 安装目录 |
| `GITHUB_TOKEN` | 空 | 可选，提高 GitHub Skills 目录和下载限额 |
| `MCP_EMAIL_ENABLED` | `false` | 是否启用邮件 MCP |
| `MCP_EMAIL_COMMAND` | `uvx mcp-email-server@latest stdio` | MCP 启动命令 |
| `MCP_EMAIL_TOOLS` | `send_email` | 暴露给模型的 MCP 工具 |
| `MCP_EMAIL_ACCOUNT` | 空 | 邮件账号名称 |
| `MCP_EMAIL_TIMEOUT` | `60` | MCP 超时秒数 |
| `API_HOST` | `127.0.0.1` | FastAPI 监听地址 |
| `API_PORT` | `8000` | FastAPI 端口 |

界面选择主流服务商和模型后，后端自动确定 `OPENAI_BASE_URL`；当前环境配置仍可使用 `OPENAI_BASE_URL`、`OPENAI_MODEL` 和 `OPENAI_MODEL_OPTIONS`。界面保存的服务商、模型和 API Key 优先于环境变量。

---

## 七、使用方式

### CLI 命令

| 命令 | 作用 |
| --- | --- |
| `/sessions` | 查看会话列表 |
| `/new [标题]` | 新建并切换会话 |
| `/switch <编号>` | 切换会话 |
| `/delete <编号> -y` | 删除会话及其记忆 |
| `/history [N]` | 查看最近对话 |
| `/help` | 查看帮助 |
| `exit` / `quit` | 退出 |

### 功能演示

| 场景 | 输入示例 | 预期结果 |
| --- | --- | --- |
| 基础问答 | `用一句话解释 ReAct` | Agent 直接回答，不调用工具 |
| 文件读取 | `读取 requirements.txt，概括项目依赖` | 调用 `read_file` 后总结 |
| 文件写入 | `创建 notes/todo.txt，写入“学习 MCP”` | 自动创建目录并调用 `write_file` |
| 长期记忆 | `记住：我喜欢美式咖啡` | 模型判断有价值后调用 `memory_save` |
| 会话隔离 | `/new 项目笔记` 后询问前一话题 | 默认不跨会话引用，并说明记忆隔离 |
| 显式跨会话 | `查一下我在其他对话里提到过什么饮品` | 调用跨会话检索并标注来源会话 |
| PDF 解析 | `解析 samples/_synthetic_nested.pdf 的第 1 页` | 返回正文与保留层级的 Markdown 表格 |
| 热点讨论 | 在热点卡片点击“讨论” | 新建会话、切换到对话并自动流式回答 |

### Web UI

页面顶部有：

- `热点`
- `对话`

首页默认进入热点视图。

热点视图：

- 抖音、B站、小红书、微博四个 Tab
- 每条热点展示标题、AI 分级、评论、标签
- 分级使用高 / 中 / 低三种颜色
- 面板底部展示灵感推荐
- 小红书显示“服务器正在维护”
- 点击“讨论”会：
  1. 新建 `热点讨论：<标题>` 会话
  2. 自动切换到对话视图
  3. 自动发送热点提示词
  4. 直接开始 SSE 流式生成

对话视图：

- 右上角“配置 API”按钮打开设置弹窗
- 设置弹窗按服务商分组展示主流模型：OpenAI、DeepSeek、通义千问、智谱 GLM、Moonshot Kimi、硅基流动、OpenRouter、Ollama
- 用户只选择模型并填写 API Key，后端根据服务商预设自动写入正确的 Base URL
- 设置弹窗只读展示自动匹配的 Base URL，用户无需手动填写
- 服务商、模型和 API Key 保存于本机 `~/.mybot/llm_config.json`，接口响应不会返回明文
- 对话输入框下方保留模型下拉菜单，可在当前服务商的最多 3 个模型间快速切换
- 当前选择会保存在浏览器本地，并在后续对话请求中携带
- 设置弹窗包含“模型 API”和“Skills”两个标签页
- Skills 页支持本地搜索、启用/停用、详情预览、OpenAI/Anthropic 目录浏览和 GitHub 手动安装
- Agent 根据问题匹配最多 2 个已启用 Skill，并将 SKILL.md 内容临时注入 system 上下文
- Agent 回复逐 token 显示
- Agent 头像在左侧，用户头像在右侧显示 `You`
- Agent 回复下方有“复制”和“重新生成”
- 重新生成只对最新一条 Agent 回复启用
- Markdown 表格、代码块、列表正常渲染

---

## 八、业务流

### 启动流程

```text
main.py / api_server.py
        │
        ▼
load_config()
        │
        ├─ 读取外部 .env
        ├─ 初始化 LLMClient
        ├─ 初始化短期记忆
        ├─ 初始化 Chroma 长期记忆
        ├─ 初始化热点服务
        ├─ 扫描并加载 Skills 索引
        ├─ 加载会话索引
        ├─ 注册工具
        ├─ 可选连接 MCP
        └─ 进入 CLI / FastAPI
```

### 单轮对话流程

```text
用户输入
   │
   ▼
Agent.run()
   │
   ├─ 设置当前 session
   ├─ 短期记忆压缩检查
   ├─ 长期记忆检索
   ├─ 热点面板上下文注入
    ├─ 匹配并注入已启用 Skills
   ├─ 组装 messages + tools
   │
   ▼
LLM 流式请求
   │
   ├─ 无 tool_calls → 逐 token 输出最终回答
   │
   └─ 有 tool_calls
        ├─ 执行工具
        ├─ 回填 tool 消息
        └─ 继续下一轮
```

### SSE 流式协议

```text
POST /api/chat/stream

data: {"type":"status","message":"正在思考…"}

data: {"type":"token","content":"你"}

data: {"type":"token","content":"好"}

data: {"type":"done","answer":"你好","session":{...},"session_id":"..."}
```

工具调用时会发送：

```json
{"type":"status","message":"正在调用工具：read_file"}
```

前端使用 `fetch` 读取 `ReadableStream`，按 `\n\n` 分割 SSE 事件。

### 工具清单

| 工具 | 作用 | 边界 |
| --- | --- | --- |
| `read_file` | 读取本地文本文件 | 输出超过 20,000 字符会截断 |
| `write_file` | 写入本地文件并自动创建目录 | 无路径沙箱 |
| `run_shell` | 执行本机 Shell 命令 | 默认超时 60 秒，输出截断 20,000 字符 |
| `web_search` | 解析 Bing 搜索结果 | 依赖页面结构，需要网络 |
| `web_fetch` | 抓取网页正文 | 不执行 JavaScript |
| `pdf_parse` | 解析 PDF 正文和表格层级 | 不支持扫描件 OCR |
| `memory_save` | 写入当前会话长期记忆 | 内容不能为空 |
| `memory_search_other_sessions` | 检索其他会话的长期记忆 | 仅用户明确要求时使用，并标注来源 |
| `send_email` | 通过邮件 MCP 发信 | 可选，受 MCP 服务端收件人白名单约束 |

### 实现边界

- 热点和 Skills 上下文通过 `Agent.run(..., extra_system=...)` 临时注入，不修改原有 ReAct 核心循环。
- Skills 只提供流程知识，不会因安装而自动获得脚本执行权限。
- 当前会话 ID 通过 `ContextVar` 传递，避免模型自行填写会话参数。
- 长期记忆默认只检索当前会话；跨会话检索必须由用户显式触发。
- 热点分析结果先写入 SQLite 快照，对话读取已有快照，不在每轮聊天时重新生成。
- 流式接口通过回调推送 `status`、`token`、`done` 和 `error` 事件，最终回答仍按 Markdown 渲染。
- 前端生产构建由 FastAPI 托管；开发模式下由 Vite 代理 `/api` 请求。

---

## 九、记忆架构

### 短期记忆

位置：

```text
<MEMORY_DATA_DIR>/sessions/<session_id>.jsonl
```

结构：

```text
基础 system prompt
+ 历史摘要
+ 最近原始消息窗口
```

默认策略：

```text
MEMORY_MAX_MESSAGES=30
MEMORY_KEEP_RECENT=10
```

流程：

```text
消息条数 > 30
    │
    ▼
把较早消息交给 LLM 摘要
    │
    ▼
摘要 + 最近消息写回 JSONL
```

切点会尽量对齐到 `user` 消息，避免切断：

```text
assistant(tool_calls)
    → tool 结果
```

压缩只在回合开始时执行，不在 ReAct 循环中途执行。

### 长期记忆

使用：

```text
Chroma 持久化向量库
+ bge-small-zh-v1.5
```

写入由模型调用：

```text
memory_save
```

默认检索：

```text
top_k=3
where={"session_id": 当前会话}
```

长期记忆按会话物理隔离。

跨会话检索工具：

```text
memory_search_other_sessions
```

只有在用户明确要求“查一下我在其他对话里说过什么”时才使用，并标注来源会话。

### 会话

会话索引：

```text
<MEMORY_DATA_DIR>/sessions/index.json
```

保存：

- 会话 ID
- 标题
- 创建时间
- 更新时间

删除会话会同时删除：

- 短期记忆 JSONL
- 长期记忆
- 会话索引记录

---

## 十、热点面板实现

### 数据源

基础地址：

```text
https://60s.viki.moe
```

当前平台策略：

| 平台 | 策略 |
| --- | --- |
| 抖音 | 60s API |
| B站 | 60s API 失败时使用 B站公开接口兜底 |
| 微博 | 60s API 失败时使用微博公开接口兜底 |
| 小红书 | 固定显示“服务器正在维护”，不抓取、不分析 |

小红书当前不参与：

- 热点抓取
- AI 分级
- 评论生成
- 标签生成
- 小红书平台推荐

### LLM 分析

后端将非维护平台热点作为输入，要求 LLM 严格输出 JSON：

```json
{
  "items": [
    {
      "key": "douyin-1",
      "level": "高",
      "comment": "1-2 句评论",
      "tags": ["标签1", "标签2"]
    }
  ],
  "recommendations": [
    {
      "title": "灵感标题",
      "reason": "一句话理由",
      "platform": "抖音",
      "format": "短视频"
    }
  ]
}
```

要求包括：

- JSON 以外不能有文字
- 分级只能是高 / 中 / 低
- 不编造新闻细节
- 小红书处于维护状态，不生成小红书分析或推荐
- 每个热点有 1-3 个标签
- 生成 6 条灵感推荐

如果 LLM 输出不合法，会使用规则兜底，保证面板仍可展示。

### 缓存

热点快照存入：

```text
<MEMORY_DATA_DIR>/hotspots.sqlite3
```

默认缓存 30 分钟。

不会在每次对话时重新抓取或调用 LLM：

- `GET /api/hotspots` 优先读取未过期缓存
- 缓存超过 TTL 时自动重新抓取并生成分析
- 过期刷新失败时返回旧快照，并标记 `stale=true` 和 `refresh_error`
- `POST /api/hotspots/refresh` 强制刷新
- 某个平台失败时保留该平台上次成功缓存

---

## 十一、API 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/status` | 模型、记忆、工具、热点状态 |
| `GET` | `/api/settings/llm` | 读取脱敏 Key、当前模型和服务商预设列表 |
| `POST` | `/api/settings/llm/test` | 按服务商和模型测试连接 |
| `PUT` | `/api/settings/llm` | 保存服务商、模型和 API Key 并立即应用 |
| `GET` | `/api/sessions` | 会话列表 |
| `POST` | `/api/sessions` | 新建会话 |
| `PATCH` | `/api/sessions/{id}` | 修改会话标题 |
| `DELETE` | `/api/sessions/{id}` | 删除会话及记忆 |
| `GET` | `/api/sessions/{id}/history` | 最近对话 |
| `POST` | `/api/chat` | 非流式聊天 |
| `POST` | `/api/chat/stream` | SSE 流式聊天 |
| `GET` | `/api/hotspots` | 热点缓存 |
| `POST` | `/api/hotspots/refresh` | 强制刷新热点 |
| `GET` | `/api/skills` | 搜索本地已安装 Skills |
| `POST` | `/api/skills/refresh` | 重新扫描 Skills 目录 |
| `GET` | `/api/skills/catalog` | 浏览 OpenAI/Anthropic Skills 目录 |
| `GET` | `/api/skills/{id}` | 查看 Skill 详情与 SKILL.md |
| `POST` | `/api/skills/install` | 从 GitHub 安装 Skill |
| `POST` | `/api/skills/{id}/enable` | 启用 Skill |
| `POST` | `/api/skills/{id}/disable` | 停用 Skill |
| `DELETE` | `/api/skills/{id}` | 删除 Skill |
| `GET` | `/api/mcp/registry/search` | 搜索官方 MCP Registry |
| `GET` | `/api/mcp/registry/detail` | 读取 MCP 服务详情 |
| `GET` | `/api/mcp/servers` | 列出已安装 MCP 与连接状态 |
| `POST` | `/api/mcp/servers/install` | 安装并连接 MCP 服务 |
| `POST` | `/api/mcp/servers/{id}/enable` | 启用 MCP 服务 |
| `POST` | `/api/mcp/servers/{id}/disable` | 停用 MCP 服务 |
| `POST` | `/api/mcp/servers/{id}/restart` | 重启 MCP 服务 |
| `GET` | `/api/mcp/servers/{id}/tools` | 查看 MCP 命名空间工具 |
| `DELETE` | `/api/mcp/servers/{id}` | 删除 MCP 服务配置 |

聊天请求：

```json
{
  "session_id": "20260927-131158-iwa",
  "message": "读取 requirements.txt，概括项目依赖",
  "model": "gpt-4o-mini"
}
```

---

## 十二、测试方式

### 1. 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### 2. 查看状态

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/status
```

重点检查：

```text
status = ok
memory_enabled = true
long_term_enabled = true
hotspots_enabled = true
```

### 3. 测试热点接口

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/hotspots
```

强制刷新：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/hotspots/refresh
```

预期：

- 抖音有数据
- B站有数据或显示平台错误
- 小红书 `maintenance = true`，显示“服务器正在维护”
- 微博有数据
- `recommendations` 有内容

### 4. 测试 SSE 流式接口

使用 `curl.exe`：

```powershell
curl.exe -N -X POST http://127.0.0.1:8000/api/chat/stream `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"用一句话介绍你自己\"}"
```

应依次看到：

```text
status
token
token
...
done
```

### 5. 测试复制和重新生成

在 Web UI 对话页：

- 点击 Agent 回复下方“复制”
- 检查剪贴板内容
- 点击最新 Agent 回复下方“重新生成”
- 应该删除旧回复并重新流式生成

### 6. 测试热点讨论联动

1. 打开热点首页
2. 点击热点条目的“讨论”
3. 应该自动新建会话并自动发送提示词
4. 对话应流式返回
5. 回答应引用热点平台和标题

### 7. 测试 PDF

```text
解析 samples/_synthetic_nested.pdf 的第 1 页
```

应输出正文和带缩进层级的 Markdown 表格。

### 8. 上传前检查

```powershell
python scripts\check_github_safety.py
```

---

## 十三、安全说明

### 密钥存放

真实 LLM Key 应放在仓库外。可以通过页面“配置 API”保存到：

```text
C:\Users\<用户名>\.mybot\llm_config.json
```

也可以继续使用原来的外部 `.env`：

```text
C:\Users\<用户名>\.mybot\.env
```

或：

```text
MYBOT_ENV_FILE=<仓库外路径>
```

项目内 `.env.example` 只允许占位符。

### 邮件 MCP

邮件 MCP 默认关闭：

```dotenv
MCP_EMAIL_ENABLED=false
```

SMTP/IMAP 授权码不要写入 `.env.example`、代码、README 或聊天记录。

配置方式：

```powershell
python -m pip install uv
uvx mcp-email-server@latest ui
```

### Skills 安全

Skills 内容来自外部输入，安装前应查看 `SKILL.md`。当前实现只注入文本流程，不自动执行 Skill 目录中的脚本；安装文件限制为最多 500 个、解压后最多 50 MB，并拒绝路径穿越和符号链接。

### MCP 安全

MCP Registry 中的条目是外部代码或远程服务。安装前必须确认来源、包名、版本、启动命令和所需凭据；管理接口默认只允许本机访问。API 响应会对 `env` 和 `headers` 做脱敏，不返回明文 Token。MCP 工具以 `mcp__服务__工具` 注册，可逐步收紧工具白名单。

### 工具安全

`read_file`、`write_file`、`run_shell` 没有沙箱隔离。

FastAPI 默认只监听：

```text
127.0.0.1:8000
```

不要直接改成 `0.0.0.0` 暴露到公网。如果部署到服务器，至少需要：

1. 独立用户或容器隔离
2. 认证和权限控制
3. HTTPS
4. 入站防火墙
5. 工具白名单和沙箱

更多说明见 [SECURITY.md](SECURITY.md)。

---

## 十四、常见问题

| 问题 | 处理 |
| --- | --- |
| PowerShell 找不到 `python` | 使用 `py -3`，或填写 Python 安装目录中 `python.exe` 的绝对路径 |
| 未找到 `OPENAI_API_KEY` | 检查 `~/.mybot/.env` 或 `MYBOT_ENV_FILE` |
| 长期记忆已禁用 | 检查 `models/bge-small-zh-v1.5`，缺失时运行 `python setup_memory.py` |
| `ModuleNotFoundError: fastapi` | 运行 `pip install -r requirements.txt` |
| 端口 8000 被占用 | 修改 `API_PORT` |
| 前端页面打不开 | 检查 `ui/dist/index.html`，必要时运行 `npm run build` |
| 页面仍显示旧资源 | `Ctrl + F5` 强制刷新，或关闭标签页重开 |
| 小红书显示维护 | 当前设计如此，不参与热点抓取和分析 |
| B站显示 500 | 系统会尝试 B站公开接口兜底；仍失败时点击刷新 |
| 微博显示 429 | 60s API 限流，系统会尝试微博公开接口兜底 |
| 热点接口暂时不可用 | 点击“刷新”，或等待 60s API 恢复 |
| PDF 无文本 | 可能是扫描件，需要 OCR，当前工具不支持 |
| MCP 工具为 0 | 检查本地邮件 MCP 配置，或将 `MCP_EMAIL_ENABLED=false` |

---

## 十五、已知限制

- 无沙箱，`run_shell` 等工具可直接操作本机
- 不支持扫描件 PDF OCR
- 长期记忆没有相似度阈值，top-k 可能召回不相关记忆
- 长期记忆写入依赖模型主动调用 `memory_save`
- 摘要压缩依赖 LLM，压缩失败时跳过
- 会话 JSONL 压缩时需要整体重写文件
- 传统邮件 MCP 仍使用单槽位配置；MCP Registry 已支持多个服务
- 网页搜索依赖 Bing HTML 结构，网页抓取不执行 JavaScript
- 小红书当前处于维护状态
- 热点接口来自公共 API，可能限流或暂时不可用

---

## 十六、相关文档

- [docs/specs/mybot-spec-v1.0.md](docs/specs/mybot-spec-v1.0.md)：正式软件规格说明书与需求追踪基线
- [SECURITY.md](SECURITY.md)：密钥管理和 GitHub 上传安全
- [ui/README.md](ui/README.md)：前端开发说明
- [samples/README.md](samples/README.md)：PDF 测试样本说明
- [models/README.md](models/README.md)：本地嵌入模型说明