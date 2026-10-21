"""分数类：约分、四则运算、与整数互转、格式化输出。"""

from math import gcd


class FractionError(ValueError):
    """分数相关错误。"""


class Fraction:
    """不可变分数，内部保证约分且分母为正。"""

    __slots__ = ("num", "den")

    def __init__(self, num, den=1):
        if not isinstance(num, int) or not isinstance(den, int):
            raise FractionError("分子和分母必须是整数")
        if den == 0:
            raise FractionError("分母不能为 0")
        if den < 0:
            num, den = -num, -den
        common = gcd(abs(num), den)
        self.num = num // common
        self.den = den // common

    # ---------- 四则运算 ----------

    def __add__(self, other):
        other = _coerce(other)
        return Fraction(self.num * other.den + other.num * self.den, self.den * other.den)

    def __sub__(self, other):
        other = _coerce(other)
        return Fraction(self.num * other.den - other.num * self.den, self.den * other.den)

    def __mul__(self, other):
        other = _coerce(other)
        return Fraction(self.num * other.num, self.den * other.den)

    def __truediv__(self, other):
        other = _coerce(other)
        if other.num == 0:
            raise FractionError("除数不能为 0")
        return Fraction(self.num * other.den, self.den * other.num)

    __radd__ = __add__
    __rmul__ = __mul__

    def __rsub__(self, other):
        return _coerce(other).__sub__(self)

    def __rtruediv__(self, other):
        return _coerce(other).__truediv__(self)

    # ---------- 比较 ----------

    def __eq__(self, other):
        other = _coerce(other)
        return self.num == other.num and self.den == other.den

    def __lt__(self, other):
        other = _coerce(other)
        return self.num * other.den < other.num * self.den

    def __le__(self, other):
        other = _coerce(other)
        return self.num * other.den <= other.num * self.den

    def __gt__(self, other):
        other = _coerce(other)
        return self.num * other.den > other.num * self.den

    def __ge__(self, other):
        other = _coerce(other)
        return self.num * other.den >= other.num * self.den

    def __hash__(self):
        return hash((self.num, self.den))

    # ---------- 转换与格式化 ----------

    def is_proper(self):
        """是否为真分数（分子 < 分母，且为正）。"""
        return 0 < self.num < self.den

    def is_integer(self):
        return self.den == 1

    def to_string(self):
        """整数输出为 n，真分数输出为 n/d，其余输出为带分数 a'b/c。"""
        if self.den == 1:
            return str(self.num)
        sign = "-" if self.num < 0 else ""
        num = abs(self.num)
        if num < self.den:
            return f"{sign}{num}/{self.den}"
        whole, remain = divmod(num, self.den)
        return f"{sign}{whole}'{remain}/{self.den}"

    @classmethod
    def from_string(cls, text):
        """解析 n、n/d、a'b/c 三种形式。"""
        if not isinstance(text, str):
            raise FractionError("分数必须是字符串")
        s = text.strip().replace(" ", "")
        if not s:
            raise FractionError("分数不能为空")
        sign = 1
        if s[0] in "+-−":
            if s[0] in "-−":
                sign = -1
            s = s[1:]
        if "'" in s:
            whole_text, frac_text = s.split("'", 1)
            if "/" not in frac_text:
                raise FractionError(f"非法带分数：{text}")
            whole = _parse_int(whole_text, text)
            num_text, den_text = frac_text.split("/", 1)
            num = _parse_int(num_text, text)
            den = _parse_int(den_text, text)
            if den == 0:
                raise FractionError(f"分母不能为 0：{text}")
            if num >= den:
                raise FractionError(f"带分数的小数部分必须是真分数：{text}")
            return cls(sign * (whole * den + num), den)
        if "/" in s:
            num_text, den_text = s.split("/", 1)
            num = _parse_int(num_text, text)
            den = _parse_int(den_text, text)
            if den == 0:
                raise FractionError(f"分母不能为 0：{text}")
            return cls(sign * num, den)
        return cls(sign * _parse_int(s, text))

    def __str__(self):
        return self.to_string()

    def __repr__(self):
        return f"Fraction({self.num}, {self.den})"


def _coerce(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    raise FractionError(f"不支持的操作数类型：{type(value).__name__}")


def _parse_int(text, origin):
    if not text.isdigit():
        raise FractionError(f"非法数字：{origin}")
    return int(text)
