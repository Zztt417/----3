"""短期记忆模块：会话消息的 JSONL 持久化与「条数触发」的摘要压缩。"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

# 摘要压缩用的提示词
COMPRESS_PROMPT = """请把下面的对话历史压缩成一段简洁的中文摘要。
要求：
1. 保留关键事实、用户身份与偏好、已确认的结论、未完成的事项。
2. 去掉寒暄、重复与无关细节。
3. 只输出摘要正文，不要标题、不要解释。

对话历史：
{history}
"""

# 会话键里不安全的字符（用于生成文件名）
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_filename(key: str) -> str:
    """把任意会话键转成安全的文件名。

    参数:
        key: 会话键（如 "default" 或飞书 chat_id）。

    返回:
        仅含 [A-Za-z0-9_.-] 的文件名。
    """
    return _UNSAFE_NAME_RE.sub("_", key) or "default"


class Session:
    """单个会话的短期记忆。

    结构 = 基础 system 提示词 + 历史摘要 + 最近若干条原始消息。
    落盘格式为 JSONL：首行可选摘要记录，其后每行一条消息。
    """

    def __init__(
        self,
        key: str,
        base_prompt: str,
        path: Path,
        max_messages: int,
        keep_recent: int,
        llm: Any,
    ) -> None:
        """初始化并尝试从磁盘加载。

        参数:
            key: 会话键。
            base_prompt: 基础 system 提示词。
            path: 该会话的 JSONL 文件路径。
            max_messages: 触发压缩的消息条数阈值。
            keep_recent: 压缩后保留的最近消息条数。
            llm: LLM 客户端（仅用于生成摘要）。
        """
        self.key = key
        self.summary = ""
        self.messages: list[dict[str, Any]] = []
        self._base_prompt = base_prompt
        self._path = path
        self._max_messages = max_messages
        self._keep_recent = keep_recent
        self._llm = llm
        self._load()

    def system_content(self, extra: str = "") -> str:
        """拼接本轮 system 内容（不落盘，属请求期临时状态）。

        参数:
            extra: 本轮附加内容，如检索到的长期记忆。

        返回:
            基础提示词 + 历史摘要 + extra 拼接后的文本。
        """
        parts = [self._base_prompt]
        if self.summary:
            parts.append(f"【历史对话摘要】\n{self.summary}")
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    def append(self, message: dict[str, Any]) -> None:
        """追加一条消息并立即落盘。

        注意：这里**不**触发压缩——压缩只在回合开始时做，
        以免在 ReAct 中途切断 assistant(tool_calls) 与其 tool 结果的配对。

        参数:
            message: OpenAI 格式的消息。
        """
        self.messages.append(message)
        self._append_line({"type": "message", "message": message})

    def compress_if_needed(self) -> bool:
        """若消息条数超过阈值，则把较早部分摘要压缩掉。

        切点规则：目标保留最近 keep_recent 条，并从该位置向后找到第一条
        role=="user" 的消息作为切点，保证保留段从用户消息开始、
        不会切断 tool_calls 与 tool 结果的配对。

        返回:
            True 表示发生了压缩，False 表示未触发。
        """
        if self._llm is None or len(self.messages) <= self._max_messages:
            return False

        target = max(0, len(self.messages) - self._keep_recent)
        cut = target
        for index in range(target, len(self.messages)):
            if self.messages[index].get("role") == "user":
                cut = index
                break
        old = self.messages[:cut]
        if not old:
            return False

        history_text = "\n".join(
            f"{message.get('role')}: {str(message.get('content', ''))[:2000]}" for message in old
        )
        try:
            new_summary = self._llm.complete(COMPRESS_PROMPT.format(history=history_text))
        except Exception:
            return False  # 摘要失败就放弃本次压缩，不影响对话

        self.summary = f"{self.summary}\n{new_summary}".strip() if self.summary else new_summary
        self.messages = self.messages[cut:]
        self._persist_all()
        return True

    def reset(self) -> None:
        """清空该会话的摘要与消息，并删除落盘文件。"""
        self.summary = ""
        self.messages = []
        self._path.unlink(missing_ok=True)

    # ---------- 内部：持久化 ----------

    def _load(self) -> None:
        """从 JSONL 文件恢复摘要与消息；文件不存在或损坏时安静跳过。"""
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("type") == "summary":
                    self.summary = record.get("content", "")
                elif record.get("type") == "message":
                    self.messages.append(record["message"])
        except Exception:
            self.summary = ""
            self.messages = []

    def _append_line(self, record: dict[str, Any]) -> None:
        """向文件追加一行 JSON。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _persist_all(self) -> None:
        """压缩后整体重写文件（摘要行 + 保留的消息行）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if self.summary:
            lines.append(
                json.dumps({"type": "summary", "content": self.summary}, ensure_ascii=False)
            )
        for message in self.messages:
            lines.append(json.dumps({"type": "message", "message": message}, ensure_ascii=False))
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ShortTermMemory:
    """短期记忆管理器：按会话键维护多个 Session，带 LRU 上限。"""

    def __init__(
        self,
        system_prompt: str,
        sessions_dir: str | Path,
        llm: Any = None,
        max_messages: int = 30,
        keep_recent: int = 10,
        max_sessions: int = 200,
    ) -> None:
        """初始化。

        参数:
            system_prompt: 每个会话的基础 system 提示词。
            sessions_dir: 会话文件目录。
            llm: LLM 客户端（用于摘要压缩；为 None 时不做压缩）。
            max_messages: 触发压缩的消息条数阈值。
            keep_recent: 压缩后保留的最近消息条数。
            max_sessions: 内存中最多缓存的会话数（LRU 淘汰）。
        """
        self._system_prompt = system_prompt
        self._sessions_dir = Path(sessions_dir)
        self._llm = llm
        self._max_messages = max_messages
        self._keep_recent = keep_recent
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def session(self, key: str) -> Session:
        """获取（必要时加载或新建）指定会话。

        参数:
            key: 会话键（CLI 用 "default"，飞书用 chat_id）。

        返回:
            该会话的 Session 实例。
        """
        session = self._sessions.get(key)
        if session is None:
            session = Session(
                key=key,
                base_prompt=self._system_prompt,
                path=self._sessions_dir / f"{_safe_filename(key)}.jsonl",
                max_messages=self._max_messages,
                keep_recent=self._keep_recent,
                llm=self._llm,
            )
            self._sessions[key] = session
        self._sessions.move_to_end(key)
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return session

    def reset(self, key: str) -> None:
        """清空指定会话的记忆（含落盘文件）。

        参数:
            key: 会话键。
        """
        session = self._sessions.pop(key, None)
        if session is not None:
            session.reset()
        else:
            (self._sessions_dir / f"{_safe_filename(key)}.jsonl").unlink(missing_ok=True)

    @property
    def session_count(self) -> int:
        """当前缓存的会话数。"""
        return len(self._sessions)
