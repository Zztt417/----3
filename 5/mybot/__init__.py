"""mybot：一个仿照 nanobot 核心架构实现的极简 CLI Agent 助手。

模块划分（单一职责）：
    - config  : 从 .env 加载配置
    - llm     : 封装 OpenAI 兼容的流式 LLM 客户端
    - tools   : 工具基类、注册表与内置工具（read_file / write_file / run_shell）
    - agent   : 带 max_steps 上限的 ReAct 工具调用循环
    - cli     : 命令行 REPL 入口
"""

__version__ = "0.1.0"
