"""批改模块：解析题目与答案文件，比对并统计对错。"""

import expression
from fraction import Fraction, FractionError
from utils import AppError, read_lines


class GradeError(AppError):
    """批改过程中的错误。"""


def parse_exercise(line, line_no):
    """解析一行题目，返回标准答案。"""
    text = line.strip()
    if not text:
        raise GradeError(f"第 {line_no} 行题目为空")
    if "=" in text:
        text = text.split("=", 1)[0]
    try:
        node = expression.parse(text)
        return node.evaluate()
    except (expression.ExpressionError, FractionError, ValueError) as error:
        raise GradeError(f"第 {line_no} 行题目无法解析：{text}（{error}）")


def parse_answer(line, line_no):
    """解析一行答案，返回分数对象。"""
    text = line.strip()
    if not text:
        raise GradeError(f"第 {line_no} 行答案为空")
    try:
        return Fraction.from_string(text)
    except FractionError as error:
        raise GradeError(f"第 {line_no} 行答案无法解析：{text}（{error}）")


def grade(exercise_path, answer_path):
    """比对题目与答案文件，返回 (正确题号列表, 错误题号列表)。"""
    exercises = read_lines(exercise_path)
    answers = read_lines(answer_path)
    if len(exercises) != len(answers):
        raise GradeError(
            f"题目文件有 {len(exercises)} 行，答案文件有 {len(answers)} 行，两者数量不一致"
        )

    correct_ids = []
    wrong_ids = []
    for number, (exercise_line, answer_line) in enumerate(zip(exercises, answers), start=1):
        expected = parse_exercise(exercise_line, number)
        actual = parse_answer(answer_line, number)
        if expected == actual:
            correct_ids.append(number)
        else:
            wrong_ids.append(number)
    return correct_ids, wrong_ids
