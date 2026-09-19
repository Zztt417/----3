"""表达式 AST：求值、约束校验、规范化（判重）、渲染与解析。"""

from fraction import Fraction, FractionError

OP_ADD = "+"
OP_SUB = "-"
OP_MUL = "*"
OP_DIV = "/"


MAX_OPERATORS = 3

# 内部算子 -> 展示符号
DISPLAY = {OP_ADD: "+", OP_SUB: "−", OP_MUL: "×", OP_DIV: "÷"}
# 优先级：+ − 为 1，× ÷ 为 2
PRECEDENCE = {OP_ADD: 1, OP_SUB: 1, OP_MUL: 2, OP_DIV: 2}
# 满足交换律的算子
COMMUTATIVE = {OP_ADD, OP_MUL}


class ExpressionError(ValueError):
    """表达式相关错误。"""


class Node:
    """表达式节点基类。"""

    def evaluate(self):
        raise NotImplementedError

    def operator_count(self):
        raise NotImplementedError

    def operands(self):
        """返回表达式中出现的所有操作数（叶子节点值）。"""
        raise NotImplementedError

    def canonical_key(self):
        """交换律意义下的判重键。"""
        raise NotImplementedError

    def render(self):
        """渲染为可直接输出的字符串。"""
        raise NotImplementedError


class Num(Node):
    """叶子节点：一个自然数或真分数。"""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value if isinstance(value, Fraction) else Fraction(value)

    def evaluate(self):
        return self.value

    def operator_count(self):
        return 0

    def operands(self):
        return [self.value]

    def canonical_key(self):
        return f"#{self.value.num}/{self.value.den}"

    def render(self):
        return self.value.to_string()

    def __repr__(self):
        return f"Num({self.value})"


class BinOp(Node):
    """二元运算节点。"""

    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        if op not in PRECEDENCE:
            raise ExpressionError(f"未知运算符：{op}")
        self.op = op
        self.left = left
        self.right = right

    def evaluate(self):
        left = self.left.evaluate()
        right = self.right.evaluate()
        if self.op == OP_ADD:
            return left + right
        if self.op == OP_SUB:
            return left - right
        if self.op == OP_MUL:
            return left * right
        if right == Fraction(0):
            raise ExpressionError("除数为 0")
        return left / right

    def operator_count(self):
        return 1 + self.left.operator_count() + self.right.operator_count()

    def operands(self):
        return self.left.operands() + self.right.operands()

    def iter_binops(self):
        """按前序遍历返回所有二元运算节点。"""
        yield self
        if isinstance(self.left, BinOp):
            yield from self.left.iter_binops()
        if isinstance(self.right, BinOp):
            yield from self.right.iter_binops()

    def canonical_key(self):
        left = self.left.canonical_key()
        right = self.right.canonical_key()
        if self.op in COMMUTATIVE and left > right:
            left, right = right, left
        return f"{self.op}({left},{right})"

    def render(self):
        left = _render_child(self.left, self.op, is_right=False)
        right = _render_child(self.right, self.op, is_right=True)
        return f"{left} {DISPLAY[self.op]} {right}"

    def __repr__(self):
        return f"BinOp({self.op!r}, {self.left!r}, {self.right!r})"


def _render_child(child, parent_op, is_right):
    text = child.render()
    if isinstance(child, Num):
        return text
    child_prec = PRECEDENCE[child.op]
    parent_prec = PRECEDENCE[parent_op]
    if is_right:
        need = child_prec <= parent_prec
    else:
        need = child_prec < parent_prec
    return f"({text})" if need else text


def check_constraints(node, r):
    """校验题目是否满足 PRD 3.1.2 的全部约束。"""
    if node.operator_count() > MAX_OPERATORS:
        return False
    # 操作数范围：自然数 n < r；真分数分子、分母均 < r
    for value in node.operands():
        if value.num < 0 or value.num >= r:
            return False
        if value.den != 1 and value.den >= r:
            return False
    if not isinstance(node, BinOp):
        return False
    for item in node.iter_binops():
        result = item.evaluate()
        # 无负数中间结果
        if result.num < 0:
            return False
        # 除法结果必须是真分数
        if item.op == OP_DIV and not result.is_proper():
            return False
    return True


