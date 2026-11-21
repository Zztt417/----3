"""FastAPI 接口：把本地 Agent 暴露给 Vue 前端。

启动方式：
    python api_server.py
或：
    python -m mybot.api

开发时前端由 Vite 启动，`/api` 通过代理转发到本服务；
生产构建后，FastAPI 会自动托管 `ui/dist`。
"""

from __future__ import annotations

import json
import os
import threading
import time
from queue import Queue
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .agent import SYSTEM_PROMPT, Agent
from .config import load_config, load_hotspot_config, load_mcp_config, load_memory_config, resolve_env_file
from .hotspots import HotspotService
from .llm import LLMClient
from .llm_providers import detect_provider_id, get_provider, provider_payloads
from .llm_settings import get_llm_config_path, load_stored_llm_settings, save_stored_llm_settings, validate_llm_api_key
from .long_memory import LongTermMemory, create_long_term_memory
from .mcp_client import connect_mcp_tools
from .mcp_manager import MCPManager, MCPManagerError
from .mcp_registry import MCPRegistryClient, MCPRegistryError
from .memory import Session, ShortTermMemory
from .session_scope import DEFAULT_SESSION_ID
from .sessions import SessionIndex, SessionMeta
from .skills import SkillError, SkillRegistry
from .tools import create_default_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIST = PROJECT_ROOT / "ui" / "dist"
MAX_HISTORY = 500


class ChatRequest(BaseModel):
    """一次聊天请求。"""

    session_id: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=20_000)
    model: str | None = Field(default=None, max_length=200)


class SessionCreateRequest(BaseModel):
    """新建会话请求。"""

    title: str = Field(default="", max_length=120)


class SessionRenameRequest(BaseModel):
    """重命名会话请求。"""

    title: str = Field(min_length=1, max_length=120)


class LLMSettingsUpdateRequest(BaseModel):
    """保存用户模型服务配置的请求。"""

    provider_id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)


class LLMSettingsTestRequest(BaseModel):
    """测试用户模型服务配置的请求。"""

    provider_id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)


class SkillInstallRequest(BaseModel):
    """从 GitHub 安装标准 Skill 的请求。"""

    repo: str = Field(min_length=3, max_length=200)
    path: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="main", min_length=1, max_length=120)


class MCPInstallRequest(BaseModel):
    """从官方 MCP Registry 安装服务的请求。"""

    name: str = Field(min_length=3, max_length=300)
    version: str = Field(default="latest", max_length=120)
    transport: str = Field(default="streamable-http", max_length=40)
    package_index: int = Field(default=0, ge=0, le=20)
    remote_index: int = Field(default=0, ge=0, le=20)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


@dataclass
class AgentRuntime:
    """API 进程内共享的 Agent 运行时。"""

    agent: Agent | None = None
    short_term: ShortTermMemory | None = None
    long_term: LongTermMemory | None = None
    sessions: SessionIndex | None = None
    hotspot_service: HotspotService | None = None
    skill_registry: SkillRegistry | None = None
    mcp_client: Any | None = None
    mcp_manager: MCPManager | None = None
    mcp_registry_client: MCPRegistryClient | None = None
    mcp_tools: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    provider_id: str = "custom"
    model: str = ""
    model_options: list[str] = field(default_factory=list)
    base_url: str = ""
    temperature: float = 0.0
    max_steps: int = 10
    memory_enabled: bool = False
    long_term_enabled: bool = False
    hotspots_enabled: bool = False
    hotspot_ttl_minutes: int = 30
    data_dir: str = ""
    model_dir: str = ""
    sessions_dir: str = ""
    chroma_dir: str = ""
    short_term_max: int = 30
    short_term_keep: int = 10
    default_session_id: str = DEFAULT_SESSION_ID
    startup_error: str = ""
    warnings: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def close(self) -> None:
        """关闭 MCP 子进程等外部资源。"""
        if self.mcp_manager is not None:
            try:
                self.mcp_manager.close_all()
            except Exception:
                pass
            self.mcp_manager = None
        if self.mcp_client is not None:
            try:
                self.mcp_client.close()
            except Exception:
                pass
            self.mcp_client = None


def _ensure_session(index: SessionIndex, sessions_dir: str) -> str:
    """确保至少存在一个会话，并返回默认会话 ID。

    参数:
        index: 会话索引。
        sessions_dir: 会话数据目录。

    返回:
        启动时默认选中的会话 ID。
    """
    if index.count == 0:
        legacy_history = Path(sessions_dir) / f"{DEFAULT_SESSION_ID}.jsonl"
        adopted = index.adopt_legacy(legacy_history.exists())
        if adopted:
            return adopted
        return index.create("")
    return index.list()[0].session_id


