"""批改功能测试。"""

import pytest

import grader
from utils import AppError, build_grade_content


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_grade_all_correct(tmp_path):
    exercise = write(
        tmp_path / "Exercises.txt",
        "1 + 2 = \n1/6 + 1/8 = \n2'3/8 + 1/8 = \n5 − 3 + 4 = \n",
    )
    answer = write(tmp_path / "Answers.txt", "3\n7/24\n5/2\n6\n")
    correct, wrong = grader.grade(exercise, answer)
    assert correct == [1, 2, 3, 4]
    assert wrong == []


def test_grade_partial_correct(tmp_path):
    exercise = write(tmp_path / "Exercises.txt", "1 + 2 = \n1 + 2 = \n1 + 2 = \n")
    answer = write(tmp_path / "Answers.txt", "3\n4\n3\n")
    correct, wrong = grader.grade(exercise, answer)
    assert correct == [1, 3]
    assert wrong == [2]


def test_grade_missing_file(tmp_path):
    answer = write(tmp_path / "Answers.txt", "3\n")
    with pytest.raises(AppError):
        grader.grade(str(tmp_path / "Missing.txt"), answer)


def test_grade_line_count_mismatch(tmp_path):
    exercise = write(tmp_path / "Exercises.txt", "1 + 2 = \n1 + 2 = \n")
    answer = write(tmp_path / "Answers.txt", "3\n")
    with pytest.raises(grader.GradeError):
        grader.grade(exercise, answer)


def test_grade_invalid_answer(tmp_path):
    exercise = write(tmp_path / "Exercises.txt", "1 + 2 = \n")
    answer = write(tmp_path / "Answers.txt", "不是数字\n")
    with pytest.raises(grader.GradeError):
        grader.grade(exercise, answer)


def test_grade_invalid_exercise(tmp_path):
    exercise = write(tmp_path / "Exercises.txt", "1 + $ = \n")
    answer = write(tmp_path / "Answers.txt", "3\n")
    with pytest.raises(grader.GradeError):
        grader.grade(exercise, answer)


def test_grade_with_utf8_bom(tmp_path):
    """兼容带 UTF-8 BOM 的文件（Windows 记事本 / PowerShell 生成的文件常见）。"""
    exercise = tmp_path / "Exercises.txt"
    answer = tmp_path / "Answers.txt"
    exercise.write_bytes("1 + 2 = \n".encode("utf-8-sig"))
    answer.write_bytes("3\n".encode("utf-8-sig"))
    correct, wrong = grader.grade(str(exercise), str(answer))
    assert correct == [1]
    assert wrong == []


def test_build_grade_content_format():
    assert build_grade_content([1, 3, 5, 7, 9], [2, 4, 6, 8, 10]) == [
        "Correct: 5 (1, 3, 5, 7, 9)",
        "Wrong: 5 (2, 4, 6, 8, 10)",
    ]
    assert build_grade_content([], [1]) == ["Correct: 0 ()", "Wrong: 1 (1)"]
