# MyBot · 本地个人 Agent 助手

一个运行在本地的个人 Agent 助手，提供两种使用方式：

- **CLI**：命令行对话、会话管理、工具调用
- **Web UI**：Vue 3 + FastAPI 的本地图形界面

核心能力包括：

- OpenAI 兼容 LLM 接入
- ReAct 工具调用循环
- 文件读写、Shell 命令、网页搜索与抓取
- PDF 正文与嵌套表格解析
- 短期记忆滑动窗口 + 溢出摘要压缩
- Chroma 长期记忆 + 本地 bge 向量模型
- 多会话隔离
- MCP 邮件工具扩展
- Markdown 消息渲染

> **安全提醒**：项目包含 `run_shell`、文件读写等本机工具，没有沙箱隔离。默认只适合个人本地使用，不要直接暴露到公网。

---

## 目录结构

```text
个人agent助手/
├── main.py                    CLI 启动入口
├── api_server.py              FastAPI 启动入口
├── mybot/
│   ├── agent.py               ReAct 循环
│   ├── api.py                 FastAPI 接口与运行时装配
│   ├── config.py              配置加载
│   ├── llm.py                 OpenAI 兼容客户端
│   ├── memory.py              短期记忆
│   ├── long_memory.py         Chroma 长期记忆
│   ├── sessions.py            会话索引
│   ├── mcp_client.py          MCP 同步桥接
│   └── tools/                 工具实现
├── ui/                        Vue 3 + Vite 前端
│   ├── src/
│   └── dist/                  已构建的生产资源
├── models/
│   └── bge-small-zh-v1.5/     本地向量模型
├── samples/                   合成 PDF 测试样本
├── scripts/
│   └── check_github_safety.py GitHub 上传前安全检查
├── .env.example               配置模板（仅占位符）
├── SECURITY.md                安全与上传说明
├── requirements.txt
└── setup_memory.py            下载本地嵌入模型
```

---

## 环境要求

- Python **3.10+**
- Windows、macOS 或 Linux
- 如果开发前端：Node.js **20.19+**，推荐 Node.js 22 LTS
- 如果使用邮件 MCP：需要安装 `uv` / `uvx`
- 一个大模型 API Key（OpenAI 兼容接口即可，例如 DeepSeek、OpenAI 或其他兼容服务）

仓库中已经包含：

- `ui/dist` 前端生产构建
- `models/bge-small-zh-v1.5` 本地向量模型

因此普通使用者只需要安装 Python 依赖即可启动 Web UI。

---

## 快速开始

### 1. 进入项目目录

```powershell
cd "<项目根目录>"
```

### 2. 创建并激活虚拟环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装 Python 依赖

```powershell
pip install -r requirements.txt
```

### 4. 创建本地配置文件

**不要编辑 `.env.example` 后提交真实密钥。**

推荐把真实配置放在用户目录的 `~/.mybot/.env`：

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

然后填写至少以下配置：

```dotenv
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

如果使用 DeepSeek，可以改成：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-flash
```

程序读取配置的顺序是：

```text
MYBOT_ENV_FILE
  > 项目根目录 .env
  > 用户目录 ~/.mybot/.env
```

如果配置文件不在默认位置，可以设置：

Windows PowerShell：

```powershell
$env:MYBOT_ENV_FILE = "D:\my-secrets\mybot.env"
```

macOS / Linux：

```bash
export MYBOT_ENV_FILE="$HOME/.mybot/.env"
```

### 5. 准备向量模型

仓库正常情况下已经包含：

```text
models/bge-small-zh-v1.5/
```

如果该目录不存在，运行：

```powershell
python setup_memory.py
```

脚本会从 ModelScope 下载模型到项目内 `models/bge-small-zh-v1.5`。

### 6. 启动 CLI

```powershell
python main.py
```

也可以使用：

```powershell
python -m mybot
```

常用命令：

| 命令 | 作用 |
| --- | --- |
| `/sessions` | 查看会话列表 |
| `/new [标题]` | 新建会话 |
| `/switch <编号>` | 切换会话 |
| `/delete <编号> -y` | 删除会话及其记忆 |
| `/history [N]` | 查看最近对话 |
| `/help` | 查看帮助 |
| `exit` / `quit` | 退出 |

### 7. 启动 Web UI

仓库已经包含 `ui/dist`，所以可以直接启动 FastAPI：

```powershell
python api_server.py
```

打开：

```text
http://127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

---

## 前端开发模式

如果需要修改 Vue 前端：

终端 1：

```powershell
python api_server.py
```

终端 2：

```powershell
cd ui
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

Vite 会把 `/api` 代理到：

```text
http://127.0.0.1:8000
```

修改源码后构建生产版本：

```powershell
cd ui
npm install
npm run build
```

然后重启：

```powershell
cd ..
python api_server.py
```

