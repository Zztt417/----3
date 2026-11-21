"""主流 OpenAI 兼容模型服务预设。

前端只提交 provider_id 和 model，base_url 由本模块解析，避免用户手填地址。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """一个模型服务商预设。"""

    id: str
    name: str
    base_url: str
    models: tuple[str, ...]


PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
    ),
    ProviderPreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderPreset(
        id="qwen",
        name="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=("qwen-plus", "qwen-max", "qwen-turbo"),
    ),
    ProviderPreset(
        id="zhipu",
        name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=("glm-4-flash", "glm-4-air", "glm-4-plus"),
    ),
    ProviderPreset(
        id="moonshot",
        name="Moonshot Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
    ),
    ProviderPreset(
        id="siliconflow",
        name="硅基流动",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct",
        ),
    ),
    ProviderPreset(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models=("openai/gpt-4o-mini", "deepseek/deepseek-chat", "anthropic/claude-3.5-sonnet"),
    ),
    ProviderPreset(
        id="ollama",
        name="Ollama 本地",
        base_url="http://127.0.0.1:11434/v1",
        models=("qwen2.5:7b", "llama3.1:8b", "deepseek-r1:7b"),
    ),
)

PROVIDER_BY_ID = {provider.id: provider for provider in PROVIDERS}


def get_provider(provider_id: str) -> ProviderPreset | None:
    """按稳定 ID 获取服务商预设。"""
    return PROVIDER_BY_ID.get((provider_id or "").strip())


def detect_provider_id(base_url: str) -> str:
    """根据 Base URL 检测服务商；无法匹配时返回 custom。"""
    normalized = (base_url or "").strip().rstrip("/")
    for provider in PROVIDERS:
        if provider.base_url.rstrip("/") == normalized:
            return provider.id
    return "custom"


def provider_payloads() -> list[dict[str, object]]:
    """返回给前端的服务商与模型菜单数据。"""
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "models": list(provider.models[:3]),
        }
        for provider in PROVIDERS
    ]