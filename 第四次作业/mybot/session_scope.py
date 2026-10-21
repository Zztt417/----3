"""会话作用域模块：保存「当前正在处理的会话 ID」，供工具层读取。

工具实例在启动时只创建一次，而会话会随用户切换而改变；因此用 ContextVar
传递「当前会话」，避免把 session_id 做成工具参数——那样模型就得自己提供，
既不可靠，也容易被对话内容带偏。
"""

from __future__ import annotations

from contextvars import ContextVar

# 默认会话 ID：单会话场景（未启用会话管理）下使用
DEFAULT_SESSION_ID = "default"

_current_session_id: ContextVar[str] = ContextVar(
    "current_session_id", default=DEFAULT_SESSION_ID
)


def set_current_session(session_id: str) -> None:
    """设置当前会话 ID。

    参数:
        session_id: 会话 ID；为空时回退为默认值。
    """
    _current_session_id.set(session_id or DEFAULT_SESSION_ID)


def current_session() -> str:
    """获取当前会话 ID。

    返回:
        当前会话 ID；从未设置过时为 "default"。
    """
    return _current_session_id.get()
