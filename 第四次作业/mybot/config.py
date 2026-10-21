"""配置加载模块：从 .env 文件读取 LLM、Agent 与记忆模块的运行参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：仓库内资源都以它为基准，避免依赖当前工作目录或固定盘符。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 默认把运行数据放在项目内 data/，便于跨平台和仓库分发。
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
# 默认嵌入模型放在项目内 models/，随仓库分发或由 setup_memory.py 下载。
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "bge-small-zh-v1.5"
# 本地私密配置的推荐位置：放在用户目录，不进入项目仓库。
DEFAULT_USER_ENV = Path.home() / ".mybot" / ".env"


def resolve_env_file(env_file: str | Path | None = None) -> Path:
    """解析实际要加载的环境文件。

    优先级：
    1. 调用方显式传入的路径；
    2. 环境变量 MYBOT_ENV_FILE；
    3. 项目根目录 .env；
    4. 用户目录 ~/.mybot/.env。

    参数:
        env_file: 显式指定的 .env 路径。

    返回:
        选定路径；文件不存在时返回项目根目录 .env，由 dotenv 安静跳过。
    """
    if env_file:
        return Path(env_file).expanduser()

    configured = os.getenv("MYBOT_ENV_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()

    project_env = PROJECT_ROOT / ".env"
    if project_env.exists():
        return project_env
    if DEFAULT_USER_ENV.exists():
        return DEFAULT_USER_ENV
    return project_env


@dataclass
class Config:
    """Agent 运行配置。

    属性:
        api_key: OpenAI 兼容接口的 API Key。
        base_url: 接口基础地址（如 https://api.openai.com/v1）。
        model: 模型名（固定从 .env 读取，代码内不做模型切换）。
        max_steps: 单轮用户请求内 ReAct 循环的最大步数。
        temperature: 采样温度。
    """

    api_key: str
    base_url: str
    model: str
    max_steps: int = 10
    temperature: float = 0.0


def load_config(env_file: str | None = None) -> Config:
    """加载配置。

    参数:
        env_file: .env 文件路径；不传时按 MYBOT_ENV_FILE、项目根 .env、~/.mybot/.env 顺序查找。

    返回:
        Config 实例。

    异常:
        ValueError: 当缺少 OPENAI_API_KEY 时抛出。
    """
    # override=False：已存在的真实环境变量优先，便于临时覆盖 .env 的值
    load_dotenv(str(resolve_env_file(env_file)), override=False)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("未找到 OPENAI_API_KEY，请复制 .env.example 为 .env 并填写。")

    return Config(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
        # 模型名只从 .env 读取，无任何切换逻辑
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
        max_steps=int(os.getenv("MAX_STEPS", "10")),
        temperature=float(os.getenv("TEMPERATURE", "0.0")),
    )


@dataclass
class MemoryConfig:
    """记忆模块配置。

    属性:
        enabled: 是否启用记忆（False 时 Agent 退化为无记忆）。
        data_dir: 记忆数据根目录（默认项目内 data/）。
        sessions_dir: 会话短期记忆目录。
        chroma_dir: Chroma 向量库目录。
        model_dir: 嵌入模型目录（默认项目内 models/bge-small-zh-v1.5）。
        max_messages: 短期记忆消息条数阈值，超过即触发摘要压缩。
        keep_recent: 压缩后保留的最近消息条数。
        top_k: 每轮从长期记忆检索的条数。
    """

    enabled: bool = True
    data_dir: str = str(DEFAULT_DATA_DIR)
    sessions_dir: str = ""
    chroma_dir: str = ""
    model_dir: str = ""
    max_messages: int = 30
    keep_recent: int = 10
    top_k: int = 3


def load_memory_config(env_file: str | None = None) -> MemoryConfig:
    """加载记忆配置。

    参数:
        env_file: .env 文件路径；不传时按 MYBOT_ENV_FILE、项目根 .env、~/.mybot/.env 顺序查找。

    返回:
        MemoryConfig 实例；会话/向量库目录从 data_dir 推导，模型目录默认使用项目内 models/。
    """
    load_dotenv(str(resolve_env_file(env_file)), override=False)

    enabled = os.getenv("MEMORY_ENABLED", "true").strip().lower() not in {"false", "0", "no"}
    data_dir = os.getenv("MEMORY_DATA_DIR", "").strip() or str(DEFAULT_DATA_DIR)

    return MemoryConfig(
        enabled=enabled,
        data_dir=data_dir,
        sessions_dir=os.getenv("MEMORY_SESSIONS_DIR", "").strip()
        or str(Path(data_dir) / "sessions"),
        chroma_dir=os.getenv("MEMORY_CHROMA_DIR", "").strip()
        or str(Path(data_dir) / "chroma"),
        model_dir=os.getenv("MEMORY_MODEL_DIR", "").strip() or str(DEFAULT_MODEL_DIR),
        max_messages=int(os.getenv("MEMORY_MAX_MESSAGES", "30")),
        keep_recent=int(os.getenv("MEMORY_KEEP_RECENT", "10")),
        top_k=int(os.getenv("MEMORY_TOP_K", "3")),
    )


@dataclass
class McpConfig:
    """邮件 MCP 配置。

    属性:
        enabled: 是否启用；关闭后完全不启动 MCP 子进程。
        command_line: 启动 MCP 服务的完整命令行。
        tools: 允许暴露给模型的 MCP 工具名白名单（空表示全部允许）。
        account: 发件工具的 account_name 默认值；为空表示不注入。
        timeout: MCP 启动握手与单次调用的超时秒数。
    """

    enabled: bool = False
    command_line: str = "uvx mcp-email-server@latest stdio"
    tools: list[str] = field(default_factory=lambda: ["send_email"])
    account: str = ""
    timeout: float = 60.0


def load_mcp_config(env_file: str | None = None) -> McpConfig:
    """加载邮件 MCP 配置。

    参数:
        env_file: .env 文件路径；不传时按 MYBOT_ENV_FILE、项目根 .env、~/.mybot/.env 顺序查找。

    返回:
        McpConfig 实例。
    """
    load_dotenv(str(resolve_env_file(env_file)), override=False)

    enabled = os.getenv("MCP_EMAIL_ENABLED", "false").strip().lower() not in {"false", "0", "no"}
    tools = [
        item.strip()
        for item in os.getenv("MCP_EMAIL_TOOLS", "send_email").replace("，", ",").split(",")
        if item.strip()
    ]
    return McpConfig(
        enabled=enabled,
        command_line=os.getenv("MCP_EMAIL_COMMAND", "uvx mcp-email-server@latest stdio").strip(),
        tools=tools,
        account=os.getenv("MCP_EMAIL_ACCOUNT", "").strip(),
        timeout=float(os.getenv("MCP_EMAIL_TIMEOUT", "60")),
    )
