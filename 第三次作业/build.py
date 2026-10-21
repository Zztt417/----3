"""打包脚本：封装 PyInstaller 命令，生成 dist/Myapp.exe。"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join("src", "main.py")
APP_NAME = "Myapp"


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未检测到 PyInstaller，请先安装：pip install -r requirements.txt")
        return 1

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        APP_NAME,
        "--distpath",
        os.path.join(PROJECT_ROOT, "dist"),
        "--workpath",
        os.path.join(PROJECT_ROOT, "build"),
        "--specpath",
        os.path.join(PROJECT_ROOT, "build"),
        os.path.join(PROJECT_ROOT, ENTRY),
    ]
    print("执行：", " ".join(command))
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    sys.exit(main())
