"""一次性脚本：从 ModelScope 下载 bge-small-zh-v1.5 到项目内 models/。

用法:
    python setup_memory.py            # 下载（已存在则跳过）
    python setup_memory.py --force    # 强制重新下载
"""

import argparse
import sys
import urllib.request
from pathlib import Path

# 项目根目录与默认模型目录：模型放在仓库内，克隆后即可直接使用。
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "bge-small-zh-v1.5"

# ModelScope 文件直链模板（已验证可达）
_URL = (
    "https://modelscope.cn/api/v1/models/BAAI/bge-small-zh-v1.5/repo"
    "?Revision=master&FilePath={path}"
)
# sentence-transformers 加载所需的最小文件集
_FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "configuration.json",
    "modules.json",
    "model.safetensors",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
]


def download(model_dir: Path, force: bool = False) -> int:
    """下载模型文件。

    参数:
        model_dir: 目标目录（默认项目内 models/bge-small-zh-v1.5）。
        force: 为 True 时已存在的文件也重新下载。

    返回:
        0 表示全部成功，1 表示有文件失败。
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for rel in _FILES:
        target = model_dir / rel
        if target.exists() and not force:
            print(f"跳过（已存在）：{rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = urllib.request.Request(
                _URL.format(path=rel), headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            target.write_bytes(data)
            print(f"下载完成：{rel}（{len(data) / 1024:.0f} KB）")
        except Exception as exc:
            failed += 1
            print(f"下载失败：{rel} -> {type(exc).__name__} {exc}", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="下载 bge-small-zh-v1.5 嵌入模型")
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_MODEL_DIR),
        help="模型存放目录（默认项目内 models/bge-small-zh-v1.5）",
    )
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    args = parser.parse_args()
    print(f"目标目录：{args.dest}")
    code = download(Path(args.dest), args.force)
    print("全部完成 ✅" if code == 0 else "存在失败项，请检查网络后重试 ❌")
    return code


if __name__ == "__main__":
    sys.exit(main())
