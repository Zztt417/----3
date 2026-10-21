"""通用工具：文件读写、参数校验、结果格式化。"""

import os


class AppError(Exception):
    """程序运行期错误，携带面向用户的中文提示。"""


class UsageError(AppError):
    """参数使用错误，需要额外打印帮助信息。"""


HELP_TEXT = """小学四则运算题目自动生成器

用法：
  Myapp.exe -n <数量> -r <范围>      生成题目
  Myapp.exe -e <题目文件> -a <答案文件>   批改答案

参数说明：
  -n <数量>   生成题目的个数，例如 -n 10
  -r <范围>   题目中操作数的范围，生成小于该值的题目，例如 -r 10 表示 10 以内（不含 10）
              -r 为必填参数，且至少为 1
  -e <文件>   批改模式下的题目文件，例如 -e Exercises.txt
  -a <文件>   批改模式下的答案文件，例如 -a Answers.txt

示例：
  Myapp.exe -n 10 -r 10
  Myapp.exe -n 10000 -r 100
  Myapp.exe -e Exercises.txt -a Answers.txt
"""


def read_lines(path):
    """按行读取文本文件（UTF-8，兼容带 BOM 的文件），忽略末尾空行。"""
    if not os.path.isfile(path):
        raise AppError(f"文件不存在：{path}")
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            content = handle.read()
    except OSError as error:
        raise AppError(f"无法读取文件 {path}：{error}")
    lines = content.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def write_lines(path, lines):
    """按行写入文本文件（UTF-8，LF 换行）。"""
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line)
                handle.write("\n")
    except OSError as error:
        raise AppError(f"无法写入文件 {path}：{error}")


def _parse_natural(value, name):
    text = str(value).strip()
    if not text.isdigit():
        raise UsageError(f"参数 {name} 必须是非负整数，当前取值：{value}")
    return int(text)


def validate_n(value):
    """校验 -n：必须为正整数。"""
    number = _parse_natural(value, "-n")
    if number <= 0:
        raise UsageError(f"参数 -n 必须大于 0，当前取值：{value}")
    return number


def validate_r(value):
    """校验 -r：必须为自然数且至少为 1。"""
    number = _parse_natural(value, "-r")
    if number < 1:
        raise UsageError(f"参数 -r 必须至少为 1，当前取值：{value}")
    return number


def build_grade_content(correct_ids, wrong_ids):
    """按 PRD 3.2.3 生成 Grade.txt 的内容行。"""

    def join(ids):
        return ", ".join(str(item) for item in ids)

    return [
        f"Correct: {len(correct_ids)} ({join(correct_ids)})",
        f"Wrong: {len(wrong_ids)} ({join(wrong_ids)})",
    ]
