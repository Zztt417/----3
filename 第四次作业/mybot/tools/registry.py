"""工具注册表模块：负责工具的注册、查询、schema 导出与按名执行。"""

from __future__ import annotations

import json
from typing import Any

from .base import Tool, ToolResult


class ToolRegistry:
    """工具注册表。

    参考 nanobot 的 ToolRegistry：把「工具是谁」与「工具怎么被调用」解耦，
    Agent 循环只需依赖本类，不关心具体有哪些工具。
    """

    def __init__(self) -> None:
        """初始化一个空的工具表。"""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具（同名会覆盖）。

        参数:
            tool: Tool 实例。
        """
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名获取工具。

        参数:
            name: 工具名。

        返回:
            对应的 Tool 实例；不存在时返回 None。
        """
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """导出所有工具的 OpenAI schema 列表。

        返回:
            工具 schema 列表；按工具名排序以保证提示词稳定（利于缓存）。
        """
        return [self._tools[n].to_schema() for n in sorted(self._tools)]

    @property
    def tool_names(self) -> list[str]:
        """返回已注册的工具名列表（排序后）。"""
        return sorted(self._tools)

    def execute(self, name: str, arguments: str | dict[str, Any]) -> ToolResult:
        """执行指定工具，任何异常都转换为错误结果（不抛出），便于回喂给 LLM。

        参数:
            name: 工具名。
            arguments: LLM 给出的参数，通常是 JSON 字符串，也可能是 dict 或空串。

        返回:
            ToolResult；出错时 is_error=True。
        """
        tool = self.get(name)
        if tool is None:
            return ToolResult.error(
                f"错误：工具 '{name}' 不存在。可用工具：{', '.join(self.tool_names)}"
            )

        # 参数解析：空串视为无参调用；非法 JSON 直接返回错误
        if isinstance(arguments, str):
            raw = arguments.strip()
            if not raw:
                params: dict[str, Any] = {}
            else:
                try:
                    params = json.loads(raw)
                except json.JSONDecodeError as exc:
                    return ToolResult.error(f"错误：工具 '{name}' 的参数不是合法 JSON：{exc}")
        else:
            params = arguments

        if not isinstance(params, dict):
            return ToolResult.error(f"错误：工具 '{name}' 的参数必须是 JSON 对象。")

        try:
            return tool.execute(**params)
        except Exception as exc:  # 兜底：工具内部异常不中断 ReAct 循环
            return ToolResult.error(f"错误：执行工具 '{name}' 时抛出异常：{exc}")
