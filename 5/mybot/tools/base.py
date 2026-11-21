"""工具基类模块：定义所有工具的统一接口与执行结果类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """工具执行结果。

    属性:
        content: 返回给 LLM 的文本内容。
        is_error: 是否为错误（True 表示执行失败）。
    """

    content: str
    is_error: bool = False

    @classmethod
    def error(cls, content: str) -> "ToolResult":
        """构造一个错误结果。

        参数:
            content: 错误说明文本。

        返回:
            is_error=True 的 ToolResult。
        """
        return cls(content=content, is_error=True)


class Tool(ABC):
    """工具抽象基类。

    子类必须实现 name / description / parameters / execute 四个成员。
    这一设计参考 nanobot 的 Tool 基类，保证「注册表只依赖统一接口」。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名（LLM 通过该名调用，必须与注册名一致）。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具功能描述（写给 LLM 看，决定它何时调用该工具）。"""

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """参数的 JSON Schema。"""

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具。

        参数:
            **kwargs: 由 LLM 传入的命名参数（与 parameters 定义一致）。

        返回:
            ToolResult，表示执行结果或错误。
        """

    def to_schema(self) -> dict[str, Any]:
        """转换为 OpenAI function-calling 的工具描述格式。

        返回:
            形如 {"type": "function", "function": {...}} 的字典，可直接传给
            chat.completions.create 的 tools 参数。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
