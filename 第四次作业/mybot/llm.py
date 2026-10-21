"""LLM 客户端封装：调用 OpenAI 兼容的 Chat Completions 接口（同步 + 流式）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI


@dataclass
class ToolCall:
    """LLM 请求发起的一次工具调用。

    属性:
        id: 工具调用 ID，回填 tool 消息时必须对应。
        name: 要调用的工具名。
        arguments: 原始 JSON 字符串形式的参数。
    """

    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    """一次 LLM 回复的聚合结果。

    属性:
        content: 文本内容（可能为空，例如纯工具调用时）。
        tool_calls: 本次回复请求的工具调用列表。
        finish_reason: 结束原因（如 "stop" / "tool_calls"）。
    """

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class LLMClient:
    """OpenAI 兼容的 LLM 客户端（同步 + 流式）。

    只负责「发请求 + 聚合流式分片」，不包含任何循环或工具执行逻辑。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
    ) -> None:
        """初始化客户端。

        参数:
            api_key: API Key。
            base_url: 接口基础地址。
            model: 模型名（固定从配置传入，客户端内不做切换）。
            temperature: 采样温度。
        """
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """发起一次流式对话请求，并把分片聚合成完整回复。

        本方法不做任何输出（打印是 CLI 的职责），只返回聚合结果。

        参数:
            messages: OpenAI 格式的消息列表（system / user / assistant / tool）。
            tools: 工具 schema 列表；为空表示本次不启用工具。

        返回:
            LLMResponse：聚合后的文本内容与工具调用列表。
        """
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            temperature=self.temperature,
            stream=True,
        )

        content_parts: list[str] = []
        # index -> {id, name, arguments}；流式工具调用需要按 index 分片累积
        calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # 1) 文本增量：仅累积，由调用方决定是否展示
            if delta.content:
                content_parts.append(delta.content)

            # 2) 工具调用增量：id / name 通常只在首片出现，arguments 会分多片
            for tc in delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        tool_calls = [
            ToolCall(id=slot["id"], name=slot["name"], arguments=slot["arguments"])
            for _, slot in sorted(calls.items())
        ]
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    def complete(self, prompt: str, system: str = "") -> str:
        """发起一次非流式补全（不带工具），用于内部辅助任务（如生成摘要）。

        参数:
            prompt: 用户侧提示词。
            system: 可选的 system 提示词。

        返回:
            模型返回的文本内容。
        """
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=False,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def assistant_message(response: LLMResponse) -> dict[str, Any]:
        """把 LLMResponse 序列化为 OpenAI 的 assistant 消息。

        用于把本轮回复回填到消息历史中，使其符合 OpenAI 的多轮工具调用格式。

        参数:
            response: 一次 LLM 回复的聚合结果。

        返回:
            assistant 消息字典；若存在工具调用，会带上 tool_calls 字段。
        """
        message: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments or "{}"},
                }
                for tc in response.tool_calls
            ]
        return message
