"""CLI 入口模块：提供命令行 REPL 交互循环与会话（历史对话）管理命令。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .agent import SYSTEM_PROMPT, Agent
from .config import load_config, load_mcp_config, load_memory_config
from .llm import LLMClient
from .long_memory import create_long_term_memory
from .mcp_client import connect_mcp_tools
from .memory import ShortTermMemory
from .session_scope import DEFAULT_SESSION_ID
from .sessions import SessionIndex
from .tools import create_default_registry
from .tools.base import Tool

BANNER = """========================================
  我的 CLI Agent 助手（仿 nanobot 极简版）
  输入内容回车执行；/help 查看命令；exit 或 quit 退出
========================================"""

HELP_TEXT = """可用命令：
  /sessions          列出所有会话
  /new [标题]        新建会话并切换过去
  /switch <编号>     切换到指定会话（并显示其近期对话）
  /delete <编号> -y  删除会话（含其长期记忆；必须带 -y 才真正执行）
  /history [N]       显示当前会话最近 N 条对话（默认 6）
  /help              显示本帮助
  exit / quit        退出程序"""

# /history 默认显示的历史条数
HISTORY_PREVIEW = 6
# 自动生成会话标题时截取的用户输入长度
AUTO_TITLE_CHARS = 20


def _print_sessions(sessions: SessionIndex, current_session_id: str) -> None:
    """打印会话列表。

    参数:
        sessions: 会话索引。
        current_session_id: 当前会话 ID（用于标记）。
    """
    metas = sessions.list()
    if not metas:
        print("（还没有任何会话）")
        return
    print("会话列表（最近使用在前）：")
    for index, meta in enumerate(metas, start=1):
        marker = "  ← 当前" if meta.session_id == current_session_id else ""
        print(f"  {index}. {meta.display_title()}   更新于 {meta.display_updated_at()}{marker}")
    print("用 /switch <编号> 切换，/delete <编号> -y 删除。")


def _render_history(short_term: ShortTermMemory | None, session_id: str, limit: int = HISTORY_PREVIEW) -> None:
    """把某会话的近期对话渲染到终端。

    参数:
        short_term: 短期记忆管理器；为 None 时不做任何事。
        session_id: 会话 ID。
        limit: 最多显示多少条。
    """
    if short_term is None:
        return
    messages = short_term.session(session_id).messages
    # 只显示有内容的用户/助手消息，跳过工具往返消息
    visible = [
        message
        for message in messages
        if message.get("role") in {"user", "assistant"} and str(message.get("content", "")).strip()
    ]
    if not visible:
        print("（该会话还没有对话记录）")
        return
    print(f"—— 最近 {min(limit, len(visible))} 条对话 ——")
    for message in visible[-limit:]:
        role = "你" if message.get("role") == "user" else "助手"
        content = str(message.get("content", "")).strip().replace("\n", " ")
        print(f"{role} > {content[:200]}")


def _resolve_index(argument: str, total: int) -> int | None:
    """把用户输入的「编号」解析为 0 基下标。

    参数:
        argument: 用户输入，如 "2"。
        total: 会话总数。

    返回:
        0 基下标；非法时返回 None。
    """
    text = argument.strip()
    if not text.isdigit():
        return None
    index = int(text) - 1
    if index < 0 or index >= total:
        return None
    return index


def _print_status(
    sessions: SessionIndex | None, current_session_id: str, long_term: object | None
) -> None:
    """打印当前会话状态。

    参数:
        sessions: 会话索引；为 None 表示会话管理不可用。
        current_session_id: 当前会话 ID。
        long_term: 长期记忆实例（可为 None）。
    """
    if sessions is None:
        return
    meta = sessions.get(current_session_id)
    title = meta.display_title() if meta is not None else current_session_id
    count = long_term.count(current_session_id) if long_term is not None else 0
    print(f"会话：{title}（{current_session_id}）    本会话长期记忆：{count} 条")


def _bootstrap_session(sessions: SessionIndex, sessions_dir: str) -> str:
    """确定启动时使用的会话。

    参数:
        sessions: 会话索引。
        sessions_dir: 会话数据目录。

    返回:
        要使用的会话 ID。
    """
    # 1) 索引为空但存在旧版 default.jsonl → 继承旧会话，避免历史"凭空消失"
    legacy_history = Path(sessions_dir) / f"{DEFAULT_SESSION_ID}.jsonl"
    adopted = sessions.adopt_legacy(legacy_history.exists())
    if adopted:
        print(f"[会话] 已把旧版默认会话登记为「默认会话」（{adopted}）")
        return adopted
    # 2) 索引为空 → 新建一个
    if sessions.count == 0:
        return sessions.create()
    # 3) 否则用最近使用过的那个
    return sessions.list()[0].session_id


def _handle_command(
    command_line: str,
    sessions: SessionIndex | None,
    short_term: ShortTermMemory | None,
    long_term: object | None,
    current_session_id: str,
) -> str:
    """处理一条斜杠命令。

    参数:
        command_line: 以 / 开头的完整命令行。
        sessions: 会话索引；为 None 表示会话管理不可用。
        short_term: 短期记忆管理器。
        long_term: 长期记忆实例。
        current_session_id: 当前会话 ID。

    返回:
        处理后的当前会话 ID（可能因切换/新建/删除而改变）。
    """
    parts = command_line.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command in {"/help", "/?"}:
        print(HELP_TEXT)
        return current_session_id

    if sessions is None:
        print("记忆模块已禁用（MEMORY_ENABLED=false），会话管理不可用。")
        return current_session_id

    if command == "/sessions":
        _print_sessions(sessions, current_session_id)
        return current_session_id

    if command == "/new":
        new_id = sessions.create(argument)
        print(f"已新建并切换到会话：{sessions.get(new_id).display_title()}（{new_id}）")
        _print_status(sessions, new_id, long_term)
        return new_id

    if command == "/switch":
        metas = sessions.list()
        index = _resolve_index(argument, len(metas))
        if index is None:
            print("用法：/switch <编号>（先用 /sessions 查看编号）")
            return current_session_id
        target = metas[index].session_id
        sessions.touch(target)
        print(f"已切换到会话：{metas[index].display_title()}（{target}）")
        _render_history(short_term, target)
        _print_status(sessions, target, long_term)
        return target

    if command == "/delete":
        tokens = argument.split()
        force = any(token in {"-y", "--yes"} for token in tokens)
        metas = sessions.list()
        positional = [token for token in tokens if not token.startswith("-")]
        index = _resolve_index(positional[0] if positional else "", len(metas))
        if index is None:
            print("用法：/delete <编号> -y（先用 /sessions 查看编号）")
            return current_session_id
        if len(metas) <= 1:
            print("这是唯一的会话，不能删除。可先用 /new 新建一个。")
            return current_session_id

        target_meta = metas[index]
        if not force:
            print(
                f"将要删除会话「{target_meta.display_title()}」（{target_meta.session_id}），"
                "其对话历史与长期记忆都会一并清除。"
            )
            print(f"确认请执行：/delete {index + 1} -y")
            return current_session_id

        target = target_meta.session_id
        removed_memories = long_term.delete_session(target) if long_term is not None else 0
        if short_term is not None:
            short_term.reset(target)
        sessions.delete(target)
        print(
            f"已删除会话「{target_meta.display_title()}」："
            f"对话历史已清除，长期记忆清除 {removed_memories} 条。"
        )
        if target == current_session_id:
            new_id = sessions.list()[0].session_id
            print(f"当前会话已被删除，已切换到：{sessions.get(new_id).display_title()}（{new_id}）")
            _print_status(sessions, new_id, long_term)
            return new_id
        return current_session_id

    if command == "/history":
        limit = int(argument) if argument.isdigit() and int(argument) > 0 else HISTORY_PREVIEW
        _render_history(short_term, current_session_id, limit)
        return current_session_id

    print(f"未知命令：{command}（输入 /help 查看可用命令）")
    return current_session_id


def main() -> int:
    """程序主入口：加载配置、构建 Agent、进入 REPL 循环。

    返回:
        进程退出码：0 表示正常退出，1 表示配置错误。
    """
    # 1) 加载配置（.env）
    try:
        config = load_config()
    except ValueError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 1

    # 2) 组装各层：LLM 客户端 → 记忆 → 工具注册表 → Agent
    llm = LLMClient(config.api_key, config.base_url, config.model, config.temperature)

    # 记忆模块（可按 .env 关闭；依赖缺失/模型未下载时自动降级）
    memory_config = load_memory_config()
    short_term: ShortTermMemory | None = None
    long_term = None
    sessions: SessionIndex | None = None
    if memory_config.enabled:
        short_term = ShortTermMemory(
            system_prompt=SYSTEM_PROMPT.format(cwd=os.getcwd()),
            sessions_dir=memory_config.sessions_dir,
            llm=llm,
            max_messages=memory_config.max_messages,
            keep_recent=memory_config.keep_recent,
        )
        long_term = create_long_term_memory(
            memory_config.chroma_dir, memory_config.model_dir, memory_config.top_k
        )
        sessions = SessionIndex(memory_config.sessions_dir)

    registry = create_default_registry(long_term)

    agent = Agent(
        llm,
        registry,
        max_steps=config.max_steps,
        memory=short_term,
        long_term=long_term,
    )

    # 3) 确定当前会话；并把升级前遗留的无 session_id 记忆归入本会话
    current_session_id = DEFAULT_SESSION_ID
    if sessions is not None:
        current_session_id = _bootstrap_session(sessions, memory_config.sessions_dir)
        if long_term is not None:
            backfilled = long_term.assign_orphans(current_session_id)
            if backfilled:
                print(f"[记忆] 已把 {backfilled} 条缺少会话归属的旧记忆归入当前会话。")

    print(BANNER)
    print(f"模型：{config.model}    Base URL：{config.base_url}    最大步数：{config.max_steps}")
    long_status = f"开（{long_term.count()} 条）" if long_term else "关"
    print(f"记忆：短期={'开' if short_term else '关'}  长期={long_status}")
    _print_status(sessions, current_session_id, long_term)

    # 4) 连接邮件 MCP：启动时发现工具才能注册进注册表（可按 .env 关闭；失败自动降级）
    mcp_config = load_mcp_config()
    mcp_client = None
    if mcp_config.enabled:
        field_defaults: dict[str, Any] | None = (
            {"account_name": mcp_config.account} if mcp_config.account else None
        )
        mcp_tools, mcp_client = connect_mcp_tools(
            mcp_config.command_line, mcp_config.tools, field_defaults, mcp_config.timeout
        )
        for tool in mcp_tools:  # 注册表是同一个对象，Agent 每轮都会重新取工具定义
            registry.register(tool)
        names = ", ".join(tool.name for tool in mcp_tools) or "无"
        print(f"MCP：已接入 {len(mcp_tools)} 个工具（{names}）")
    else:
        print("MCP：已关闭")
    print()

    # 5) REPL 循环
    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            mcp_client.close() if mcp_client else None
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("再见！")
            mcp_client.close() if mcp_client else None
            return 0

        # 斜杠命令：会话管理
        if user_input.startswith("/"):
            current_session_id = _handle_command(
                user_input, sessions, short_term, long_term, current_session_id
            )
            continue

        try:
            # 先打印提示符表示已接收输入；Agent 执行过程静默，只输出最终结论
            print("助手 > ", end="", flush=True)
            answer = agent.run(user_input, session_id=current_session_id)
            print(answer)
            # 会话活动时间与自动命名（仅在尚未命名时）
            if sessions is not None:
                meta = sessions.get(current_session_id)
                if meta is not None and not meta.title:
                    sessions.rename(current_session_id, user_input[:AUTO_TITLE_CHARS])
                sessions.touch(current_session_id)
        except Exception as exc:  # LLM/网络异常不应导致 REPL 退出
            print(f"\n[运行错误] {exc}", file=sys.stderr)
        print()  # 与下一轮输入之间留空行
