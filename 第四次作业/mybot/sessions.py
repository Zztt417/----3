"""会话索引模块：维护所有会话的元信息（标题 / 创建时间 / 更新时间）。

会话的**对话内容**仍由 ``memory.ShortTermMemory`` 按「一个会话一个 JSONL」保存；
本模块只维护一个轻量索引文件 ``index.json``，用于在 CLI 里列出、切换、删除会话。
"""

from __future__ import annotations

import json
import random
import string
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# 索引文件名（与会话 JSONL 同目录）
INDEX_FILENAME = "index.json"
# 沿用旧版本的单会话 ID，便于平滑升级
LEGACY_SESSION_ID = "default"
# 未命名会话的占位标题（仅在展示时使用）
UNTITLED = "（未命名）"


def _now() -> str:
    """返回当前时间的 ISO 字符串（精确到微秒）。

    用微秒而不是秒，是为了让「最近使用」排序有稳定依据——同一秒内的
    新建/切换如果时间戳相同，排序会退化成随机顺序，导致 /switch、/delete
    的编号与用户看到的不一致。

    返回:
        形如 "2026-09-27T15:30:45.123456" 的时间戳。
    """
    return datetime.now().isoformat(timespec="microseconds")


def _display_time(value: str) -> str:
    """把存储用的高精度时间戳裁剪成适合展示的形式。

    参数:
        value: 存储的时间戳。

    返回:
        形如 "2026-09-27 15:30:45" 的字符串；无法解析时原样返回。
    """
    if not value:
        return ""
    return value[:19].replace("T", " ")


@dataclass
class SessionMeta:
    """单个会话的元信息。

    属性:
        session_id: 会话 ID（同时是历史文件名与记忆 metadata 中的键）。
        title: 会话标题；为空表示尚未命名。
        created_at: 创建时间。
        updated_at: 最近一次对话时间。
    """

    session_id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""

    def display_title(self) -> str:
        """用于展示的标题。

        返回:
            标题；为空时返回占位文案。
        """
        return self.title or UNTITLED

    def display_updated_at(self) -> str:
        """用于展示的最近活动时间。

        返回:
            形如 "2026-09-27 15:30:45" 的字符串。
        """
        return _display_time(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。"""
        return asdict(self)


class SessionIndex:
    """会话索引：持久化为 ``<sessions_dir>/index.json``。"""

    def __init__(self, sessions_dir: str | Path) -> None:
        """初始化并加载索引。

        参数:
            sessions_dir: 会话数据目录（与历史 JSONL 同目录）。
        """
        self._dir = Path(sessions_dir)
        self._path = self._dir / INDEX_FILENAME
        self._sessions: dict[str, SessionMeta] = {}
        self._load()

    # ---------- 查询 ----------

    def list(self) -> list[SessionMeta]:
        """按更新时间倒序返回所有会话。

        排序键带上 session_id 作为兜底，确保时间戳并列时顺序也是确定的，
        不会因字典遍历顺序不同而让 /switch、/delete 的编号漂移。

        返回:
            SessionMeta 列表（最近使用在前）。
        """
        return sorted(
            self._sessions.values(),
            key=lambda meta: (meta.updated_at, meta.session_id),
            reverse=True,
        )

    def get(self, session_id: str) -> SessionMeta | None:
        """按 ID 取会话元信息。

        参数:
            session_id: 会话 ID。

        返回:
            SessionMeta；不存在时返回 None。
        """
        return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        """判断会话是否存在。

        参数:
            session_id: 会话 ID。

        返回:
            存在返回 True。
        """
        return session_id in self._sessions

    @property
    def count(self) -> int:
        """会话总数。"""
        return len(self._sessions)

    # ---------- 变更 ----------

    def create(self, title: str = "") -> str:
        """新建一个会话。

        参数:
            title: 标题；为空表示稍后根据首条消息自动命名。

        返回:
            新会话的 ID。
        """
        session_id = self._new_id()
        now = _now()
        self._sessions[session_id] = SessionMeta(
            session_id=session_id, title=title.strip(), created_at=now, updated_at=now
        )
        self._save()
        return session_id

    def ensure(self, session_id: str, title: str = "") -> SessionMeta:
        """确保某会话存在于索引中（不存在则登记）。

        参数:
            session_id: 会话 ID。
            title: 标题（仅在新建时使用）。

        返回:
            该会话的元信息。
        """
        meta = self._sessions.get(session_id)
        if meta is None:
            now = _now()
            meta = SessionMeta(
                session_id=session_id, title=title.strip(), created_at=now, updated_at=now
            )
            self._sessions[session_id] = meta
            self._save()
        return meta

    def rename(self, session_id: str, title: str) -> None:
        """设置会话标题。

        参数:
            session_id: 会话 ID。
            title: 新标题。
        """
        meta = self._sessions.get(session_id)
        if meta is None:
            return
        meta.title = title.strip()
        self._save()

    def touch(self, session_id: str) -> None:
        """刷新会话的最近活动时间。

        参数:
            session_id: 会话 ID。
        """
        meta = self._sessions.get(session_id)
        if meta is None:
            self.ensure(session_id)
            return
        meta.updated_at = _now()
        self._save()

    def adopt_legacy(self, history_exists: bool) -> str | None:
        """升级兼容：把旧版本的单会话（default）登记进索引。

        参数:
            history_exists: 旧会话的历史文件是否存在。

        返回:
            登记成功时返回 "default"，否则返回 None。
        """
        if self._sessions or not history_exists:
            return None
        now = _now()
        self._sessions[LEGACY_SESSION_ID] = SessionMeta(
            session_id=LEGACY_SESSION_ID, title="默认会话", created_at=now, updated_at=now
        )
        self._save()
        return LEGACY_SESSION_ID

    def delete(self, session_id: str) -> bool:
        """从索引中删除会话。

        参数:
            session_id: 会话 ID。

        返回:
            True 表示确实删除了。
        """
        if session_id not in self._sessions:
            return False
        self._sessions.pop(session_id, None)
        self._save()
        return True

    # ---------- 内部 ----------

    def _new_id(self) -> str:
        """生成按时间可排序、且不易重复的会话 ID。

        返回:
            形如 "20260927-153045-a1b" 的 ID。
        """
        while True:
            base = time.strftime("%Y%m%d-%H%M%S")
            suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
            candidate = f"{base}-{suffix}"
            if candidate not in self._sessions:
                return candidate

    def _load(self) -> None:
        """从 index.json 加载；文件缺失或损坏时视为空索引。"""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._sessions = {}
            return

        sessions = raw.get("sessions") if isinstance(raw, dict) else raw
        if not isinstance(sessions, list):
            return
        for item in sessions:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                continue
            self._sessions[session_id] = SessionMeta(
                session_id=session_id,
                title=str(item.get("title") or ""),
                created_at=str(item.get("created_at") or ""),
                updated_at=str(item.get("updated_at") or ""),
            )

    def _save(self) -> None:
        """把索引写回磁盘。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {"sessions": [meta.to_dict() for meta in self.list()]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
