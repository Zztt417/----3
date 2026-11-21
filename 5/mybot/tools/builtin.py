"""内置工具模块：提供 read_file / write_file / run_shell 三个基础工具。

注意：这些工具直接在用户本机执行文件读写与命令，没有沙箱隔离，
仅用于学习与本地使用，请勿在不可信的输入环境下启用。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

# 单个工具返回内容的最大字符数，超出则截断，避免撑爆 LLM 上下文
MAX_OUTPUT_CHARS = 20_000


def _truncate(text: str) -> str:
    """截断过长文本。

    参数:
        text: 原始文本。

    返回:
        若超过 MAX_OUTPUT_CHARS 则截断并追加提示，否则原样返回。
    """
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_OUTPUT_CHARS
    return text[:MAX_OUTPUT_CHARS] + f"\n...（输出过长，已截断 {omitted} 个字符）"


class ReadFileTool(Tool):
    """读取文本文件内容的工具。"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取指定路径的文本文件内容，返回文件全文。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径（相对或绝对路径）"},
            },
            "required": ["path"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """读取文件。

        参数:
            **kwargs: 必须包含 path（str）。

        返回:
            ToolResult，content 为文件内容；文件不存在或读取失败时为错误结果。
        """
        path = Path(str(kwargs.get("path", ""))).expanduser()
        if not path.exists():
            return ToolResult.error(f"错误：文件不存在：{path}")
        if not path.is_file():
            return ToolResult.error(f"错误：路径不是文件：{path}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.error(f"错误：读取文件失败：{exc}")
        return ToolResult(content=_truncate(content))


class WriteFileTool(Tool):
    """写入文本到文件的工具（覆盖写入，自动创建父目录）。"""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "把文本内容写入指定路径的文件。若文件已存在会覆盖，若父目录不存在会自动创建。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径（相对或绝对路径）"},
                "content": {"type": "string", "description": "要写入的文本内容"},
            },
            "required": ["path", "content"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """写入文件。

        参数:
            **kwargs: 必须包含 path（str）与 content（str）。

        返回:
            ToolResult，成功时 content 为写入结果说明；失败时为错误结果。
        """
        path = Path(str(kwargs.get("path", ""))).expanduser()
        content = str(kwargs.get("content", ""))
        try:
            if path.parent and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.error(f"错误：写入文件失败：{exc}")
        return ToolResult(content=f"已写入 {len(content)} 个字符到 {path}")


class RunShellTool(Tool):
    """执行 shell 命令的工具。"""

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 60

    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return (
            "在本机执行一条 shell 命令并返回输出。"
            "Windows 上使用 cmd，Linux/macOS 上使用 /bin/sh。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {
                    "type": "integer",
                    "description": f"超时时间（秒），默认 {self.DEFAULT_TIMEOUT}",
                },
            },
            "required": ["command"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """执行命令。

        参数:
            **kwargs: 必须包含 command（str），可选 timeout（int）。

        返回:
            ToolResult，content 为 stdout/stderr 与退出码；超时或失败时为错误结果。
        """
        command = str(kwargs.get("command", ""))
        if not command.strip():
            return ToolResult.error("错误：command 不能为空。")

        timeout = int(kwargs.get("timeout", self.DEFAULT_TIMEOUT) or self.DEFAULT_TIMEOUT)

        try:
            completed = subprocess.run(
                command,
                shell=True,  # 跨平台最简写法：Windows 走 cmd，Unix 走 /bin/sh
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.error(f"命令超时（>{timeout}s）：{command}")
        except OSError as exc:
            return ToolResult.error(f"错误：命令执行失败：{exc}")

        # 拼装输出：stdout + stderr + 退出码
        parts: list[str] = []
        if completed.stdout:
            parts.append(completed.stdout.rstrip())
        if completed.stderr:
            parts.append("[stderr]\n" + completed.stderr.rstrip())
        parts.append(f"[exit code: {completed.returncode}]")
        output = "\n".join(parts)

        if completed.returncode != 0:
            # 非 0 退出码视为错误，但仍返回完整输出供 LLM 判断
            return ToolResult.error(output)
        return ToolResult(content=_truncate(output))