FastAPI 会自动托管 `ui/dist`。

---

## 配置说明

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 必填 | OpenAI 兼容接口密钥 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 接口地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 模型名称 |
| `MAX_STEPS` | `10` | 单轮最大 ReAct 步数 |
| `TEMPERATURE` | `0.0` | 采样温度 |
| `MYBOT_ENV_FILE` | 空 | 可选的仓库外配置文件路径 |
| `MEMORY_ENABLED` | `true` | 是否启用记忆模块 |
| `MEMORY_DATA_DIR` | `<项目根>/data` | 会话与 Chroma 数据目录 |
| `MEMORY_MAX_MESSAGES` | `30` | 短期记忆压缩阈值 |
| `MEMORY_KEEP_RECENT` | `10` | 压缩后保留的消息条数 |
| `MEMORY_TOP_K` | `3` | 每轮长期记忆检索条数 |
| `MEMORY_SESSIONS_DIR` | 空 | 留空则从 `MEMORY_DATA_DIR` 推导 |
| `MEMORY_CHROMA_DIR` | 空 | 留空则从 `MEMORY_DATA_DIR` 推导 |
| `MEMORY_MODEL_DIR` | `<项目根>/models/bge-small-zh-v1.5` | 向量模型目录 |
| `MCP_EMAIL_ENABLED` | `false` | 是否启用邮件 MCP |
| `MCP_EMAIL_COMMAND` | `uvx mcp-email-server@latest stdio` | MCP 启动命令 |
| `MCP_EMAIL_TOOLS` | `send_email` | 暴露给模型的 MCP 工具 |
| `MCP_EMAIL_ACCOUNT` | 空 | 邮件账号名称 |
| `MCP_EMAIL_TIMEOUT` | `60` | MCP 超时秒数 |
| `API_HOST` | `127.0.0.1` | FastAPI 监听地址 |
| `API_PORT` | `8000` | FastAPI 端口 |

### 数据目录

默认情况下，记忆数据位于：

```text
<项目根>/data/
├── sessions/      会话 JSONL 与 index.json
└── chroma/        Chroma 向量库
```

如果配置了：

```dotenv
MEMORY_DATA_DIR=D:\mybot-data
```

则使用该目录。

> `.mybot/`、`data/`、Chroma 数据库和会话 JSONL 都不应该提交到 Git。

---

## 记忆机制

### 短期记忆

- 每个会话一个 JSONL 文件
- 超过 `MEMORY_MAX_MESSAGES` 后触发压缩
- 保留最近 `MEMORY_KEEP_RECENT` 条附近的消息
- 较早消息由 LLM 压缩成摘要
- 压缩只在回合开始时进行，避免切断工具调用配对

### 长期记忆

- Chroma 持久化向量库
- 本地 `bge-small-zh-v1.5` 生成向量
- 模型主动调用 `memory_save` 写入
- 每轮根据用户输入检索当前会话的 top-k 记忆
- 不同会话默认物理隔离
- 跨会话检索需要用户明确要求

---

## 工具列表

| 工具 | 能力 |
| --- | --- |
| `read_file` | 读取本地文本文件 |
| `write_file` | 写入本地文件 |
| `run_shell` | 执行本机 Shell 命令 |
| `web_search` | Bing 网页搜索 |
| `web_fetch` | 抓取网页正文 |
| `pdf_parse` | 提取 PDF 正文和表格 |
| `memory_save` | 写入当前会话长期记忆 |
| `memory_search_other_sessions` | 跨会话检索 |
| `send_email` | 通过 MCP 发邮件（可选） |

> `run_shell`、`read_file`、`write_file` 没有沙箱隔离，请只在可信的本地环境使用。

---

## 邮件 MCP（可选）

邮件功能默认关闭：

```dotenv
MCP_EMAIL_ENABLED=false
```

需要发邮件时，先安装/确认 `uvx`，然后配置邮件服务：

```powershell
# 如果还没有 uvx
python -m pip install uv

uvx mcp-email-server@latest ui
```

在本地 MCP UI 中填写：

```text
账号名称：qq
邮箱地址：your-account@qq.com
SMTP：smtp.qq.com:465（SSL）
IMAP：imap.qq.com:993（SSL）
授权码：your-16-char-auth-code
```

配置完成后，把本地配置中的：

```dotenv
MCP_EMAIL_ENABLED=false
```

改成：

```dotenv
MCP_EMAIL_ENABLED=true
```

重启 API 或 CLI。

> **SMTP/IMAP 授权码不要写进 `.env.example`、README、代码或聊天记录。**  
> 邮件 MCP 的授权码保存在它自己的本地配置库中，不随项目提交。

---

