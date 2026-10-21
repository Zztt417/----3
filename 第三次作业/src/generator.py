"""题目生成器：随机生成、约束修正、去重、批量生成。"""

import random

from expression import (
    OP_ADD,
    OP_DIV,
    OP_MUL,
    OP_SUB,
    BinOp,
    Num,
    check_constraints,
)
from fraction import Fraction

OPERATORS = (OP_ADD, OP_SUB, OP_MUL, OP_DIV)

# 生成真分数作为操作数的概率（需 r >= 3）
FRACTION_PROBABILITY = 0.3

# 连续失败多少次后认为题目空间耗尽
MAX_CONSECUTIVE_FAILURES = 20000

ZERO = Fraction(0)


class GenerationError(ValueError):
    """题目生成错误。"""


def random_leaf(rng, r):
    """随机生成一个满足范围的叶子操作数。"""
    if r >= 3 and rng.random() < FRACTION_PROBABILITY:
        denominator = rng.randint(2, r - 1)
        numerator = rng.randint(1, denominator - 1)
        return Num(Fraction(numerator, denominator))
    return Num(Fraction(rng.randint(0, r - 1)))


def build(rng, operators, r):
    """自底向上构造带 operators 个运算符的表达式；无法满足约束时返回 None。"""
    if operators <= 0:
        return random_leaf(rng, r)

    op = rng.choice(OPERATORS)
    left_ops = rng.randint(0, operators - 1)
    right_ops = operators - 1 - left_ops
    left = build(rng, left_ops, r)
    right = build(rng, right_ops, r)
    if left is None or right is None:
        return None

    left_value = left.evaluate()
    right_value = right.evaluate()

    if op == OP_SUB:
        # 保证左值 >= 右值，避免负数中间结果
        if left_value < right_value:
            left, right = right, left
    elif op == OP_DIV:
        # 保证左值 < 右值且左值 > 0，使结果为真分数
        if left_value == right_value:
            return None
        if left_value > right_value:
            left, right = right, left
        if left.evaluate() <= ZERO:
            return None

    return BinOp(op, left, right)


def generate(n, r, seed=None):
    """生成 n 道 r 以内、互不重复且满足约束的题目。

    返回 (results, complete)，results 为 [(表达式字符串, 答案字符串), ...]，
    complete 表示是否成功生成满 n 道题。
    """
    if n <= 0:
        raise GenerationError("题目数量必须大于 0")
    if r < 1:
        raise GenerationError("数值范围 -r 必须至少为 1")

    rng = random.Random(seed)
    seen = set()
    results = []
    failures = 0

    while len(results) < n and failures < MAX_CONSECUTIVE_FAILURES:
        node = build(rng, rng.randint(1, 3), r)
        if node is None or not check_constraints(node, r):
            failures += 1
            continue
        key = node.canonical_key()
        if key in seen:
            failures += 1
            continue
        seen.add(key)
        results.append((node.render(), node.evaluate().to_string()))
        failures = 0

    return results, len(results) == n
