# 安全与 GitHub 上传说明

## 密钥存放原则

本项目不会把真实密钥放进仓库。

推荐把本地配置放在用户目录：

```text
Windows: C:\Users\<你的用户名>\.mybot\.env
macOS/Linux: ~/.mybot/.env
```

也可以通过环境变量指定仓库外的配置文件：

```powershell
$env:MYBOT_ENV_FILE = "C:\Users\your-name\.mybot\.env"
```

程序读取优先级：

```text
MYBOT_ENV_FILE > 项目根目录 .env > ~/.mybot/.env
```

`.env.example` 只包含占位符，不包含真实密钥。

## 邮件 MCP 凭据

`mcp-email-server` 的 SMTP/IMAP 授权码保存在它自己的本地配置库中，不在本项目目录内：

```text
C:\Users\<你的用户名>\.config\mcp-email-server\managed.sqlite3
```

不要把 `.config` 目录、`managed.sqlite3` 或其中的授权码提交到 GitHub。

首次配置或重新配置请运行：

```powershell
uvx mcp-email-server@latest ui
```

真实授权码只在本地 UI 中填写，不要写进 `.env.example`、README、聊天记录或代码。

## 上传前检查

在项目根目录执行：

```powershell
python scripts\check_github_safety.py
```

脚本会检查：

- 项目根目录是否残留真实 `.env`
- 常见 API Key、GitHub Token、AWS Key、私钥格式
- 疑似硬编码的密码、Token、授权码
- 疑似手机号
- `samples/` 中是否出现非合成 PDF
- 项目内是否出现 SQLite 数据库文件

脚本返回 `[OK]` 后再上传。

如果之后初始化了 Git 仓库，再执行：

```powershell
git status --short
git status --ignored
```

确认 `.env`、`.mybot/`、`data/`、个人 PDF 和数据库文件都没有进入待提交列表。

## 本项目已做的处理

- LLM API Key 已移出项目目录，放到用户目录的 `~/.mybot/.env`。
- 邮件 MCP 数据库中的 SMTP/IMAP 授权码已删除，邮件账号已禁用。
- 真实简历、课程表等个人 PDF 已移出项目目录。
- `.env`、`.env.*`、`.mybot/`、`data/`、数据库文件、个人 PDF 已加入 `.gitignore`。
- 前端构建产物 `ui/dist` 和模型文件不包含密钥，可以正常提交。

## 运行安全

`read_file`、`write_file`、`run_shell` 没有沙箱隔离。FastAPI 默认只监听：

```text
127.0.0.1:8000
```

不要改成 `0.0.0.0` 后直接暴露到局域网或公网，除非先加入认证、权限控制和沙箱隔离。