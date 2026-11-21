"""一个用于教学的最小 MCP 服务（stdio 传输）——只做演示，不含真实功能。

====================================================================
一、MCP 是什么
====================================================================
MCP（Model Context Protocol）是一套让「AI 应用（客户端）」调用「外部能力（服务端）」
的**标准协议**。它解决的是同一个问题：**不要为每个工具写一套适配代码**。

本文件扮演的是 **服务端（MCP Server）**；你的 `mybot` 项目里的
`mybot/mcp_client.py` 扮演 **客户端（MCP Client）**。

一次调用的完整链路：

    LLM 决定调用某工具
        ↓  mybot 的 MCPToolWrapper.execute()
    客户端把请求写成 JSON-RPC 消息 → 子进程的 stdin
        ↓
    本文件（服务端）执行对应函数 → 把结果写成 JSON-RPC 消息 → stdout
        ↓
    客户端解析结果 → 作为工具结果回喂给 LLM

注意这里的关键点：**服务端是被客户端以子进程方式拉起来的**，
它自己不需要知道 TCP 端口、鉴权、HTTP——因为走的是 stdio（标准输入输出）。

====================================================================
二、三条铁律（新手最容易踩的坑）
====================================================================
1. **绝对不要用 print() 往 stdout 输出任何东西。**
   stdio 模式下 stdout 就是协议通道，print 会插进一段非 JSON 的内容，
   直接破坏协议帧，客户端会报解析错误。
   要调试请用 `sys.stderr.write()` 或 `logging`（本文件末尾有示例）。

2. **函数签名 + docstring 就是工具的"说明书"。**
   MCP 客户端会读取它们，自动生成 JSON Schema 发给 LLM。
   所以 docstring 不是写给同事看的，是**写给模型看的**——要说清"什么时候该调用我"。

3. **服务端不需要关心调用者是谁。**
   会话隔离、权限、白名单这些是客户端/上层的事（比如 mybot 的
   `session_scope` 和邮件服务的收件人白名单）。

====================================================================
三、依赖与运行
====================================================================
依赖：只需 `mcp`（本项目 requirements.txt 里已有）。

自测运行（它会阻塞等待 stdin，属正常现象，Ctrl+C 退出）：

    python mcp_server_demo.py            # stdio（默认，mybot 用的就是这种）
    python mcp_server_demo.py http       # streamable-http（教学演示另一种传输）

命令行自测连接（复用 mybot 现成的客户端）：

    python -c "from mybot.mcp_client import connect_mcp_tools; t,c=connect_mcp_tools('python mcp_server_demo.py', ['echo','add'], None, 60); print([x.name for x in t]); [print(x.execute(**args)) for x in t for args in ([{'text':'hi'}] if x.name=='echo' else [{'a':1,'b':2}])]; c.close()"
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

# 创建服务实例。
#   name 会出现在客户端看到的服务标识里；
#   instructions 是给"使用这个服务的 AI"的一段总说明（可选）。
mcp = FastMCP(
    "demo",
    instructions="这是一个教学用途的演示服务，只有几个玩具工具，不承载任何真实业务。",
)


# --------------------------------------------------------------------
# 1) 工具（Tool）—— 会被 LLM 调用的函数
# --------------------------------------------------------------------
# 加 @mcp.tool() 之后，这个普通函数就变成了 MCP 工具：
#   - 函数名        → 工具名（客户端按这个名字调用）
#   - docstring     → 工具描述（写给模型看，决定它何时调用）
#   - 参数类型注解   → 自动生成 JSON Schema 的 properties
#   - 返回类型注解   → 客户端可据此处理结果
@mcp.tool()
def echo(text: str) -> str:
    """把输入原样返回。

    教学用途：这是**最小可用的工具**，用来观察"函数 → 工具"的映射关系。

    Args:
        text: 任意文本。

    Returns:
        与输入完全相同的文本。
    """
    # 注意：这里只 return，绝不 print（print 会污染协议通道）
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """把两个整数相加。

    教学用途：观察**类型注解如何变成 JSON Schema** —— 客户端拿到的
    parameters 会是 {"type":"object","properties":{"a":{"type":"integer"},
    "b":{"type":"integer"}},"required":["a","b"]}，
    模型据此知道要传两个整数。

    Args:
        a: 第一个整数。
        b: 第二个整数。

    Returns:
        两数之和。
    """
    return a + b


# --------------------------------------------------------------------
# 2) 资源（Resource）—— 只读的上下文数据，不是工具
# --------------------------------------------------------------------
# 区别很重要：
#   - 工具（Tool）：模型**主动调用**，可以产生副作用，参数由模型填。
#   - 资源（Resource）：**只读**数据，通常由客户端在构造上下文时**主动读入**，
#     模型不"调用"它。适合放"配置、文档片段、状态快照"这类东西。
@mcp.resource("demo://greeting")
def greeting() -> str:
    """返回一段固定的问候语（资源示例）。

    Returns:
        一段静态文本。
    """
    return "你好，这是来自 demo 资源的内容。"


# --------------------------------------------------------------------
# 3) 提示模板（Prompt）—— 可复用的提示词，同样不是工具
# --------------------------------------------------------------------
# 提示模板由**用户/客户端显式选择**使用（例如界面上的一个命令），
# 用来把一段常用的提示词固化下来。模型不会自己去"调用"它。
@mcp.prompt()
def review_prompt(topic: str) -> str:
    """生成一段"请评审这个主题"的提示词。

    Args:
        topic: 要评审的主题。

    Returns:
        组装好的提示词文本。
    """
    return f"请从正确性、可读性、性能三个角度评审：{topic}"


# --------------------------------------------------------------------
# 4) 出错时怎么办
# --------------------------------------------------------------------
# 直接 raise 异常即可：SDK 会把它包装成**错误响应**（isError=true）回给客户端。
# 在 mybot 侧，这会被渲染成 ToolResult.error(...)，模型能看到错误并改策略，
# 而不会中断整个 Agent 循环。
#
# @mcp.tool()
# def risky(x: int) -> str:
#     """演示如何报错（本文件未注册，仅作示意）。"""
#     if x < 0:
#         raise ValueError("x 不能为负数")
#     return "ok"


# --------------------------------------------------------------------
# 5) 调试日志的正确姿势
# --------------------------------------------------------------------
# 需要看运行日志时，写 stderr 或 logging，绝不能写 stdout：
#
#     import logging
#     logging.basicConfig(stream=sys.stderr, level=logging.INFO)
#     logging.info("工具被调用了")
#
# 顺带一提：mybot 的客户端会把本服务进程的 **stderr 重定向到
# `.mybot/mcp.log`**，所以你的调试日志会落在那里，不刷屏终端。


def main() -> int:
    """服务入口：按命令行参数选择传输方式并启动（阻塞）。

    返回:
        进程退出码。
    """
    transport = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "stdio"

    if transport in {"http", "streamable-http"}:
        # 另一种传输：把服务挂在 HTTP 上（适合远程/多客户端）
        mcp.run(transport="streamable-http")
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        # 默认 stdio：由客户端拉成子进程，通过 stdin/stdout 通信。
        # mybot 用的就是这一种（也是目前最主流、最简单的一种）。
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
