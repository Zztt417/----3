"""工具包：导出基类与注册表，并提供默认工具集工厂。"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult
from .builtin import ReadFileTool, RunShellTool, WriteFileTool
from .memory_tools import MemorySaveTool, MemorySearchCrossSessionTool
from .pdf_tools import PdfParseTool
from .registry import ToolRegistry
from .web import WebFetchTool, WebSearchTool


def create_default_registry(long_term: Any | None = None) -> ToolRegistry:
    """创建并返回注册了内置工具的工具注册表。

    参数:
        long_term: 长期记忆实例；传入时会额外注册记忆读写相关的工具。

    返回:
        已注册 read_file / write_file / run_shell / web_search / web_fetch / pdf_parse
        的 ToolRegistry；传入 long_term 时还会包含 memory_save 与
        memory_search_other_sessions。
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(RunShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(PdfParseTool())
    if long_term is not None:
        registry.register(MemorySaveTool(long_term))
        registry.register(MemorySearchCrossSessionTool(long_term))
    return registry


__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "ReadFileTool",
    "WriteFileTool",
    "RunShellTool",
    "WebSearchTool",
    "WebFetchTool",
    "PdfParseTool",
    "MemorySaveTool",
    "MemorySearchCrossSessionTool",
    "create_default_registry",
]