def build_runtime() -> AgentRuntime:
    """按现有 CLI 模块组装 Agent 运行时。

    配置或 LLM 初始化失败时不会抛异常，而是把错误记录到
    ``startup_error``，由 /api/status 和 /api/chat 返回给前端。

    返回:
        AgentRuntime 实例。
    """
    runtime = AgentRuntime()

    try:
        config = load_config()
    except Exception as exc:
        runtime.startup_error = f"配置加载失败：{exc}"
        return runtime

    runtime.provider_id = config.provider_id
    runtime.model = config.model
    runtime.model_options = config.model_options
    runtime.base_url = config.base_url
    runtime.temperature = config.temperature
    runtime.max_steps = config.max_steps

    try:
        llm = LLMClient(config.api_key, config.base_url, config.model, config.temperature)
    except Exception as exc:
        runtime.startup_error = f"LLM 初始化失败：{exc}"
        return runtime

    memory_config = load_memory_config()
    runtime.memory_enabled = memory_config.enabled
    runtime.data_dir = memory_config.data_dir
    runtime.model_dir = memory_config.model_dir
    runtime.sessions_dir = memory_config.sessions_dir
    runtime.chroma_dir = memory_config.chroma_dir
    runtime.short_term_max = memory_config.max_messages
    runtime.short_term_keep = memory_config.keep_recent
    try:
        runtime.skill_registry = SkillRegistry(memory_config.data_dir)
    except Exception as exc:
        runtime.warnings.append(f"Skills 初始化失败，已降级：{type(exc).__name__}: {exc}")

    hotspot_config = load_hotspot_config()
    runtime.hotspots_enabled = hotspot_config.enabled
    runtime.hotspot_ttl_minutes = hotspot_config.ttl_minutes
    if hotspot_config.enabled:
        try:
            runtime.hotspot_service = HotspotService(
                llm=llm,
                db_path=Path(memory_config.data_dir) / "hotspots.sqlite3",
                api_base=hotspot_config.api_base,
                ttl_minutes=hotspot_config.ttl_minutes,
                max_items=hotspot_config.max_items,
                timeout=hotspot_config.timeout,
            )
        except Exception as exc:
            runtime.warnings.append(
                f"热点面板初始化失败，已降级：{type(exc).__name__}: {exc}"
            )

    if memory_config.enabled:
        try:
            runtime.short_term = ShortTermMemory(
                system_prompt=SYSTEM_PROMPT.format(cwd=os.getcwd()),
                sessions_dir=memory_config.sessions_dir,
                llm=llm,
                max_messages=memory_config.max_messages,
                keep_recent=memory_config.keep_recent,
            )
            runtime.long_term = create_long_term_memory(
                memory_config.chroma_dir, memory_config.model_dir, memory_config.top_k
            )
            runtime.sessions = SessionIndex(memory_config.sessions_dir)
            runtime.default_session_id = _ensure_session(
                runtime.sessions, memory_config.sessions_dir
            )
            if runtime.long_term is not None:
                backfilled = runtime.long_term.assign_orphans(runtime.default_session_id)
                if backfilled:
                    runtime.warnings.append(
                        f"已把 {backfilled} 条缺少会话归属的旧记忆归入当前会话。"
                    )
        except Exception as exc:
            runtime.warnings.append(f"记忆模块初始化失败，已降级：{type(exc).__name__}: {exc}")
            runtime.short_term = None
            runtime.long_term = None
            runtime.sessions = None
            runtime.default_session_id = DEFAULT_SESSION_ID

    runtime.long_term_enabled = runtime.long_term is not None

    try:
        registry = create_default_registry(runtime.long_term)
        runtime.agent = Agent(
            llm,
            registry,
            max_steps=config.max_steps,
            memory=runtime.short_term,
            long_term=runtime.long_term,
        )
        runtime.tool_names = registry.tool_names
    except Exception as exc:
        runtime.startup_error = f"Agent 初始化失败：{exc}"
        return runtime

    try:
        runtime.mcp_manager = MCPManager(registry=registry)
        runtime.mcp_manager.start_enabled()
        runtime.tool_names = registry.tool_names
    except Exception as exc:
        runtime.warnings.append(f"MCP Registry 服务初始化失败：{type(exc).__name__}: {exc}")

    mcp_config = load_mcp_config()
    if mcp_config.enabled:
        field_defaults: dict[str, Any] | None = (
            {"account_name": mcp_config.account} if mcp_config.account else None
        )
        mcp_tools, mcp_client = connect_mcp_tools(
            mcp_config.command_line,
            mcp_config.tools,
            field_defaults,
            mcp_config.timeout,
        )
        for tool in mcp_tools:
            registry.register(tool)
        runtime.mcp_client = mcp_client
        runtime.mcp_tools = [str(tool.name) for tool in mcp_tools]
        runtime.tool_names = registry.tool_names

    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时组装 Agent，退出时回收 MCP。"""
    try:
        app.state.runtime = build_runtime()
    except Exception as exc:
        app.state.runtime = AgentRuntime(
            startup_error=f"运行时初始化失败：{type(exc).__name__}: {exc}"
        )
    try:
        yield
    finally:
        runtime = getattr(app.state, "runtime", None)
        if runtime is not None:
            runtime.close()


app = FastAPI(
    title="MyBot API",
    version="0.2.0",
    description="本地个人 Agent 的 HTTP 接口，供 Vue 前端调用。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _env_flag(name: str, default: bool = False) -> bool:
    """读取布尔环境变量。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _settings_request_allowed(request: Request) -> bool:
    """判断当前请求是否允许修改 LLM API 配置。

    默认只允许桌面端/开发机的本机请求；部署到公网后必须显式开启并自行增加鉴权。
    """
    if _env_flag("MYBOT_ALLOW_REMOTE_LLM_SETTINGS", False):
        return True
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"} or host.startswith("127.")


