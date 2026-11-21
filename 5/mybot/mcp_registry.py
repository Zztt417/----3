"""官方 MCP Registry API 客户端。"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any


REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
SEARCH_TTL_SECONDS = 300


class MCPRegistryError(Exception):
    """MCP Registry 请求失败。"""


class MCPRegistryClient:
    """搜索和读取官方 MCP Registry。"""

    def __init__(self, base_url: str = REGISTRY_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """请求 Registry JSON 接口。"""
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
            if query:
                url = f"{url}?{query}"
        cache_key = url
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "MyBot-MCP-Registry",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MCPRegistryError(f"访问 MCP Registry 失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise MCPRegistryError("MCP Registry 返回格式异常。")
        self._cache[cache_key] = (time.time() + SEARCH_TTL_SECONDS, payload)
        return payload

    def search(self, query: str = "", cursor: str = "", limit: int = 20) -> dict[str, Any]:
        """搜索 MCP 服务。"""
        query = (query or "").strip()
        if query and len(query) < 3:
            raise MCPRegistryError("搜索词至少需要 3 个字符。")
        payload = self._get(
            "/v0/servers",
            {
                "search": query,
                "cursor": cursor,
                "limit": max(1, min(int(limit), 50)),
                "version": "latest",
            },
        )
        items: list[dict[str, Any]] = []
        for entry in payload.get("servers", []) or []:
            server = entry.get("server") if isinstance(entry, dict) else None
            if isinstance(server, dict):
                items.append(server)
        return {
            "items": items,
            "next_cursor": (payload.get("metadata") or {}).get("nextCursor", ""),
        }

    def detail(self, name: str, version: str = "latest") -> dict[str, Any]:
        """读取指定服务版本详情。"""
        name = (name or "").strip()
        if not name:
            raise MCPRegistryError("MCP 服务名称不能为空。")
        encoded_name = urllib.parse.quote(name, safe="")
        encoded_version = urllib.parse.quote((version or "latest").strip(), safe="")
        payload = self._get(f"/v0/servers/{encoded_name}/versions/{encoded_version}")
        server = payload.get("server") if isinstance(payload, dict) else None
        if not isinstance(server, dict):
            raise MCPRegistryError("MCP 服务详情格式异常。")
        return server