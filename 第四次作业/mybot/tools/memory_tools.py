"""记忆工具模块：让模型写入/检索长期记忆（按会话隔离）。"""

from __future__ import annotations

from typing import Any

from ..long_memory import DEFAULT_MEMORY_TYPE, MEMORY_TYPES
from ..session_scope import current_session
from .base import Tool, ToolResult


class MemorySaveTool(Tool):
    """长期记忆写入工具：由模型判断哪些信息值得长期记住。"""

    def __init__(self, long_term: Any) -> None:
        """初始化。

        参数:
            long_term: LongTermMemory 实例。
        """
        self._long_term = long_term

    @property
    def name(self) -> str:
        return "memory_save"

    @property
    def description(self) -> str:
        return (
            "把值得长期记住的信息写入【当前会话】的长期记忆，之后可在本会话中被自动回忆。"
            "适用于：用户的身份/偏好/习惯、重要约定、已确认的结论或事实。"
            "不要记录寒暄、临时性内容或一次性的中间过程。"
            "写入内容要自包含——脱离当前对话也能读懂（例如写「用户喜欢喝美式咖啡」而不是「他喜欢这个」）。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要长期记住的内容（自包含的一句话）"},
                "type": {
                    "type": "string",
                    "enum": list(MEMORY_TYPES),
                    "description": (
                        "记忆类型：fact=客观事实，preference=用户偏好，conclusion=已确认的结论"
                    ),
                },
                "tags": {"type": "string", "description": "可选标签，如 身份/项目/偏好"},
            },
            "required": ["content"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """写入一条长期记忆（归属当前会话）。

        参数:
            **kwargs: 必须包含 content（str），可选 type（str）、tags（str）。

        返回:
            ToolResult，成功时提示已记住；内容为空时返回错误。
        """
        content = str(kwargs.get("content", "")).strip()
        if not content:
            return ToolResult.error("错误：content 不能为空。")
        mem_type = str(kwargs.get("type", DEFAULT_MEMORY_TYPE)).strip() or DEFAULT_MEMORY_TYPE
        tags = str(kwargs.get("tags", "")).strip()
        session_id = current_session()
        try:
            self._long_term.add(content, session_id=session_id, mem_type=mem_type, tags=tags)
        except Exception as exc:
            return ToolResult.error(f"错误：写入长期记忆失败：{exc}")
        return ToolResult(content=f"已记入当前会话（{session_id}）的长期记忆：{content}")


class MemorySearchCrossSessionTool(Tool):
    """跨会话记忆检索工具：仅在用户明确要求时使用。"""

    def __init__(self, long_term: Any) -> None:
        """初始化。

        参数:
            long_term: LongTermMemory 实例。
        """
        self._long_term = long_term

    @property
    def name(self) -> str:
        return "memory_search_other_sessions"

    @property
    def description(self) -> str:
        return (
            "在【其他会话】里检索历史记忆。"
            "默认不要调用本工具——各会话记忆相互隔离是设计如此。"
            "只有当用户明确要求「查一下我在别的对话里说过什么」并确认后，才调用它。"
            "返回结果会标注每条记忆来自哪个会话，回答时必须说明来源，不要与本会话内容混淆。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要在其他会话中检索的关键词或问题"},
                "max_results": {"type": "integer", "description": "最多返回条数，默认 5"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """跨会话检索长期记忆。

        参数:
            **kwargs: 必须包含 query（str），可选 max_results（int）。

        返回:
            ToolResult，content 为带来源会话标注的记忆列表；无命中时给出提示。
        """
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult.error("错误：query 不能为空。")
        max_results = int(kwargs.get("max_results", 5) or 5)

        session_id = current_session()
        try:
            hits = self._long_term.search_cross_session(
                query, exclude_session_id=session_id, top_k=max_results
            )
        except Exception as exc:
            return ToolResult.error(f"错误：跨会话检索失败：{exc}")

        if not hits:
            return ToolResult(content=f"在其他会话中没有找到与「{query}」相关的记忆。")

        lines = [f"在其他会话中找到 {len(hits)} 条相关记忆（请注明来源会话）：", ""]
        for index, (content, source) in enumerate(hits, start=1):
            lines.append(f"{index}. [来源会话：{source}] {content}")
        return ToolResult(content="\n".join(lines))