def _require_settings_access(request: Request) -> None:
    """拒绝非本机来源的 API 配置修改请求。"""
    if not _settings_request_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="API 设置默认仅允许本机访问；如需远程配置，请先增加登录鉴权并设置 MYBOT_ALLOW_REMOTE_LLM_SETTINGS=true。",
        )


def _mask_api_key(value: str) -> str:
    """返回可展示的脱敏 API Key。"""
    value = (value or "").strip()
    if not value:
        return ""
    if value.lower() in {"local", "not-needed", "ollama"}:
        return value
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-4:]}"


def _providers_for_runtime(runtime: AgentRuntime) -> list[dict[str, Any]]:
    """返回服务商菜单，并保留当前配置中可能存在的自定义模型。"""
    providers = provider_payloads()
    current_id = runtime.provider_id or detect_provider_id(runtime.base_url)
    current_models = runtime.model_options or ([runtime.model] if runtime.model else [])
    for provider in providers:
        models = list(provider.get("models", []))
        if provider["id"] == current_id:
            for model in reversed(current_models):
                if model and model not in models:
                    models.insert(0, model)
            provider["models"] = models[:3]
    if current_id == "custom":
        fallback_models = current_models or [os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()]
        providers.append(
            {
                "id": "custom",
                "name": "当前环境配置",
                "base_url": runtime.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
                "models": fallback_models[:3],
            }
        )
    return providers


def _llm_settings_payload(runtime: AgentRuntime) -> dict[str, Any]:
    """构造不含明文密钥的 LLM 设置响应。"""
    stored = load_stored_llm_settings()
    llm = runtime.agent.llm if runtime.agent is not None else None
    api_key = llm.api_key if llm is not None else (
        stored.api_key if stored is not None else os.getenv("OPENAI_API_KEY", "").strip()
    )
    base_url = llm.base_url if llm is not None else (
        runtime.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    )
    model = llm.model if llm is not None else (
        runtime.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    )
    provider_id = runtime.provider_id or detect_provider_id(base_url)
    models = runtime.model_options or ([model] if model else [])
    providers = _providers_for_runtime(runtime)
    source = "local" if stored is not None else ("environment" if api_key else "unconfigured")
    return {
        "provider_id": provider_id,
        "provider_name": next(
            (item["name"] for item in providers if item["id"] == provider_id),
            "当前环境配置",
        ),
        "base_url": base_url,
        "model": model,
        "models": models[:3],
        "providers": providers,
        "api_key_configured": bool(api_key),
        "api_key_hint": _mask_api_key(api_key),
        "source": source,
        "config_path": str(get_llm_config_path()),
        "settings_editable": True,
        "startup_error": runtime.startup_error,
    }


def _resolve_api_key(runtime: AgentRuntime, supplied: str = "", provider_id: str = "") -> str:
    """解析用户输入或已有配置中的 API Key。"""
    supplied = (supplied or "").strip()
    if supplied:
        return supplied
    stored = load_stored_llm_settings()
    if stored is not None:
        return stored.api_key
    if runtime.agent is not None:
        return runtime.agent.llm.api_key
    if provider_id == "ollama":
        return "local"
    return ""


def _resolve_provider_selection(
    runtime: AgentRuntime, provider_id: str, model: str
) -> tuple[str, str, list[str], str]:
    """根据服务商和模型解析出 Base URL，避免前端手填地址。"""
    provider_id = (provider_id or "").strip()
    model = (model or "").strip()
    if provider_id == "custom":
        base_url = runtime.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        models = runtime.model_options or ([runtime.model] if runtime.model else [])
        if model not in models:
            raise ValueError("当前环境没有该模型，请重新选择。")
        return provider_id, base_url, models[:3], model

    provider = get_provider(provider_id)
    if provider is None:
        raise ValueError("不支持的服务商。")
    models = list(provider.models[:3])
    if runtime.provider_id == provider_id:
        for current_model in reversed(runtime.model_options or [runtime.model]):
            if current_model and current_model not in models:
                models.insert(0, current_model)
    if model not in models:
        raise ValueError("该服务商不支持所选模型。")
    return provider.id, provider.base_url, models[:3], model

