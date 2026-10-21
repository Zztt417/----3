"""分数运算单元测试。"""

import pytest

from fraction import Fraction, FractionError


def test_reduce_on_construction():
    assert Fraction(2, 4) == Fraction(1, 2)
    assert Fraction(6, 3) == Fraction(2)
    assert Fraction(-2, 4) == Fraction(-1, 2)
    assert Fraction(2, -4) == Fraction(-1, 2)


def test_zero_denominator():
    with pytest.raises(FractionError):
        Fraction(1, 0)


def test_arithmetic():
    assert Fraction(1, 6) + Fraction(1, 8) == Fraction(7, 24)
    assert Fraction(3, 5) + Fraction(2, 5) == Fraction(1)
    assert Fraction(3, 4) - Fraction(1, 4) == Fraction(1, 2)
    assert Fraction(2, 3) * Fraction(3, 4) == Fraction(1, 2)
    assert Fraction(1, 2) / Fraction(3, 4) == Fraction(2, 3)


def test_mixed_with_int():
    assert Fraction(1, 2) + 1 == Fraction(3, 2)
    assert 1 + Fraction(1, 2) == Fraction(3, 2)
    assert 2 - Fraction(1, 2) == Fraction(3, 2)
    assert 2 * Fraction(1, 4) == Fraction(1, 2)
    assert 1 / Fraction(1, 2) == Fraction(2)


def test_comparison():
    assert Fraction(1, 3) < Fraction(1, 2)
    assert Fraction(2, 4) == Fraction(1, 2)
    assert Fraction(3, 2) > 1
    assert hash(Fraction(1, 2)) == hash(Fraction(2, 4))


def test_is_proper():
    assert Fraction(1, 2).is_proper()
    assert not Fraction(1).is_proper()
    assert not Fraction(3, 2).is_proper()
    assert not Fraction(0, 5).is_proper()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3", Fraction(3)),
        ("3/5", Fraction(3, 5)),
        ("2'3/8", Fraction(19, 8)),
        (" 1'1/2 ", Fraction(3, 2)),
        ("-1/2", Fraction(-1, 2)),
    ],
)
def test_from_string(text, expected):
    assert Fraction.from_string(text) == expected


def test_from_string_invalid():
    with pytest.raises(FractionError):
        Fraction.from_string("1/0")
    with pytest.raises(FractionError):
        Fraction.from_string("2'5/3")
    with pytest.raises(FractionError):
        Fraction.from_string("")


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(3), "3"),
        (Fraction(3, 5), "3/5"),
        (Fraction(19, 8), "2'3/8"),
        (Fraction(7, 24), "7/24"),
        (Fraction(-3, 2), "-1'1/2"),
    ],
)
def test_to_string(value, expected):
    assert value.to_string() == expected


def test_string_round_trip():
    for value in (Fraction(0), Fraction(5), Fraction(3, 5), Fraction(19, 8), Fraction(7, 24)):
        assert Fraction.from_string(value.to_string()) == value
