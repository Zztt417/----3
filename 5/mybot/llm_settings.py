"""本地 LLM 配置的读取、校验与持久化。

配置文件默认放在用户目录 ``~/.mybot/llm_config.json``，不会进入项目仓库。
界面只让用户选择预设服务商/模型并填写 API Key，Base URL 由服务商预设自动写入。
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG_PATH = Path.home() / ".mybot" / "llm_config.json"


@dataclass(frozen=True)
class StoredLLMSettings:
    """界面保存的 LLM 服务配置。"""

    api_key: str
    provider_id: str = ""
    base_url: str = ""
    model: str = ""
    model_options: tuple[str, ...] = field(default_factory=tuple)


def get_llm_config_path() -> Path:
    """返回实际使用的 LLM 配置文件路径。"""
    configured = os.getenv("MYBOT_LLM_CONFIG", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CONFIG_PATH


def validate_llm_api_key(api_key: str) -> str:
    """校验并规范化用户填写的 API Key。"""
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError("API Key 不能为空。")
    if any(ch in api_key for ch in "\r\n"):
        raise ValueError("API Key 不能包含换行。")
    if len(api_key) > 1000:
        raise ValueError("API Key 长度超出限制。")
    return api_key


def validate_base_url(base_url: str) -> str:
    """校验 OpenAI 兼容接口地址。"""
    base_url = str(base_url or "").strip().rstrip("/")
    if not base_url or any(ch in base_url for ch in "\r\n\t "):
        raise ValueError("模型接口地址不合法。")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("模型接口地址必须是完整的 http:// 或 https:// 地址。")
    if len(base_url) > 500:
        raise ValueError("模型接口地址长度超出限制。")
    return base_url


def normalize_model_options(model: str, model_options: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """把模型选项限制为最多 3 个，并保证当前模型位于第一项。"""
    ordered: list[str] = []
    for item in (model, *model_options):
        value = str(item or "").strip()
        if value and value not in ordered:
            ordered.append(value)
    if not ordered:
        raise ValueError("模型名称不能为空。")
    return tuple(ordered[:3])


def load_stored_llm_settings() -> StoredLLMSettings | None:
    """读取界面保存的配置；文件缺失或内容不合法时返回 None。"""
    path = get_llm_config_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        api_key = validate_llm_api_key(payload.get("api_key", ""))
        raw_options = payload.get("model_options", [])
        options = raw_options if isinstance(raw_options, list) else []
        model = str(payload.get("model", "") or "").strip()
        normalized_options = normalize_model_options(model, options) if model else ()
        base_url = str(payload.get("base_url", "") or "").strip().rstrip("/")
        if base_url:
            base_url = validate_base_url(base_url)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return StoredLLMSettings(
        api_key=api_key,
        provider_id=str(payload.get("provider_id", "") or "").strip(),
        base_url=base_url,
        model=model,
        model_options=normalized_options,
    )


def save_stored_llm_settings(
    provider_id: str,
    base_url: str,
    model: str,
    model_options: list[str] | tuple[str, ...],
    api_key: str,
) -> Path:
    """原子写入完整 LLM 配置，并尽量收紧文件权限。"""
    provider_id = str(provider_id or "").strip()
    base_url = validate_base_url(base_url)
    model = str(model or "").strip()
    options = normalize_model_options(model, model_options)
    api_key = validate_llm_api_key(api_key)
    if not provider_id:
        raise ValueError("服务商不能为空。")

    path = get_llm_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass

    payload = {
        "provider_id": provider_id,
        "base_url": base_url,
        "model": model,
        "model_options": list(options),
        "api_key": api_key,
    }
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(temp_path, path)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path