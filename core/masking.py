"""--mask：金额与代码打码，但统计结果不许失真。

规则（先想清楚再看代码）：
- 打码只发生在「渲染」这一步，模型层照常算全精度。
- 比率类指标（胜率、盈亏比、占比、成本占比、平均持仓天数）与笔数、天数完全不变。
- 绝对值类金额（盈亏、费用、平均盈利额…）不是「不变」，而是改为显示比例：
  以「最大单笔盈利额」为 100%，其它金额显示成它的百分比；总和显示为 Σ（不可反推）。
  这样读者仍能看出「这笔是第一名的 62%」，却读不出真实金额。
- 代码显示前 2 位 + ****，如 600000 → 60****。
"""

from decimal import Decimal

MASK = "***"
SUM_MASK = "Σ"


def mask_code(code: str) -> str:
    """代码只留前 2 位。"""
    if not code:
        return MASK
    return code[:2] + "****"


def mask_amount(_value, unit: Decimal) -> str:
    """把金额换成相对单位：value / unit 的百分比。unit 为 0 时退化为 `***`。"""
    if unit is None or Decimal(unit) == 0:
        return MASK
    return f"{Decimal(_value) / Decimal(unit) * 100:.1f}%"

class Masker:
    """渲染期的打码器。enabled=False 时所有方法原样返回真实值。"""

    def __init__(self, enabled: bool, unit: Decimal = None):
        self.enabled = bool(enabled)
        # unit：金额单位（最大单笔盈利额），仅打码时使用
        self.unit = unit

    def code(self, code: str) -> str:
        return mask_code(code) if self.enabled else code

    def money(self, value, suffix: str = " 元") -> str:
        if value is None:
            return "—"
        if not self.enabled:
            return f"{Decimal(value):.2f}{suffix}"
        return mask_amount(value, self.unit)

    def total(self, value) -> str:
        """汇总类金额：打码后不可反推，只能显示符号。"""
        if value is None:
            return "—"
        if not self.enabled:
            return f"{Decimal(value):.2f} 元"
        return SUM_MASK

    def qty(self, value) -> str:
        if not self.enabled:
            return f"{Decimal(value):.0f} 股"
        return MASK
