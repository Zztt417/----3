"""表达式约束校验与判重测试（含 PRD 3.1.2 的全部判重示例）。"""

import expression as expr
from fraction import Fraction


def key(text):
    return expr.parse(text).canonical_key()


# --------------------------- 判重规则 ---------------------------


def test_commutative_duplicate_add():
    assert key("23 + 45") == key("45 + 23")


def test_commutative_duplicate_mul():
    assert key("6 × 8") == key("8 × 6")


def test_associated_duplicate():
    assert key("3 + (2 + 1)") == key("1 + 2 + 3")


def test_non_duplicate_different_association():
    assert key("1 + 2 + 3") != key("3 + 2 + 1")


def test_subtraction_not_commutative():
    assert key("5 − 3") != key("3 − 5")


def test_division_not_commutative():
    assert key("1 ÷ 2") != key("2 ÷ 1")


# --------------------------- 约束校验 ---------------------------


def test_no_negative_intermediate():
    assert not expr.check_constraints(expr.parse("3 − 5 + 4"), 10)
    assert expr.check_constraints(expr.parse("5 − 3 + 4"), 10)


def test_division_must_be_proper_fraction():
    assert expr.check_constraints(expr.parse("1 ÷ 2"), 10)
    assert not expr.check_constraints(expr.parse("6 ÷ 3"), 10)
    assert not expr.check_constraints(expr.parse("3 ÷ 2"), 10)


def test_operand_range():
    assert expr.check_constraints(expr.parse("9 + 1"), 10)
    assert not expr.check_constraints(expr.parse("10 + 1"), 10)
    assert expr.check_constraints(expr.parse("3/5 + 1/2"), 10)
    assert not expr.check_constraints(expr.parse("3/10 + 1/2"), 10)


def test_operator_count_limit():
    assert expr.check_constraints(expr.parse("1 + 2 + 3 + 4"), 10)
    assert not expr.check_constraints(expr.parse("1 + 2 + 3 + 4 + 5"), 10)


def test_single_number_is_not_a_question():
    assert not expr.check_constraints(expr.parse("7"), 10)


# --------------------------- 渲染与解析 ---------------------------


def test_render_left_associative_without_parentheses():
    assert expr.parse("1 + 2 + 3").render() == "1 + 2 + 3"


def test_render_keeps_right_association():
    assert expr.parse("3 + (2 + 1)").render() == "3 + (2 + 1)"


def test_render_subtraction_structure():
    assert expr.parse("5 + 3 − 2").render() == "5 + 3 − 2"
    assert expr.parse("5 + (3 − 2)").render() == "5 + (3 − 2)"


def test_render_precedence_parentheses():
    assert expr.parse("(1 + 2) × 3").render() == "(1 + 2) × 3"
    assert expr.parse("2 × 3 + 1").render() == "2 × 3 + 1"


def test_render_mixed_number():
    assert expr.parse("2'3/8 + 1/8").render() == "2'3/8 + 1/8"


def test_parse_evaluate():
    assert expr.parse("1/6 + 1/8").evaluate() == Fraction(7, 24)
    assert expr.parse("2'3/8").evaluate() == Fraction(19, 8)


def test_parse_render_round_trip():
    samples = [
        "1 ÷ 2",
        "3 + (2 + 1)",
        "1/6 + 1/8",
        "(1 + 2) × 3",
        "5 − 3 + 4",
        "2'3/8 + 1/8",
    ]
    for text in samples:
        node = expr.parse(text)
        assert expr.parse(node.render()).canonical_key() == node.canonical_key()


def test_parse_invalid():
    import pytest

    for bad in ["", "1 +", "(1 + 2", "1 + 2)", "1 $ 2", "1/0"]:
        with pytest.raises(expr.ExpressionError):
            expr.parse(bad)


def test_format_expression():
    assert expr.format_expression(expr.parse("1 + 2")) == "1 + 2 = "
