"""MCP 客户端模块：在后台线程的事件循环上运行 MCP stdio 服务，并包装成同步工具。

官方 ``mcp`` SDK 是 asyncio 的，而本项目的工具接口是同步的（``Tool.execute``）。
因此这里把 MCP 连接放进一个守护线程的独立事件循环，对外只暴露同步方法：
主线程通过 ``asyncio.run_coroutine_threadsafe`` 把协程投递到那个循环里执行。
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from .tools.base import Tool, ToolResult

# MCP 子进程 stderr 的默认落盘位置（该目录已在 .gitignore 中忽略）
DEFAULT_ERRLOG_PATH = Path(".mybot") / "mcp.log"


class MCPClient:
    """MCP stdio 客户端的同步门面。

    生命周期：``start()`` → ``list_tools()`` / ``call_tool()`` → ``close()``。
    任何一步失败都应被调用方捕获并降级，不应影响主程序。
    """

    def __init__(
        self,
        command_line: str,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
        errlog_path: str | Path | None = DEFAULT_ERRLOG_PATH,
    ) -> None:
        """初始化（不建立连接）。

        参数:
            command_line: 启动 MCP 服务的完整命令行，如
                "uvx mcp-email-server@latest stdio"。
            env: 追加给子进程的环境变量；None 表示仅继承当前环境。
            timeout: 启动握手与单次调用的超时秒数。
            errlog_path: MCP 子进程 stderr 的落盘位置；None 表示丢弃。
                MCP 启动器（uvx）与部分服务会把大量 INFO 日志打到 stderr，
                默认直接落盘可以让终端保持干净，同时保留排查线索。

        异常:
            ValueError: 命令行为空。
        """
        parts = shlex.split(command_line)
        if not parts:
            raise ValueError("MCP 命令行不能为空")
        self._command = parts[0]
        self._args = parts[1:]
        self._env = env
        self._timeout = timeout
        self._errlog_path = Path(errlog_path) if errlog_path is not None else None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._tools: list[Any] = []
        self._closing: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动后台线程并等待 MCP 握手完成。

        异常:
            RuntimeError: 启动超时或握手失败（调用方应降级处理）。
        """
        self._thread = threading.Thread(target=self._thread_main, name="mcp-client", daemon=True)
        self._thread.start()
        if not self._ready.wait(self._timeout):
            raise RuntimeError(f"MCP 服务启动超时（>{self._timeout:g}s）：{self._command}")
        if self._error is not None:
            raise RuntimeError(f"MCP 服务启动失败：{type(self._error).__name__}: {self._error}")

    def close(self, join_timeout: float = 5.0) -> None:
        """通知后台循环退出并等待线程结束（从而回收 MCP 子进程）。

        参数:
            join_timeout: 等待线程退出的秒数。
        """
        if self._loop is not None and self._closing is not None:
            try:
                self._loop.call_soon_threadsafe(self._closing.set)
            except RuntimeError:
                pass  # 循环已关闭
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)

    # ---------- 对外同步接口 ----------

    def list_tools(self) -> list[Any]:
        """返回已发现的 MCP 工具对象列表。

        返回:
            SDK 的工具对象列表（每个含 name / description / inputSchema）。
        """
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """同步调用一个 MCP 工具。

        参数:
            name: MCP 工具名。
            arguments: 参数字典。

        返回:
            SDK 的 CallToolResult。

        异常:
            RuntimeError: 连接未就绪或调用超时。
        """
        if self._session is None or self._loop is None:
            raise RuntimeError("MCP 连接未就绪")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments), self._loop
        )
        try:
            return future.result(timeout=self._timeout)
        except TimeoutError as exc:  # concurrent.futures.TimeoutError
            raise RuntimeError(f"MCP 工具调用超时（>{self._timeout:g}s）：{name}") from exc

    # ---------- 内部：线程与协程 ----------

    def _thread_main(self) -> None:
        """后台线程入口：建立事件循环、完成握手、保持存活直到关闭。"""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except BaseException as exc:  # 取消/超时也可能是 BaseException，统一记录后降级
            self._error = exc
        finally:
            self._ready.set()  # 无论成功失败都要放行主线程，避免死等
            loop.close()

    def _open_errlog(self) -> TextIO:
        """打开 MCP 子进程 stderr 的落盘文件。

        落盘失败（如目录不可写）时退回空设备，保证终端始终不被日志刷屏。

        返回:
            可写的文本流。
        """
        if self._errlog_path is not None:
            try:
                self._errlog_path.parent.mkdir(parents=True, exist_ok=True)
                return self._errlog_path.open("a", encoding="utf-8", errors="replace")
            except OSError:
                pass
        return open(os.devnull, "w", encoding="utf-8")

    async def _serve(self) -> None:
        """建立 stdio 连接、握手、列出工具，然后等待关闭信号。"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._closing = asyncio.Event()
        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env={**os.environ, **(self._env or {})},
        )
        errlog = self._open_errlog()
        try:
            # errlog：把子进程 stderr 落盘，避免 uvx / MCP 服务的 INFO 日志刷屏
            async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._tools = list(getattr(result, "tools", []) or [])
                    self._session = session
                    self._ready.set()  # 握手完成，放行主线程
                    await self._closing.wait()  # 保持连接，直到 close() 触发
        finally:
            errlog.close()


class MCPToolWrapper(Tool):
    """把一个 MCP 工具包装成 mybot 的同步 Tool。"""

    def __init__(
        self,
        client: MCPClient,
        tool: Any,
        field_defaults: dict[str, Any] | None = None,
    ) -> None:
        """初始化。

        参数:
            client: 已连接的 MCPClient。
            tool: SDK 返回的工具对象（含 name / description / inputSchema）。
            field_defaults: 模型未填时自动补全的参数（如 account_name）。
        """
        self._client = client
        self._tool_name = str(tool.name)
        self._description = str(getattr(tool, "description", "") or tool.name)
        schema = getattr(tool, "inputSchema", None)
        self._schema: dict[str, Any] = (
            schema if isinstance(schema, dict) and schema else {"type": "object", "properties": {}}
        )
        self._defaults = dict(field_defaults or {})

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        if self._defaults:
            preset = "、".join(f"{key}={value}" for key, value in self._defaults.items())
            return f"{self._description}（以下参数已预设，无需填写：{preset}）"
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步执行 MCP 工具。

        参数:
            **kwargs: 传给 MCP 工具的参数。

        返回:
            ToolResult；MCP 返回 isError 或调用异常时为错误结果。
        """
        arguments = dict(kwargs)
        for field, value in self._defaults.items():
            if not arguments.get(field):
                arguments[field] = value
        try:
            result = self._client.call_tool(self._tool_name, arguments)
        except Exception as exc:
            return ToolResult.error(f"错误：调用 MCP 工具 {self._tool_name} 失败：{exc}")
        return render_call_result(result)


