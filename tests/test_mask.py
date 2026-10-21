"""判据 7：打码不得改动任何统计结果。

原则：打码只发生在渲染层。胜率、盈亏比、笔数、平均持仓天数这类比率/计数完全不变；
绝对值金额改为「占最大单笔盈利额的比例」，读者仍能比较大小，但读不出真实金额。
"""

import os
import tempfile
import unittest
from decimal import Decimal

from tests.helpers import fixture, run_cli

D = Decimal


def run(tmp, *extra):
    code, out, err = run_cli(
        ["recap", fixture("synthetic.csv"), "--mapping", "generic-cn", "--year", "2026", *extra], cwd=tmp
    )
    assert code == 0, err
    with open(os.path.join(tmp, "report.md"), encoding="utf-8") as fh:
        return fh.read(), out


class MaskTest(unittest.TestCase):
    def test_mask_does_not_change_ratios(self):
        with tempfile.TemporaryDirectory() as plain_dir, tempfile.TemporaryDirectory() as mask_dir:
            plain_md, plain_out = run(plain_dir)
            mask_md, mask_out = run(mask_dir, "--mask")

            # 比率类与计数：两版完全一致
            for token in ("胜率 75.0%", "盈亏比 1.12", "| 完整交易数 | 4 笔", "平均持仓天数 | 8.5 天", "| 50.0%"):
                self.assertIn(token, plain_md)
                self.assertIn(token, mask_md)

            # 绝对金额：打码版不得出现真实金额，代码不得完整出现
            for secret in ("258.20", "109.50", "188.80", "600000", "600519"):
                self.assertIn(secret, plain_md)
                self.assertNotIn(secret, mask_md)

    def test_mask_shows_codes_and_amounts_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            mask_md, mask_out = run(tmp, "--mask")
            self.assertIn("60****", mask_md)
            self.assertIn("00****", mask_md)
            # 汇总类金额显示为 Σ，相对金额显示百分比
            self.assertIn("Σ", mask_md)
            self.assertIn("100.0%", mask_md)
            # 终端摘要同样打码
            self.assertNotIn("258.20", mask_out)

    def test_mask_keeps_diagnosis_values(self):
        """诊断项本身的数值是比率/天数，打码后必须一字不变。"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            plain, _ = run(a)
            masked, _ = run(b, "--mask")
            for token in ("50.0%", "1.3", "11.4%"):
                self.assertIn(token, plain)
                self.assertIn(token, masked)


if __name__ == "__main__":
    unittest.main()
