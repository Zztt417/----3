"""LLM 客户端封装：调用 OpenAI 兼容的 Chat Completions 接口（同步 + 流式）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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
        timeout: float = 60.0,
        max_retries: int = 1,
    ) -> None:
        """初始化客户端。

        参数:
            api_key: API Key。
            base_url: 接口基础地址。
            model: 模型名（固定从配置传入，客户端内不做切换）。
            temperature: 采样温度。
            timeout: 单次 HTTP 请求超时秒数。
            max_retries: OpenAI SDK 的自动重试次数。
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = self._create_client()

    @property
    def api_key_configured(self) -> bool:
        """当前客户端是否持有非空 API Key。"""
        return bool(self.api_key.strip())

    def _create_client(self) -> OpenAI:
        """按当前配置创建 OpenAI 兼容客户端。"""
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    def reconfigure(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float | None = None,
    ) -> None:
        """原地更新连接配置，使 Agent、记忆和热点分析共享的新客户端立即生效。

        参数:
            api_key: 新的 API Key。
            base_url: 新的接口基础地址。
            model: 新的模型名称。
            temperature: 可选的新采样温度；不传则保持原值。
        """
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        if temperature is not None:
            self.temperature = temperature
        self._client = self._create_client()

    def test_connection(self) -> str:
        """发送一次最小请求，验证地址、密钥和模型是否可用。

        返回:
            模型返回的短文本。

        异常:
            Exception: 网络、鉴权、模型或接口格式错误会原样抛出，由 API 层转换。
        """
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            temperature=0.0,
            max_tokens=4,
            stream=False,
        )
        if not response.choices:
            raise RuntimeError("接口返回成功，但没有 choices 内容。")
        return (response.choices[0].message.content or "").strip()

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """发起一次流式对话请求，并把分片聚合成完整回复。

        本方法不做任何输出（打印是 CLI 的职责），只返回聚合结果。

        参数:
            messages: OpenAI 格式的消息列表（system / user / assistant / tool）。
            tools: 工具 schema 列表；为空表示本次不启用工具。
            on_token: 可选的文本分片回调；用于 SSE 流式输出。
            model: 可选的本次请求模型；不传时使用客户端默认模型。

        返回:
            LLMResponse：聚合后的文本内容与工具调用列表。
        """
        stream = self._client.chat.completions.create(
            model=model or self.model,
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
                if on_token is not None:
                    on_token(delta.content)

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