def render_call_result(result: Any) -> ToolResult:
    """把 MCP 的 CallToolResult 渲染成项目的 ToolResult。

    渲染策略（按优先级）：
        1. 拼接各 ``content`` 块的文本；
        2. 若没有文本块（部分服务只返回**结构化结果**，``content`` 为空、
           真正的数据在 ``structuredContent`` 里），则把 ``structuredContent``
           序列化成 JSON 文本——否则调用方会看不到任何结果。

    参数:
        result: SDK 的 CallToolResult（含 content / structuredContent / isError）。

    返回:
        ToolResult，文本内容来自上述渲染；isError 为真时是错误结果。
    """
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
        else:
            parts.append(f"[{getattr(block, 'type', 'unknown')} 类型内容已忽略]")

    if not parts:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            try:
                parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
            except (TypeError, ValueError):
                parts.append(str(structured))

    content = "\n".join(parts).strip() or "(MCP 工具无输出)"
    if getattr(result, "isError", False):
        return ToolResult.error(content)
    return ToolResult(content=content)


def connect_mcp_tools(
    command_line: str,
    allowed_tools: list[str] | None = None,
    field_defaults: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[list[Tool], MCPClient | None]:
    """连接 MCP 服务，并按白名单返回包装好的同步工具。

    任何失败都降级为「无工具」：只打印一行提示，不抛异常，
    以免 MCP 不可用时拖垮整个 CLI。

    参数:
        command_line: 启动 MCP 服务的命令行。
        allowed_tools: 允许暴露给模型的 MCP 工具名；为空表示全部允许。
        field_defaults: 自动补全的参数（如 account_name）。
        timeout: 启动与调用超时秒数。

    返回:
        (包装后的工具列表, MCPClient 或 None)；失败时返回 ([], None)。
    """
    client: MCPClient | None = None
    try:
        client = MCPClient(command_line, timeout=timeout)
        client.start()
    except Exception as exc:
        print(f"[MCP] 连接失败（{type(exc).__name__}: {exc}），相关工具已禁用。", file=sys.stderr)
        if client is not None:
            client.close()
        return [], None

    allowed = {name for name in (allowed_tools or []) if name}
    discovered = client.list_tools()
    selected = [tool for tool in discovered if not allowed or str(tool.name) in allowed]

    if not selected:
        available = ", ".join(str(tool.name) for tool in discovered) or "无"
        print(
            f"[MCP] 没有匹配的工具（白名单：{', '.join(sorted(allowed)) or '全部'}；"
            f"服务提供：{available}），相关工具已禁用。",
            file=sys.stderr,
        )
        client.close()
        return [], None

    wrappers = [MCPToolWrapper(client, tool, field_defaults) for tool in selected]
    return wrappers, client
