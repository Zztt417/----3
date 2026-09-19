"""题目生成测试（含约束校验与大规模冒烟）。"""

import time

import expression as expr
import generator
from fraction import Fraction

MAX_OPERATORS = 3


def test_generate_count_and_uniqueness():
    results, complete = generator.generate(50, 10, seed=1)
    assert complete
    assert len(results) == 50

    keys = set()
    for exercise, answer in results:
        node = expr.parse(exercise)
        assert node.operator_count() <= MAX_OPERATORS
        assert expr.check_constraints(node, 10)
        assert node.evaluate().to_string() == answer
        keys.add(node.canonical_key())
    assert len(keys) == len(results)


def test_generate_no_negative_and_division_proper():
    results, _ = generator.generate(200, 20, seed=7)
    for exercise, _ in results:
        node = expr.parse(exercise)
        for item in node.iter_binops():
            value = item.evaluate()
            assert value >= Fraction(0)
            if item.op == expr.OP_DIV:
                assert value.is_proper()


def test_generate_operands_within_range():
    results, _ = generator.generate(200, 12, seed=11)
    for exercise, _ in results:
        node = expr.parse(exercise)
        for value in node.operands():
            assert 0 <= value.num < 12
            if value.den != 1:
                assert value.den < 12


def test_generate_seed_is_reproducible():
    first, _ = generator.generate(20, 15, seed=99)
    second, _ = generator.generate(20, 15, seed=99)
    assert first == second


def test_generate_insufficient_space():
    results, complete = generator.generate(1000, 1, seed=1)
    assert not complete
    assert len(results) < 1000


def test_generate_large_scale():
    start = time.time()
    results, complete = generator.generate(10000, 100, seed=2024)
    elapsed = time.time() - start
    assert complete
    assert len(results) == 10000
    keys = {expr.parse(exercise).canonical_key() for exercise, _ in results}
    assert len(keys) == 10000
    assert elapsed < 60
