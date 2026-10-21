"""上传 GitHub 前的本地安全检查。

用法：
    python scripts/check_github_safety.py

脚本只读取项目目录，不会删除或修改任何文件。
发现阻断项时返回退出码 1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "models",
    "__pycache__",
    "data",
    ".mybot",
}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".vue",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".example",
}
ALLOWED_SAMPLE_PDFS = {"_synthetic_big.pdf", "_synthetic_nested.pdf"}

# 高置信度的密钥格式。真实值不会被打印。
HIGH_CONFIDENCE_PATTERNS = [
    ("OpenAI/DeepSeek key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
]

# 配置文件中“键名 = 长字符串”的模式。
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|auth[_-]?code|authorization)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})"
)
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
PLACEHOLDER_WORDS = {
    "your",
    "example",
    "placeholder",
    "change",
    "redacted",
    "none",
    "null",
    "false",
    "true",
    "getenv",
    "variable",
}


def is_text_file(path: Path) -> bool:
    """判断文件是否值得按文本扫描。"""
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name.startswith(".env")


def iter_files() -> list[Path]:
    """遍历项目文件，跳过依赖、模型和运行时目录。"""
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        files.append(path)
    return files


def looks_placeholder(value: str) -> bool:
    """判断疑似密钥的值是否是示例占位符。"""
    lowered = value.lower()
    return any(word in lowered for word in PLACEHOLDER_WORDS)


def scan_text(path: Path, errors: list[str]) -> None:
    """扫描单个文本文件中的密钥形态和个人电话号码。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return
    if len(raw) > 2_000_000 or b"\x00" in raw[:4096]:
        return
    text = raw.decode("utf-8", errors="replace")
    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in HIGH_CONFIDENCE_PATTERNS:
            if pattern.search(line):
                relative = path.relative_to(PROJECT_ROOT)
                errors.append(f"{relative}:{line_number}: 疑似 {label}（值已隐藏）")
        for match in ASSIGNMENT_PATTERN.finditer(line):
            value = match.group(2)
            if not looks_placeholder(value):
                relative = path.relative_to(PROJECT_ROOT)
                errors.append(
                    f"{relative}:{line_number}: 疑似硬编码密钥字段 {match.group(1)}（值已隐藏）"
                )
        if PHONE_PATTERN.search(line):
            relative = path.relative_to(PROJECT_ROOT)
            errors.append(f"{relative}:{line_number}: 疑似手机号（值已隐藏）")


def main() -> int:
    """执行检查并打印结果。"""
    errors: list[str] = []
    warnings: list[str] = []

    project_env = PROJECT_ROOT / ".env"
    if project_env.exists():
        errors.append(
            "项目根目录仍存在 .env；请把它移到 ~/.mybot/.env 或设置 MYBOT_ENV_FILE。"
        )

    for path in PROJECT_ROOT.glob("ui/.env*"):
        if path.name != ".env.example":
            warnings.append(f"发现前端本地环境文件：{path.relative_to(PROJECT_ROOT)}（不要提交）")

    for path in iter_files():
        if path.suffix.lower() in {".sqlite3", ".sqlite", ".db"}:
            errors.append(f"发现数据库文件：{path.relative_to(PROJECT_ROOT)}（可能包含凭据）")
        if PHONE_PATTERN.search(path.name):
            errors.append(f"文件名包含疑似手机号：{path.relative_to(PROJECT_ROOT)}")
        if is_text_file(path):
            scan_text(path, errors)

    samples_dir = PROJECT_ROOT / "samples"
    if samples_dir.exists():
        for pdf in samples_dir.glob("*.pdf"):
            if pdf.name not in ALLOWED_SAMPLE_PDFS:
                errors.append(
                    f"发现非合成 PDF：samples/{pdf.name}（可能包含个人隐私，请移到仓库外）"
                )

    for runtime_dir in (".mybot", "data"):
        if (PROJECT_ROOT / runtime_dir).exists():
            warnings.append(
                f"发现运行时目录 {runtime_dir}/；Git 会忽略它，但请勿用压缩包整目录上传。"
            )

    print("MyBot GitHub 安全检查")
    print("=" * 32)
    if warnings:
        print("\n警告：")
        for warning in warnings:
            print(f"  [WARN] {warning}")
    if errors:
        print("\n阻断项：")
        for error in errors:
            print(f"  [ERROR] {error}")
        print(f"\n结果：发现 {len(errors)} 个阻断项，请修复后再上传。")
        return 1

    print("\n[OK] 未发现项目内的真实密钥、手机号或非合成 PDF。")
    print("[OK] 可以进入 GitHub 上传流程；仍建议上传前检查一次 git status。")
    return 0


if __name__ == "__main__":
    sys.exit(main())