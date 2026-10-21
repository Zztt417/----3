"""支持以 `python -m mybot` 的方式启动程序。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
