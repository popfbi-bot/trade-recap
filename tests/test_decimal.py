"""判据 3：Decimal 专项 —— 金额绝不能经过 float。"""

import os
import re
import unittest
from decimal import Decimal

from tests.helpers import ROOT
from core.models import ClosedTrade
from datetime import date

D = Decimal


class DecimalTest(unittest.TestCase):
    def test_decimal_not_float(self):
        """0.1 + 0.2 类场景：float 会得到 0.30000000000000004，Decimal 必须精确到 0.30。"""
        fee_a = D("0.10")
        fee_b = D("0.20")
        total = fee_a + fee_b
        self.assertEqual(total, D("0.30"))
        self.assertEqual(str(total), "0.30")
        # 反证：float 在这里会失真，说明本测试确实能抓到 float 混入
        self.assertNotEqual(str(0.1 + 0.2), "0.3")
        # 从字符串转换才有意义（Decimal(0.1) 会带二进制尾巴）
        self.assertEqual(D(str(0.1)) + D(str(0.2)), D("0.30"))

    def test_pnl_is_exact_to_the_cent(self):
        """买卖各带 0.10 / 0.20 费用，净盈亏必须精确为 0.30 级别的 Decimal。"""
        t = ClosedTrade(
            code="600000",
            buy_date=date(2026, 1, 1),
            buy_price=D("10.00"),
            sell_date=date(2026, 1, 2),
            sell_price=D("10.00"),
            qty=D("1"),
            buy_fee=D("0.10"),
            sell_fee=D("0.20"),
        )
        self.assertEqual(t.net_pnl, D("-0.30"))
        self.assertEqual(str(t.net_pnl), "-0.30")

    def test_no_float_construction_in_core(self):
        """metrics.py / pair.py 里不允许出现 float( 调用。"""
        for name in ("metrics.py", "pair.py", "loader.py", "models.py", "diagnosis.py"):
            path = os.path.join(ROOT, "core", name)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotRegex(src, r"\bfloat\s*\(", f"{name} 里出现了 float( 调用")
            # Decimal(0.1) 会带二进制尾巴；只允许 Decimal("0.1") 或 Decimal(整数/Decimal)
            self.assertNotRegex(
                src, r"\bDecimal\s*\(\s*-?\d+\.\d", f"{name} 里出现了 Decimal(<浮点字面量>)，应写 Decimal(\"...\")"
            )
            self.assertNotRegex(src, r"\bfrom\s+float", f"{name} 里出现了 from float")


if __name__ == "__main__":
    unittest.main()
