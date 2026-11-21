"""MyBot Windows 桌面启动器。

该入口由 PyInstaller 打包为 MyBot.exe：
- 自动启动本地 FastAPI；
- 使用随机本机端口；
- 等待健康检查；
- 创建 pywebview 桌面窗口；
- 退出时停止后端。
"""

from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


APP_NAME = "MyBot"
APP_VERSION = "1.0.0"
LOCK_NAME = "instance.lock"


def _resource_root() -> Path:
    """返回打包后的资源根目录。"""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent


def _exe_dir() -> Path:
    """返回可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _home_dir() -> Path:
    """返回桌面应用的用户数据目录。"""
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _load_desktop_env(home: Path) -> None:
    """加载可选的桌面环境文件，并设置默认用户目录。"""
    from dotenv import load_dotenv

    # 允许在 exe 旁放置 MyBot.env，用于所有者显式复用开发数据。
    for candidate in (_exe_dir() / "MyBot.env", home / "app.env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break

    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MEMORY_DATA_DIR", str(home / "data"))
    os.environ.setdefault("MYBOT_LLM_CONFIG", str(home / "llm_config.json"))
    os.environ.setdefault("MYBOT_MCP_CONFIG", str(home / "mcp_servers.json"))
    os.environ.setdefault("MYBOT_SKILLS_DIR", str(home / "skills"))

    model_dir = _resource_root() / "models" / "bge-small-zh-v1.5"
    os.environ.setdefault("MEMORY_MODEL_DIR", str(model_dir))

    # 桌面进程默认只监听回环地址；端口由启动器动态分配。
    os.environ["API_HOST"] = "127.0.0.1"


def _free_port() -> int:
    """申请一个本机空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _message(text: str, title: str = APP_NAME) -> None:
    """在 Windows 上显示原生错误对话框，其他平台输出到标准错误。"""
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def _acquire_lock(home: Path):
    """防止同一个桌面数据目录被两个实例同时写入。"""
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / LOCK_NAME
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        return lock_file
    except OSError:
        lock_file.close()
        raise RuntimeError("检测到另一个 MyBot 实例正在使用当前用户数据目录。") from None


def _wait_for_health(url: str, timeout: float = 90.0) -> bool:
    """等待本地 FastAPI 健康检查成功。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _start_server(port: int):
    """在后台线程启动 FastAPI。"""
    import uvicorn

    from mybot.api import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="mybot-fastapi", daemon=True)
    thread.start()
    return server, thread


def main() -> int:
    """启动桌面应用或执行打包烟雾测试。"""
    home = _home_dir()
    _load_desktop_env(home)
    log_dir = home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_stream = (log_dir / "desktop.log").open("a", encoding="utf-8", buffering=1)
    lock_file = None
    server = None
    server_thread = None
    try:
        with redirect_stdout(log_stream), redirect_stderr(log_stream):
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting MyBot {APP_VERSION}")
            try:
                lock_file = _acquire_lock(home)
            except RuntimeError as exc:
                _message(str(exc))
                return 2

            port = _free_port()
            os.environ["API_PORT"] = str(port)
            url = f"http://127.0.0.1:{port}"
            server, server_thread = _start_server(port)
            if not _wait_for_health(url):
                _message("MyBot 后端启动失败，请查看日志：\n%s" % (log_dir / "desktop.log"))
                return 3

            if "--smoke-test" in sys.argv:
                print(f"SMOKE_TEST_OK url={url}")
                return 0

            import webview

            webview.create_window(
                f"MyBot {APP_VERSION}",
                url,
                width=1280,
                height=820,
                min_size=(900, 620),
                text_select=True,
            )
            webview.start()
            return 0
    finally:
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=5)
        if lock_file is not None:
            try:
                lock_file.close()
            except Exception:
                pass
        log_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())