## API 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/status` | 模型、记忆、工具和会话状态 |
| `GET` | `/api/sessions` | 会话列表 |
| `POST` | `/api/sessions` | 新建会话 |
| `PATCH` | `/api/sessions/{id}` | 修改会话标题 |
| `DELETE` | `/api/sessions/{id}` | 删除会话及其记忆 |
| `GET` | `/api/sessions/{id}/history` | 获取最近对话 |
| `POST` | `/api/chat` | 执行一次 Agent 对话 |

### 聊天请求示例

```json
{
  "session_id": "20260927-131158-iwa",
  "message": "帮我读取当前目录，介绍这个项目的模块"
}
```

返回示例：

```json
{
  "answer": "这个项目由以下模块组成……",
  "session": {
    "id": "20260927-131158-iwa",
    "title": "项目模块介绍",
    "memory_count": 3
  },
  "session_id": "20260927-131158-iwa"
}
```

---

## 常见问题

### 提示未找到 `OPENAI_API_KEY`

检查配置文件是否在以下位置之一：

```text
MYBOT_ENV_FILE
<项目根>/.env
~/.mybot/.env
```

并确认文件中有：

```dotenv
OPENAI_API_KEY=your-api-key
```

### 提示长期记忆已禁用

检查模型目录：

```text
models/bge-small-zh-v1.5/
```

如果不存在，运行：

```powershell
python setup_memory.py
```

### 启动时提示 `ModuleNotFoundError: fastapi`

重新安装依赖：

```powershell
pip install -r requirements.txt
```

### `uvicorn` 找不到

```powershell
python -m pip install "uvicorn[standard]"
```

### MCP 已接入 0 个工具

检查本地邮件 MCP 配置，或暂时关闭：

```dotenv
MCP_EMAIL_ENABLED=false
```

MCP 日志位于：

```text
.mybot/mcp.log
```

启用 MCP 后，`.mybot/` 会在需要时重新创建；普通会话数据位于 `MEMORY_DATA_DIR`。

### 端口 8000 被占用

修改本地配置：

```dotenv
API_PORT=8001
```

然后访问：

```text
http://127.0.0.1:8001
```

### 前端页面打不开或显示 API 提示

确认 `ui/dist/index.html` 存在；如果不存在，构建前端：

```powershell
cd ui
npm install
npm run build
```

然后重启 `python api_server.py`。

### PDF 解析不到内容

当前 `pdf_parse` 只支持带文本层的 PDF。扫描件/纯图片 PDF 需要先做 OCR。

---

## GitHub 上传前检查

项目提供了安全检查脚本：

```powershell
python scripts\check_github_safety.py
```

脚本会检查：

- 项目根目录是否残留真实 `.env`
- OpenAI / DeepSeek / GitHub / AWS / Google / Slack 等密钥格式
- 私钥文件
- 疑似硬编码密码、Token、授权码
- 疑似手机号
- `samples/` 中是否出现非合成 PDF
- 项目内是否出现 SQLite 数据库文件

当前项目已经做了以下处理：

- 真实 LLM Key 位于仓库外的 `~/.mybot/.env`
- SMTP/IMAP 授权码已从本地 MCP 数据库删除
- 邮件账号已禁用
- 个人简历、课程表等 PDF 已移出项目
- `.env`、`.mybot/`、`data/`、数据库文件和个人 PDF 已加入 `.gitignore`
- `ui/node_modules/` 和 `__pycache__/` 已清理
- `ui/dist` 和 `models/` 可以正常提交

上传前建议再执行：

```powershell
git status --short
git status --ignored
```

确认 `.env`、`.mybot/`、`data/`、个人 PDF 和数据库文件都不在待提交列表中。

更多安全说明见 [SECURITY.md](SECURITY.md)。

---

## 部署安全说明

当前项目默认只监听：

```text
127.0.0.1:8000
```

不要直接改成 `0.0.0.0` 暴露到公网。原因是 Agent 可以：

- 读写本机文件
- 执行 Shell 命令
- 发送邮件（配置 MCP 后）

如果确实要部署到服务器，至少需要：

1. 独立系统用户或容器隔离
2. 认证与权限控制
3. HTTPS
4. 防火墙限制访问来源
5. 对工具调用做白名单和沙箱限制

在没有完成以上措施前，建议只在本机使用。

---

## 前端技术栈

- Vue 3
- Vite 8
- JavaScript
- marked（Markdown 渲染）
- DOMPurify（HTML 消毒）

前端生产资源已提交到：

```text
ui/dist/
```

前端依赖目录 `ui/node_modules/` 不提交；开发时运行 `npm install` 即可。

---

## 相关文档

- [AGENT.md](AGENT.md)：完整功能与实现说明
- [SECURITY.md](SECURITY.md)：密钥管理与 GitHub 上传安全
- [ui/README.md](ui/README.md)：前端开发说明
- [samples/README.md](samples/README.md)：PDF 测试样本说明