"""程序入口：解析命令行参数，调度生成模式与批改模式。"""

import sys

import generator
import grader
from utils import (
    HELP_TEXT,
    AppError,
    UsageError,
    build_grade_content,
    validate_n,
    validate_r,
    write_lines,
)

EXERCISE_FILE = "Exercises.txt"
ANSWER_FILE = "Answers.txt"
GRADE_FILE = "Grade.txt"

KNOWN_OPTIONS = ("-n", "-r", "-e", "-a")


def parse_args(argv):
    """解析 -n/-r/-e/-a 形式的命令行参数。"""
    options = {name: None for name in KNOWN_OPTIONS}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg not in options:
            raise UsageError(f"无法识别的参数：{arg}")
        if index + 1 >= len(argv):
            raise UsageError(f"参数 {arg} 缺少取值")
        options[arg] = argv[index + 1]
        index += 2
    return options


def run_generate(options):
    if options["-n"] is None:
        raise UsageError("生成模式缺少必填参数 -n")
    if options["-r"] is None:
        raise UsageError("生成模式缺少必填参数 -r")

    count = validate_n(options["-n"])
    limit = validate_r(options["-r"])

    results, complete = generator.generate(count, limit)
    write_lines(EXERCISE_FILE, [f"{expr} = " for expr, _ in results])
    write_lines(ANSWER_FILE, [answer for _, answer in results])

    print(f"已生成 {len(results)} 道题目，题目见 {EXERCISE_FILE}，答案见 {ANSWER_FILE}")
    if not complete:
        print(
            f"警告：受 -r {limit} 限制，可用的不重复题目不足，"
            f"仅生成 {len(results)} / {count} 道题目。"
        )
        return 3
    return 0


def run_grade(options):
    if not options["-e"] or not options["-a"]:
        raise UsageError("批改模式需要同时提供 -e <题目文件> 和 -a <答案文件>")

    correct_ids, wrong_ids = grader.grade(options["-e"], options["-a"])
    write_lines(GRADE_FILE, build_grade_content(correct_ids, wrong_ids))

    print(
        f"批改完成：正确 {len(correct_ids)} 题，错误 {len(wrong_ids)} 题，结果见 {GRADE_FILE}"
    )
    return 0


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    try:
        options = parse_args(arguments)
        if options["-e"] or options["-a"]:
            return run_grade(options)
        return run_generate(options)
    except UsageError as error:
        print(f"错误：{error}")
        print(HELP_TEXT)
        return 2
    except AppError as error:
        print(f"错误：{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
