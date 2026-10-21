"""FastAPI 接口：把本地 Agent 暴露给 Vue 前端。

启动方式：
    python api_server.py
或：
    python -m mybot.api

开发时前端由 Vite 启动，`/api` 通过代理转发到本服务；
生产构建后，FastAPI 会自动托管 `ui/dist`。
"""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .agent import SYSTEM_PROMPT, Agent
from .config import load_config, load_mcp_config, load_memory_config, resolve_env_file
from .llm import LLMClient
from .long_memory import LongTermMemory, create_long_term_memory
from .mcp_client import connect_mcp_tools
from .memory import Session, ShortTermMemory
from .session_scope import DEFAULT_SESSION_ID
from .sessions import SessionIndex, SessionMeta
from .tools import create_default_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIST = PROJECT_ROOT / "ui" / "dist"
MAX_HISTORY = 500


class ChatRequest(BaseModel):
    """一次聊天请求。"""

    session_id: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=20_000)


class SessionCreateRequest(BaseModel):
    """新建会话请求。"""

    title: str = Field(default="", max_length=120)


class SessionRenameRequest(BaseModel):
    """重命名会话请求。"""

    title: str = Field(min_length=1, max_length=120)


@dataclass
class AgentRuntime:
    """API 进程内共享的 Agent 运行时。"""

    agent: Agent | None = None
    short_term: ShortTermMemory | None = None
    long_term: LongTermMemory | None = None
    sessions: SessionIndex | None = None
    mcp_client: Any | None = None
    mcp_tools: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    model: str = ""
    base_url: str = ""
    temperature: float = 0.0
    max_steps: int = 10
    memory_enabled: bool = False
    long_term_enabled: bool = False
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

    runtime.model = config.model
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
    return {
        "status": "ok" if runtime.agent is not None and not runtime.startup_error else "degraded",
        "model": runtime.model,
        "base_url": runtime.base_url,
        "temperature": runtime.temperature,
        "max_steps": runtime.max_steps,
        "memory_enabled": runtime.memory_enabled,
        "long_term_enabled": runtime.long_term_enabled,
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
        "startup_error": runtime.startup_error,
        "warnings": runtime.warnings,
    }


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

    if runtime.sessions is not None:
        session_id = payload.session_id or runtime.default_session_id
        _session_or_404(runtime, session_id)
    else:
        session_id = DEFAULT_SESSION_ID

    with runtime.lock:
        try:
            answer = agent.run(message, session_id=session_id)
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