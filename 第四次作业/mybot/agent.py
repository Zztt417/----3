"""Agent 循环模块：实现带 max_steps 上限的 ReAct 工具调用循环。"""

from __future__ import annotations

import os
from pathlib import Path

from .llm import LLMClient
from .long_memory import LongTermMemory
from .memory import ShortTermMemory
from .session_scope import DEFAULT_SESSION_ID, set_current_session
from .tools.registry import ToolRegistry

# 系统提示词：告诉 LLM 它的角色、可用工具与行为规则
SYSTEM_PROMPT = """你是一个运行在命令行里的智能助手。
你可以使用以下工具来完成任务：读取文件、写入文件、执行 shell 命令、联网搜索与抓取网页、解析 PDF。
规则：
1. 需要真实信息或操作文件/系统时，才调用工具；可以直接回答时直接回答。
2. 一次可以调用一个或多个工具，调用后根据返回结果决定下一步。
3. 完成任务后用简洁的中文给出最终答复。
4. 当了解到值得长期记住的用户信息（身份、偏好、重要事实、已确认结论）时，调用 memory_save 记住。
5. 各会话的记忆相互隔离：你只能回忆【当前会话】里的信息，不要假设用户在其他会话里说过什么。
6. 若用户问起「我之前在别的对话里说过什么」，先明确告知各会话默认不互通；只有用户明确要求后，才调用 memory_search_other_sessions 去检索，并在回答中标注每条信息来自哪个会话。
当前工作目录：{cwd}
"""


class Agent:
    """ReAct Agent：维护会话消息历史，循环调用 LLM 与工具。

    核心流程（对应 nanobot 的 runner._run_core）：
        请求 LLM → 判断是否有工具调用 → 有则执行并回填结果 → 继续循环；
        无工具调用则视为最终答复，结束本轮。

    记忆分两层：
        - 短期记忆（memory）：按会话键持久化的消息历史，超阈值时摘要压缩。
        - 长期记忆（long_term）：向量库语义记忆，每轮检索注入 system 上下文。
    """

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        max_steps: int = 10,
        memory: ShortTermMemory | None = None,
        long_term: LongTermMemory | None = None,
    ) -> None:
        """初始化。

        参数:
            llm: LLM 客户端。
            registry: 工具注册表。
            max_steps: 单轮用户请求内最多循环步数，防止无限循环。
            memory: 短期记忆；不传则内部新建（默认落在 .mybot/sessions）。
            long_term: 长期记忆；为 None 时关闭长期记忆能力。
        """
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps
        self.long_term = long_term
        self.memory = memory or ShortTermMemory(
            system_prompt=SYSTEM_PROMPT.format(cwd=os.getcwd()),
            sessions_dir=Path(".mybot") / "sessions",
            llm=llm,
        )

    def run(self, user_input: str, session_id: str = DEFAULT_SESSION_ID) -> str:
        """处理一次用户输入，执行 ReAct 循环并返回最终文本答复。

        参数:
            user_input: 用户输入的文本。
            session_id: 会话 ID——决定读取哪份对话历史、检索哪批长期记忆。

        返回:
            最终答复文本（达到步数上限或模型空回复时返回相应提示）。
        """
        # 把当前会话写入作用域，供 memory_save 等工具读取（工具实例是全局的）
        set_current_session(session_id)

        session = self.memory.session(session_id)
        # 只在回合开始时压缩，避免切断 assistant(tool_calls) 与 tool 结果的配对
        session.compress_if_needed()

        # 只在【当前会话】内检索长期记忆（会话间隔离），并注入本轮 system 内容
        extra = ""
        if self.long_term is not None:
            hits = self.long_term.search(user_input, session_id=session_id)
            if hits:
                extra = "【本会话的相关长期记忆】\n" + "\n".join(f"- {hit}" for hit in hits)

        # request 是本轮发给 LLM 的消息（含临时注入）；session 是可持久化的历史
        request: list[dict] = [
            {"role": "system", "content": session.system_content(extra)}
        ] + session.messages

        user_message = {"role": "user", "content": user_input}
        request.append(user_message)
        session.append(user_message)

        tools = self.registry.get_definitions()

        for _ in range(self.max_steps):
            # 1) 请求 LLM（本方法不做任何输出）
            response = self.llm.chat_stream(request, tools)
            # 2) 先把 assistant 回复写入历史，保持 tool 消息与 tool_calls 的对应关系
            assistant_message = LLMClient.assistant_message(response)
            request.append(assistant_message)
            session.append(assistant_message)

            # 3) 无工具调用 → 本轮任务结束，返回文本
            if not response.tool_calls:
                if not response.content.strip():
                    return "(模型返回了空回复)"
                return response.content

            # 4) 有工具调用 → 逐个执行，并把结果作为 tool 消息回填（过程不对外输出）
            for tool_call in response.tool_calls:
                result = self.registry.execute(tool_call.name, tool_call.arguments)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result.content,
                }
                request.append(tool_message)
                session.append(tool_message)

        # 5) 超出步数上限：返回提示，避免死循环
        return f"(已达到最大步数 {self.max_steps}，任务未完成，请调整问题或提高 MAX_STEPS)"