# --------------------------------------------------------------------------
# 解析：将渲染出的字符串还原为 AST（供批改模式重算答案）
# --------------------------------------------------------------------------

_OPERATOR_CHARS = {
    "+": OP_ADD,
    "-": OP_SUB,
    "−": OP_SUB,
    "*": OP_MUL,
    "×": OP_MUL,
    "/": OP_DIV,
    "÷": OP_DIV,
}


def _to_fraction(text, origin):
    try:
        return Fraction.from_string(text)
    except FractionError as error:
        raise ExpressionError(f"非法数字：{origin}（{error}）")


def tokenize(text):
    """将表达式切分为 token 列表，token 为 ('num', Fraction) 或 ('op', 字符)。"""
    tokens = []
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == "(":
            tokens.append(("(", char))
            i += 1
            continue
        if char == ")":
            tokens.append((")", char))
            i += 1
            continue
        if char in _OPERATOR_CHARS:
            tokens.append(("op", _OPERATOR_CHARS[char]))
            i += 1
            continue
        if char.isdigit():
            j = i
            while j < length and text[j].isdigit():
                j += 1
            whole = text[i:j]
            if j < length and text[j] == "'":
                k = j + 1
                while k < length and text[k].isdigit():
                    k += 1
                numerator = text[j + 1:k]
                if k >= length or text[k] != "/" or not whole or not numerator:
                    raise ExpressionError(f"非法带分数：{text}")
                m = k + 1
                while m < length and text[m].isdigit():
                    m += 1
                denominator = text[k + 1:m]
                if not denominator:
                    raise ExpressionError(f"非法带分数：{text}")
                tokens.append(("num", _to_fraction(f"{whole}'{numerator}/{denominator}", text)))
                i = m
                continue
            if j < length and text[j] == "/":
                m = j + 1
                while m < length and text[m].isdigit():
                    m += 1
                denominator = text[j + 1:m]
                if not denominator:
                    raise ExpressionError(f"非法分数：{text}")
                tokens.append(("num", _to_fraction(f"{whole}/{denominator}", text)))
                i = m
                continue
            tokens.append(("num", Fraction(int(whole))))
            i = j
            continue
        raise ExpressionError(f"无法识别的字符：{char}")
    if not tokens:
        raise ExpressionError("表达式为空")
    return tokens


def parse(text):
    """递归下降解析表达式字符串，返回 AST 根节点。"""
    tokens = tokenize(text)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def parse_expr():
        nonlocal pos
        node = parse_term()
        while True:
            token = peek()
            if token is None or token[0] != "op" or token[1] not in (OP_ADD, OP_SUB):
                return node
            pos += 1
            node = BinOp(token[1], node, parse_term())

    def parse_term():
        nonlocal pos
        node = parse_factor()
        while True:
            token = peek()
            if token is None or token[0] != "op" or token[1] not in (OP_MUL, OP_DIV):
                return node
            pos += 1
            node = BinOp(token[1], node, parse_factor())

    def parse_factor():
        nonlocal pos
        token = peek()
        if token is None:
            raise ExpressionError("表达式意外结束")
        if token[0] == "num":
            pos += 1
            return Num(token[1])
        if token[0] == "(":
            pos += 1
            node = parse_expr()
            closing = peek()
            if closing is None or closing[0] != ")":
                raise ExpressionError("括号不匹配")
            pos += 1
            return node
        raise ExpressionError(f"意外的记号：{token[1]}")

    node = parse_expr()
    if pos != len(tokens):
        raise ExpressionError(f"存在多余内容：{text}")
    return node


def format_expression(node):
    """题目行格式：<表达式> = """
    return f"{node.render()} = "