def _resolve_chat_model(runtime: AgentRuntime, requested: str | None) -> str:
    """校验前端选择的模型，只允许配置中的最多三个模型。"""
    model = (requested or runtime.model).strip()
    allowed = runtime.model_options or ([runtime.model] if runtime.model else [])
    if not model or model not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的模型：{model or '（空）'}")
    return model


# 生产构建存在时托管静态资源；开发阶段仍由 Vite 提供前端。
if (UI_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="ui-assets")


def _runtime_or_503(request: Request) -> AgentRuntime:
    """从 app.state 取出运行时，不存在时返回 503。"""
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="服务尚未完成初始化。")
    return runtime


def _agent_or_503(runtime: AgentRuntime) -> Agent:
    """取出可用的 Agent；配置错误时返回 503。"""
    if runtime.agent is None:
        raise HTTPException(
            status_code=503,
            detail=runtime.startup_error or "Agent 未初始化，请检查 .env 和依赖。",
        )
    return runtime.agent


def _hotspot_or_503(runtime: AgentRuntime) -> HotspotService:
    """取出热点服务；未启用时返回 503。"""
    if runtime.hotspot_service is None:
        raise HTTPException(status_code=503, detail="热点面板未启用。")
    return runtime.hotspot_service


def _skill_registry_or_503(runtime: AgentRuntime) -> SkillRegistry:
    """取出技能注册表；必要时从记忆目录延迟初始化。"""
    if runtime.skill_registry is None:
        try:
            memory_config = load_memory_config()
            runtime.skill_registry = SkillRegistry(memory_config.data_dir)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Skills 服务初始化失败：{type(exc).__name__}: {exc}",
            ) from exc
    return runtime.skill_registry


def _mcp_manager_or_503(runtime: AgentRuntime) -> MCPManager:
    """取出 MCP 管理器；必要时延迟创建。"""
    if runtime.mcp_manager is None:
        try:
            registry = runtime.agent.registry if runtime.agent is not None else None
            runtime.mcp_manager = MCPManager(registry=registry)
            runtime.mcp_manager.start_enabled()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"MCP 管理器初始化失败：{type(exc).__name__}: {exc}",
            ) from exc
    return runtime.mcp_manager


def _mcp_registry_or_503(runtime: AgentRuntime) -> MCPRegistryClient:
    """取出官方 MCP Registry 客户端。"""
    if runtime.mcp_registry_client is None:
        runtime.mcp_registry_client = MCPRegistryClient()
    return runtime.mcp_registry_client


def _memory_counter(runtime: AgentRuntime, session_id: str) -> int:
    """安全读取某会话的长期记忆条数。"""
    if runtime.long_term is None:
        return 0
    try:
        return runtime.long_term.count(session_id)
    except Exception:
        return 0


def _total_memory_count(runtime: AgentRuntime) -> int:
    """安全读取全部长期记忆条数。"""
    if runtime.long_term is None:
        return 0
    try:
        return runtime.long_term.count()
    except Exception:
        return 0


def _session_payload(runtime: AgentRuntime, meta: SessionMeta) -> dict[str, Any]:
    """把 SessionMeta 序列化为前端需要的结构。"""
    return {
        "id": meta.session_id,
        "title": meta.title,
        "display_title": meta.display_title(),
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "display_updated_at": meta.display_updated_at(),
        "memory_count": _memory_counter(runtime, meta.session_id),
    }


def _synthetic_session() -> dict[str, Any]:
    """记忆模块关闭时，给前端返回一个可用的默认会话。"""
    return {
        "id": DEFAULT_SESSION_ID,
        "title": "默认会话",
        "display_title": "默认会话",
        "created_at": "",
        "updated_at": "",
        "display_updated_at": "",
        "memory_count": 0,
    }


def _list_sessions(runtime: AgentRuntime) -> list[dict[str, Any]]:
    """列出全部会话；记忆关闭时返回合成默认会话。"""
    if runtime.sessions is None:
        return [_synthetic_session()]
    return [_session_payload(runtime, meta) for meta in runtime.sessions.list()]


