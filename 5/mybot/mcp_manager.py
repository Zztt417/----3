"""多 MCP 服务的配置、连接、工具命名空间与生命周期管理。"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mcp_client import MCPClient, MCPHTTPClient, MCPToolWrapper
from .tools.registry import ToolRegistry


DEFAULT_MCP_CONFIG_PATH = Path.home() / ".mybot" / "mcp_servers.json"


class MCPManagerError(Exception):
    """MCP 配置或连接失败。"""


@dataclass
class ManagedServer:
    """一个已安装 MCP 服务的运行时状态。"""

    config: dict[str, Any]
    client: Any | None = None
    tool_names: list[str] = field(default_factory=list)
    connected: bool = False
    error: str = ""


def _safe_identifier(value: str) -> str:
    """生成用于工具名和服务 ID 的安全片段。"""
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_")
    return value or "mcp"


def _get_mcp_config_path() -> Path:
    """读取 MCP 配置文件路径。"""
    configured = os.getenv("MYBOT_MCP_CONFIG", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_MCP_CONFIG_PATH


class MCPManager:
    """管理多个 stdio / Streamable HTTP MCP 服务。"""

    def __init__(self, registry: ToolRegistry | None = None, timeout: float = 60.0) -> None:
        """初始化管理器并加载本地配置。"""
        self.registry = registry
        self.timeout = timeout
        self.config_path = _get_mcp_config_path()
        self._servers: dict[str, ManagedServer] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        """加载本地 MCP 服务配置。"""
        payload: dict[str, Any] = {"servers": []}
        if self.config_path.exists():
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("servers"), list):
                    payload = raw
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                payload = {"servers": []}
        for config in payload.get("servers", []):
            if not isinstance(config, dict):
                continue
            server_id = str(config.get("id", "")).strip()
            if not server_id:
                continue
            self._servers[server_id] = ManagedServer(config=config)

    def _save(self) -> None:
        """原子保存 MCP 服务配置。"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.config_path.parent.chmod(stat.S_IRWXU)
        except OSError:
            pass
        payload = {"servers": [item.config for item in self._servers.values()]}
        temp_path = self.config_path.with_name(f".{self.config_path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temp_path, self.config_path)
        try:
            self.config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def list_servers(self) -> list[dict[str, Any]]:
        """返回已安装服务及连接状态。"""
        with self._lock:
            result: list[dict[str, Any]] = []
            for server_id, item in self._servers.items():
                config = self._public_config(item.config)
                result.append(
                    {
                        **config,
                        "id": server_id,
                        "connected": item.connected,
                        "tool_names": list(item.tool_names),
                        "error": item.error,
                    }
                )
            return result

    def install_from_registry(
        self,
        server: dict[str, Any],
        transport: str,
        package_index: int = 0,
        remote_index: int = 0,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """把 Registry 服务转换为本地配置并启动。"""
        name = str(server.get("name", "") or "").strip()
        if not name:
            raise MCPManagerError("MCP 服务名称不能为空。")
        server_id = self._unique_server_id(name)
        config: dict[str, Any] = {
            "id": server_id,
            "name": str(server.get("title") or name.split("/")[-1] or server_id),
            "registry_name": name,
            "version": str(server.get("version") or ""),
            "transport": transport,
            "enabled": True,
            "tools": list(tools or []),
            "timeout": self.timeout,
        }
        if transport == "streamable-http":
            remotes = [item for item in server.get("remotes", []) if isinstance(item, dict)]
            http_remotes = [item for item in remotes if item.get("type") == "streamable-http"]
            remote_list = http_remotes or remotes
            if not remote_list or remote_index < 0 or remote_index >= len(http_remotes or remote_list):
                raise MCPManagerError("没有可用的 Streamable HTTP 端点。")
            remote = remote_list[remote_index]
            if not remote.get("url"):
                raise MCPManagerError("该 MCP 服务没有可用的 Streamable HTTP 端点。")
            config.update(
                {
                    "url": str(remote.get("url", "")).strip(),
                    "headers": dict(headers or {}),
                }
            )
        elif transport == "stdio":
            package = self._package_for(server, package_index)
            command, args = self._command_for_package(package)
            config.update(
                {
                    "command": command,
                    "args": args,
                    "env": dict(env or {}),
                }
            )
        else:
            raise MCPManagerError(f"不支持的 MCP transport：{transport}")

        with self._lock:
            self._servers[server_id] = ManagedServer(config=config)
            self._save()
        self.start_server(server_id)
        return next(item for item in self.list_servers() if item["id"] == server_id)

    def _unique_server_id(self, name: str) -> str:
        """从 Registry 名称生成唯一本地 ID。"""
        base = _safe_identifier(name.split("/")[-1])[:48] or "mcp"
        with self._lock:
            if base not in self._servers:
                return base
            index = 2
            while f"{base}-{index}" in self._servers:
                index += 1
            return f"{base}-{index}"

    def _package_for(self, server: dict[str, Any], index: int) -> dict[str, Any]:
        """取指定包描述。"""
        packages = [item for item in server.get("packages", []) if isinstance(item, dict)]
        if not packages:
            raise MCPManagerError("该 MCP 服务没有可安装的包。")
        if index < 0 or index >= len(packages):
            raise MCPManagerError("MCP 包序号超出范围。")
        return packages[index]

    def _command_for_package(self, package: dict[str, Any]) -> tuple[str, list[str]]:
        """根据 Registry 包元数据生成启动命令。"""
        registry_type = str(package.get("registryType", "")).lower()
        identifier = str(package.get("identifier", "")).strip()
        version = str(package.get("version", "")).strip()
        if not identifier:
            raise MCPManagerError("MCP 包缺少 identifier。")
        positional_args = []
        for arg in package.get("runtimeArguments", []) or []:
            if isinstance(arg, dict) and arg.get("type") == "positional" and arg.get("value") is not None:
                positional_args.append(str(arg.get("value")))

        if registry_type == "npm":
            command = str(package.get("runtimeHint") or "npx").strip()
            args = positional_args or ["-y"]
            if "-y" not in args and "--yes" not in args:
                args = ["-y", *args]
            args.append(f"{identifier}@{version}" if version else identifier)
            return command, args
        if registry_type in {"pypi", "python"}:
            command = str(package.get("runtimeHint") or "uvx").strip()
            args = positional_args.copy()
            args.append(f"{identifier}=={version}" if version else identifier)
            return command, args
        if registry_type in {"oci", "docker"}:
            image = f"{identifier}:{version}" if version else identifier
            return "docker", ["run", "-i", "--rm", *positional_args, image]
        raise MCPManagerError(f"暂不支持自动安装 registryType={registry_type} 的 MCP 包。")

    def start_server(self, server_id: str) -> dict[str, Any]:
        """启动一个已安装服务并注册其工具。"""
        with self._lock:
            item = self._servers.get(server_id)
            if item is None:
                raise MCPManagerError("MCP 服务不存在。")
            if item.client is not None:
                return self._status_for(server_id)
            config = item.config
            client: Any | None = None
            try:
                timeout = float(config.get("timeout") or self.timeout)
                transport = str(config.get("transport", "stdio"))
                if transport == "stdio":
                    command = str(config.get("command", "")).strip()
                    args = [str(value) for value in (config.get("args") or [])]
                    log_path = Path.home() / ".mybot" / "mcp" / f"{server_id}.log"
                    client = MCPClient(
                        env={str(k): str(v) for k, v in (config.get("env") or {}).items()},
                        timeout=timeout,
                        errlog_path=log_path,
                        command=command,
                        args=args,
                    )
                elif transport == "streamable-http":
                    client = MCPHTTPClient(
                        str(config.get("url", "")),
                        headers={str(k): str(v) for k, v in (config.get("headers") or {}).items()},
                        timeout=timeout,
                    )
                else:
                    raise MCPManagerError(f"不支持的 transport：{transport}")
                client.start()
                discovered = client.list_tools()
                allowed = {str(name) for name in (config.get("tools") or []) if str(name).strip()}
                selected = [tool for tool in discovered if not allowed or str(tool.name) in allowed]
                safe_server = _safe_identifier(server_id)
                public_names: list[str] = []
                for tool in selected:
                    original = str(tool.name)
                    safe_tool = _safe_identifier(original)
                    public_name = f"mcp__{safe_server}__{safe_tool}"[:64]
                    if self.registry is not None:
                        self.registry.register(
                            MCPToolWrapper(client, tool, public_name=public_name)
                        )
                    public_names.append(public_name)
                item.client = client
                item.tool_names = public_names
                item.connected = True
                item.error = ""
                return self._status_for(server_id)
            except Exception as exc:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                item.client = None
                item.tool_names = []
                item.connected = False
                item.error = f"{type(exc).__name__}: {exc}"
                raise MCPManagerError(item.error) from exc

    def stop_server(self, server_id: str) -> dict[str, Any]:
        """停止服务并注销其工具。"""
        with self._lock:
            item = self._servers.get(server_id)
            if item is None:
                raise MCPManagerError("MCP 服务不存在。")
            if self.registry is not None:
                for name in item.tool_names:
                    self.registry.unregister(name)
            if item.client is not None:
                try:
                    item.client.close()
                except Exception:
                    pass
            item.client = None
            item.tool_names = []
            item.connected = False
            item.error = ""
            return self._status_for(server_id)

    def restart_server(self, server_id: str) -> dict[str, Any]:
        """重启 MCP 服务。"""
        self.stop_server(server_id)
        return self.start_server(server_id)

    def set_enabled(self, server_id: str, enabled: bool) -> dict[str, Any]:
        """启用或停用 MCP 服务。"""
        with self._lock:
            item = self._servers.get(server_id)
            if item is None:
                raise MCPManagerError("MCP 服务不存在。")
            item.config["enabled"] = bool(enabled)
            self._save()
        if enabled:
            return self.start_server(server_id)
        return self.stop_server(server_id)

    def remove_server(self, server_id: str) -> None:
        """删除 MCP 服务配置。"""
        with self._lock:
            item = self._servers.get(server_id)
            if item is None:
                raise MCPManagerError("MCP 服务不存在。")
        self.stop_server(server_id)
        with self._lock:
            self._servers.pop(server_id, None)
            self._save()

    def start_enabled(self) -> None:
        """启动所有启用的 MCP 服务；单个失败不影响其他服务。"""
        for server_id, item in list(self._servers.items()):
            if bool(item.config.get("enabled", False)):
                try:
                    self.start_server(server_id)
                except Exception:
                    continue

    def close_all(self) -> None:
        """关闭所有 MCP 连接。"""
        for server_id in list(self._servers):
            try:
                self.stop_server(server_id)
            except Exception:
                continue

    def get_tools(self, server_id: str) -> list[str]:
        """返回某个服务的公开工具名。"""
        with self._lock:
            item = self._servers.get(server_id)
            if item is None:
                raise MCPManagerError("MCP 服务不存在。")
            return list(item.tool_names)

    def _public_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """返回不含凭据的服务配置。"""
        result = dict(config)
        result["env"] = {
            str(key): ("已配置" if value else "")
            for key, value in (config.get("env") or {}).items()
        }
        result["headers"] = {
            str(key): ("已配置" if value else "")
            for key, value in (config.get("headers") or {}).items()
        }
        return result

    def _status_for(self, server_id: str) -> dict[str, Any]:
        """构造单个服务状态。"""
        item = self._servers[server_id]
        return {
            **self._public_config(item.config),
            "id": server_id,
            "connected": item.connected,
            "tool_names": list(item.tool_names),
            "error": item.error,
        }

    @staticmethod
    def _quote_arg(value: str) -> str:
        """对命令行参数做最小引号保护。"""
        import shlex

        return shlex.quote(value) if os.name != "nt" else f'"{value}"' if " " in value else value