def _session_or_404(runtime: AgentRuntime, session_id: str) -> SessionMeta | None:
    """校验会话是否存在；记忆关闭时只允许 default。"""
    if runtime.sessions is None:
        if session_id != DEFAULT_SESSION_ID:
            raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
        return None
    meta = runtime.sessions.get(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return meta


def _session_memory(runtime: AgentRuntime, session_id: str) -> Session | None:
    """获取短期记忆对象（兼容记忆关闭时的 Agent 内部兜底实例）。"""
    store = runtime.short_term
    if store is None and runtime.agent is not None:
        store = runtime.agent.memory
    if store is None:
        return None
    return store.session(session_id)


def _visible_history(session: Session | None, limit: int) -> list[dict[str, str]]:
    """提取前端可展示的用户/助手消息，跳过工具往返。"""
    if session is None:
        return []
    visible: list[dict[str, str]] = []
    for message in session.messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            visible.append({"role": role, "content": content})
    return visible[-limit:]


@app.get("/api/health", tags=["system"])
def health(request: Request) -> dict[str, Any]:
    """轻量健康检查。"""
    runtime = getattr(request.app.state, "runtime", None)
    ok = runtime is not None and runtime.agent is not None and not runtime.startup_error
    return {
        "status": "ok" if ok else "degraded",
        "error": runtime.startup_error if runtime is not None else "runtime missing",
    }


@app.get("/api/status", tags=["system"])
def status(request: Request) -> dict[str, Any]:
    """返回模型、记忆、工具和当前会话概要。"""
    runtime = _runtime_or_503(request)
    settings = _llm_settings_payload(runtime)
    try:
        skill_records = runtime.skill_registry.list() if runtime.skill_registry is not None else []
        skills_dir = str(runtime.skill_registry.skills_dir) if runtime.skill_registry is not None else ""
    except Exception:
        skill_records = []
        skills_dir = ""
    try:
        mcp_servers = runtime.mcp_manager.list_servers() if runtime.mcp_manager is not None else []
    except Exception:
        mcp_servers = []
    return {
        "status": "ok" if runtime.agent is not None and not runtime.startup_error else "degraded",
        "model": runtime.model,
        "provider_id": runtime.provider_id,
        "models": runtime.model_options or ([runtime.model] if runtime.model else []),
        "base_url": runtime.base_url,
        "temperature": runtime.temperature,
        "max_steps": runtime.max_steps,
        "api_key_configured": settings["api_key_configured"],
        "llm_settings_source": settings["source"],
        "llm_settings_editable": _settings_request_allowed(request),
        "memory_enabled": runtime.memory_enabled,
        "long_term_enabled": runtime.long_term_enabled,
        "hotspots_enabled": runtime.hotspots_enabled,
        "hotspot_ttl_minutes": runtime.hotspot_ttl_minutes,
        "data_dir": runtime.data_dir,
        "model_dir": runtime.model_dir,
        "sessions_dir": runtime.sessions_dir,
        "chroma_dir": runtime.chroma_dir,
        "short_term_max": runtime.short_term_max,
        "short_term_keep": runtime.short_term_keep,
        "default_session_id": runtime.default_session_id,
        "session_count": runtime.sessions.count if runtime.sessions is not None else 1,
        "long_term_count": _total_memory_count(runtime),
        "tools": runtime.tool_names,
        "mcp_tools": runtime.mcp_tools,
        "skills_dir": skills_dir,
        "skill_count": len(skill_records),
        "skill_enabled_count": sum(1 for item in skill_records if item.enabled),
        "mcp_server_count": len(mcp_servers),
        "mcp_connected_count": sum(1 for item in mcp_servers if item.get("connected")),
        "startup_error": runtime.startup_error,
        "warnings": runtime.warnings,
    }


@app.get("/api/settings/llm", tags=["settings"])
def get_llm_settings(request: Request) -> dict[str, Any]:
    """返回当前 LLM API 配置；不会返回明文 API Key。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    return _llm_settings_payload(runtime)


@app.post("/api/settings/llm/test", tags=["settings"])
def test_llm_settings(payload: LLMSettingsTestRequest, request: Request) -> dict[str, Any]:
    """测试当前模型服务配置，不保存。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    try:
        provider_id, base_url, _models, model = _resolve_provider_selection(
            runtime, payload.provider_id, payload.model
        )
        api_key = validate_llm_api_key(
            _resolve_api_key(runtime, payload.api_key, provider_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    started = time.perf_counter()
    try:
        client = LLMClient(
            api_key,
            base_url,
            model,
            temperature=runtime.temperature,
            timeout=20.0,
            max_retries=0,
        )
        reply = client.test_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"连接失败：{type(exc).__name__}: {exc}",
        ) from exc
    return {
        "ok": True,
        "message": "连接成功",
        "reply": reply[:120],
        "provider_id": provider_id,
        "base_url": base_url,
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


@app.put("/api/settings/llm", tags=["settings"])
def update_llm_settings(payload: LLMSettingsUpdateRequest, request: Request) -> dict[str, Any]:
    """保存用户模型服务配置，并让当前进程立即生效。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    try:
        provider_id, base_url, models, model = _resolve_provider_selection(
            runtime, payload.provider_id, payload.model
        )
        api_key = validate_llm_api_key(
            _resolve_api_key(runtime, payload.api_key, provider_id)
        )
        config_path = save_stored_llm_settings(provider_id, base_url, model, models, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"保存模型配置失败：{type(exc).__name__}: {exc}",
        ) from exc

    if runtime.agent is not None:
        with runtime.lock:
            try:
                runtime.agent.llm.reconfigure(api_key, base_url, model, runtime.temperature)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"应用模型配置失败：{type(exc).__name__}: {exc}",
                ) from exc
            runtime.provider_id = provider_id
            runtime.base_url = base_url
            runtime.model = model
            runtime.model_options = models[:3]
            runtime.startup_error = ""
            result = _llm_settings_payload(runtime)
            result["applied"] = True
            result["config_path"] = str(config_path)
            return result

    with runtime.lock:
        new_runtime = build_runtime()
        request.app.state.runtime = new_runtime
        runtime.close()
    result = _llm_settings_payload(new_runtime)
    result["applied"] = new_runtime.agent is not None
    result["config_path"] = str(config_path)
    if new_runtime.startup_error:
        result["startup_error"] = new_runtime.startup_error
    if new_runtime.warnings:
        result["warnings"] = new_runtime.warnings
    return result

@app.get("/api/skills", tags=["skills"])
def list_skills(request: Request, q: str = Query(default="", max_length=200)) -> dict[str, Any]:
    """搜索已安装的 Skills。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    return {"items": [item.to_dict() for item in registry.list(q)], "skills_dir": str(registry.skills_dir)}


@app.post("/api/skills/refresh", tags=["skills"])
def refresh_skills(request: Request) -> dict[str, Any]:
    """重新扫描本地 Skills 目录。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    return {"items": [item.to_dict() for item in registry.scan()], "skills_dir": str(registry.skills_dir)}


@app.get("/api/skills/catalog", tags=["skills"])
def skill_catalog(
    request: Request,
    source: str = Query(default="openai"),
    q: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    """读取 GitHub 上的官方 Skills 目录。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        items = registry.catalog(source, q)
    except SkillError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"source": source, "items": items}


@app.get("/api/skills/{skill_id}", tags=["skills"])
def skill_detail(skill_id: str, request: Request) -> dict[str, Any]:
    """返回 Skill 详情和 SKILL.md 内容。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        return registry.get(skill_id)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/skills/install", tags=["skills"])
def install_skill(payload: SkillInstallRequest, request: Request) -> dict[str, Any]:
    """从 GitHub 下载并安装一个标准 Skill。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        return registry.install_github(payload.repo, payload.path, payload.ref)
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/skills/{skill_id}/enable", tags=["skills"])
def enable_skill(skill_id: str, request: Request) -> dict[str, Any]:
    """启用一个 Skill。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        return registry.set_enabled(skill_id, True)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/skills/{skill_id}/disable", tags=["skills"])
def disable_skill(skill_id: str, request: Request) -> dict[str, Any]:
    """停用一个 Skill。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        return registry.set_enabled(skill_id, False)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/skills/{skill_id}", tags=["skills"])
def delete_skill(skill_id: str, request: Request) -> dict[str, Any]:
    """删除一个用户安装的 Skill。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry = _skill_registry_or_503(runtime)
    try:
        registry.delete(skill_id)
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted": skill_id}

@app.get("/api/mcp/registry/search", tags=["mcp"])
def search_mcp_registry(
    request: Request,
    q: str = Query(default="", max_length=200),
    cursor: str = Query(default="", max_length=500),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """搜索官方 MCP Registry。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    client = _mcp_registry_or_503(runtime)
    try:
        return client.search(q, cursor, limit)
    except MCPRegistryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/mcp/registry/detail", tags=["mcp"])
def mcp_registry_detail(
    request: Request,
    name: str = Query(min_length=3, max_length=300),
    version: str = Query(default="latest", max_length=120),
) -> dict[str, Any]:
    """读取官方 Registry 中的 MCP 服务详情。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    client = _mcp_registry_or_503(runtime)
    try:
        return client.detail(name, version)
    except MCPRegistryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/mcp/servers", tags=["mcp"])
def list_mcp_servers(request: Request) -> dict[str, Any]:
    """列出已安装的 MCP 服务与连接状态。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    return {"items": manager.list_servers()}


@app.post("/api/mcp/servers/install", tags=["mcp"])
def install_mcp_server(payload: MCPInstallRequest, request: Request) -> dict[str, Any]:
    """从官方 Registry 安装并启动 MCP 服务。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    registry_client = _mcp_registry_or_503(runtime)
    manager = _mcp_manager_or_503(runtime)
    try:
        server = registry_client.detail(payload.name, payload.version)
        return manager.install_from_registry(
            server,
            payload.transport,
            package_index=payload.package_index,
            remote_index=payload.remote_index,
            env=payload.env,
            headers=payload.headers,
            tools=payload.tools,
        )
    except (MCPRegistryError, MCPManagerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mcp/servers/{server_id}/enable", tags=["mcp"])
def enable_mcp_server(server_id: str, request: Request) -> dict[str, Any]:
    """启用并连接 MCP 服务。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    try:
        return manager.set_enabled(server_id, True)
    except MCPManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mcp/servers/{server_id}/disable", tags=["mcp"])
def disable_mcp_server(server_id: str, request: Request) -> dict[str, Any]:
    """停用并断开 MCP 服务。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    try:
        return manager.set_enabled(server_id, False)
    except MCPManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mcp/servers/{server_id}/restart", tags=["mcp"])
def restart_mcp_server(server_id: str, request: Request) -> dict[str, Any]:
    """重启 MCP 服务。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    try:
        return manager.restart_server(server_id)
    except MCPManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/mcp/servers/{server_id}/tools", tags=["mcp"])
def list_mcp_server_tools(server_id: str, request: Request) -> dict[str, Any]:
    """列出某个 MCP 服务注册到 Agent 的工具。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    try:
        return {"server_id": server_id, "tools": manager.get_tools(server_id)}
    except MCPManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/mcp/servers/{server_id}", tags=["mcp"])
def delete_mcp_server(server_id: str, request: Request) -> dict[str, Any]:
    """删除 MCP 服务及其本地配置。"""
    _require_settings_access(request)
    runtime = _runtime_or_503(request)
    manager = _mcp_manager_or_503(runtime)
    try:
        manager.remove_server(server_id)
    except MCPManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted": server_id}

@app.get("/api/sessions", tags=["sessions"])
def list_sessions(request: Request) -> list[dict[str, Any]]:
    """列出全部会话，最近使用在前。"""
    runtime = _runtime_or_503(request)
    with runtime.lock:
        return _list_sessions(runtime)


@app.post("/api/sessions", tags=["sessions"])
def create_session(payload: SessionCreateRequest, request: Request) -> dict[str, Any]:
    """新建会话并返回其元信息。"""
    runtime = _runtime_or_503(request)
    _agent_or_503(runtime)
    if runtime.sessions is None:
        raise HTTPException(status_code=409, detail="记忆模块已关闭，无法新建会话。")
    with runtime.lock:
        session_id = runtime.sessions.create(payload.title.strip())
        meta = runtime.sessions.get(session_id)
        if meta is None:
            raise HTTPException(status_code=500, detail="会话创建失败。")
        return _session_payload(runtime, meta)


@app.patch("/api/sessions/{session_id}", tags=["sessions"])
def rename_session(
    session_id: str, payload: SessionRenameRequest, request: Request
) -> dict[str, Any]:
    """修改会话标题。"""
    runtime = _runtime_or_503(request)
    with runtime.lock:
        meta = _session_or_404(runtime, session_id)
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空。")
        if runtime.sessions is not None:
            runtime.sessions.rename(session_id, title)
            meta = runtime.sessions.get(session_id)
        return _session_payload(runtime, meta) if meta is not None else _synthetic_session()


@app.delete("/api/sessions/{session_id}", tags=["sessions"])
def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    """删除会话及其短期记忆和长期记忆。"""
    runtime = _runtime_or_503(request)
    _agent_or_503(runtime)
    if runtime.sessions is None:
        raise HTTPException(status_code=409, detail="记忆模块已关闭，无法删除会话。")
    with runtime.lock:
        _session_or_404(runtime, session_id)
        if runtime.sessions.count <= 1:
            raise HTTPException(status_code=409, detail="至少保留一个会话。")
        removed = 0
        if runtime.long_term is not None:
            removed = runtime.long_term.delete_session(session_id)
        if runtime.short_term is not None:
            runtime.short_term.reset(session_id)
        runtime.sessions.delete(session_id)
        return {
            "deleted": session_id,
            "memory_removed": removed,
            "sessions": _list_sessions(runtime),
        }


@app.get("/api/sessions/{session_id}/history", tags=["sessions"])
def session_history(
    session_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=MAX_HISTORY),
) -> dict[str, Any]:
    """返回某会话最近的用户/助手消息。"""
    runtime = _runtime_or_503(request)
    with runtime.lock:
        meta = _session_or_404(runtime, session_id)
        session = _session_memory(runtime, session_id)
        return {
            "session": _session_payload(runtime, meta)
            if meta is not None
            else _synthetic_session(),
            "messages": _visible_history(session, limit),
            "summary": session.summary if session is not None else "",
        }


@app.post("/api/chat", tags=["chat"])
def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
    """执行一次 Agent 对话并返回最终答复。"""
    runtime = _runtime_or_503(request)
    agent = _agent_or_503(runtime)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空。")
    model = _resolve_chat_model(runtime, payload.model)

    if runtime.sessions is not None:
        session_id = payload.session_id or runtime.default_session_id
        _session_or_404(runtime, session_id)
    else:
        session_id = DEFAULT_SESSION_ID

    hotspot_context = ""
    if runtime.hotspot_service is not None:
        hotspot_context = runtime.hotspot_service.context_text()
    skill_context = (
        runtime.skill_registry.context_for_query(message)
        if runtime.skill_registry is not None
        else ""
    )
    extra_system = "\n\n".join(part for part in (hotspot_context, skill_context) if part)

    with runtime.lock:
        try:
            answer = agent.run(
                message,
                session_id=session_id,
                extra_system=extra_system,
                model=model,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Agent 运行失败：{type(exc).__name__}: {exc}",
            ) from exc

        session_payload = _synthetic_session()
        if runtime.sessions is not None:
            meta = runtime.sessions.get(session_id)
            if meta is not None and not meta.title:
                auto_title = " ".join(message.split())[:20]
                if auto_title:
                    runtime.sessions.rename(session_id, auto_title)
            runtime.sessions.touch(session_id)
            meta = runtime.sessions.get(session_id)
            if meta is not None:
                session_payload = _session_payload(runtime, meta)

    return {
        "answer": answer,
        "session": session_payload,
        "session_id": session_id,
    }


@app.post("/api/chat/stream", tags=["chat"])
def chat_stream(payload: ChatRequest, request: Request):
    """流式执行一次 Agent 对话，通过 SSE 推送状态和文本分片。"""
    runtime = _runtime_or_503(request)
    agent = _agent_or_503(runtime)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空。")
    model = _resolve_chat_model(runtime, payload.model)

    if runtime.sessions is not None:
        session_id = payload.session_id or runtime.default_session_id
        _session_or_404(runtime, session_id)
    else:
        session_id = DEFAULT_SESSION_ID

    hotspot_context = ""
    if runtime.hotspot_service is not None:
        hotspot_context = runtime.hotspot_service.context_text()
    skill_context = (
        runtime.skill_registry.context_for_query(message)
        if runtime.skill_registry is not None
        else ""
    )
    extra_system = "\n\n".join(part for part in (hotspot_context, skill_context) if part)

    events: Queue = Queue()

    def worker() -> None:
        try:
            with runtime.lock:
                answer = agent.run(
                    message,
                    session_id=session_id,
                    extra_system=extra_system,
                    model=model,
                    on_token=lambda chunk: events.put({"type": "token", "content": chunk}),
                    on_status=lambda text: events.put({"type": "status", "message": text}),
                )
                session_payload = _synthetic_session()
                if runtime.sessions is not None:
                    meta = runtime.sessions.get(session_id)
                    if meta is not None and not meta.title:
                        auto_title = " ".join(message.split())[:20]
                        if auto_title:
                            runtime.sessions.rename(session_id, auto_title)
                    runtime.sessions.touch(session_id)
                    meta = runtime.sessions.get(session_id)
                    if meta is not None:
                        session_payload = _session_payload(runtime, meta)
                events.put(
                    {
                        "type": "done",
                        "answer": answer,
                        "session": session_payload,
                        "session_id": session_id,
                    }
                )
        except Exception as exc:
            events.put(
                {
                    "type": "error",
                    "message": f"Agent 运行失败：{type(exc).__name__}: {exc}",
                }
            )
        finally:
            events.put(None)

    threading.Thread(target=worker, name="agent-chat-stream", daemon=True).start()

    def event_stream():
        while True:
            event = events.get()
            if event is None:
                break
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/hotspots", tags=["hotspots"])

def get_hotspots(
    request: Request,
    refresh: bool = Query(default=False, description="是否强制刷新热点数据"),
) -> dict[str, Any]:
    """返回缓存的四平台热点面板数据。"""
    runtime = _runtime_or_503(request)
    service = _hotspot_or_503(runtime)
    try:
        return service.get_or_refresh(force=refresh)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"热点数据获取失败：{type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/hotspots/refresh", tags=["hotspots"])
def refresh_hotspots(request: Request) -> dict[str, Any]:
    """强制重新拉取热点并调用 LLM 生成分析。"""
    runtime = _runtime_or_503(request)
    service = _hotspot_or_503(runtime)
    try:
        return service.refresh()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"热点刷新失败：{type(exc).__name__}: {exc}",
        ) from exc


@app.get("/favicon.png", include_in_schema=False)
def favicon() -> Any:
    """返回前端 favicon。"""
    favicon_file = UI_DIST / "favicon.png"
    if not favicon_file.exists():
        raise HTTPException(status_code=404, detail="favicon 尚未构建。")
    return FileResponse(favicon_file, media_type="image/png")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> Any:
    """兼容浏览器默认请求的 /favicon.ico。"""
    favicon_file = UI_DIST / "favicon.png"
    if not favicon_file.exists():
        raise HTTPException(status_code=404, detail="favicon 尚未构建。")
    return FileResponse(favicon_file, media_type="image/png")


@app.get("/", include_in_schema=False)

def index() -> Any:
    """生产构建存在时返回 Vue 入口，否则返回 API 提示。"""
    index_file = UI_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "name": "MyBot API",
        "docs": "/docs",
        "message": "前端尚未构建。开发时请运行 ui 目录下的 npm run dev。",
    }


def main() -> None:
    """命令行启动入口。"""
    import uvicorn

    load_dotenv(str(resolve_env_file()))
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("mybot.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()