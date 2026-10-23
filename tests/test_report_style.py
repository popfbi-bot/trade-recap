"""判据（Issue #10）：报告配色的语义方向 + --out 路径错误的友好提示。

配色约定（写死在这儿，别再改反）：
- 盈利（net_pnl > 0）= 红，亏损（net_pnl < 0）= 绿。
  与 life-kline 的「阳红阴绿」统一，也符合 A 股「红涨绿跌」的直觉。
- 行为诊断「命中」= 橙（这条要改），「未命中」= 灰蓝（无事发生）。
  灰蓝不能变回绿色——绿色已经表示「亏损」，一个颜色只能有一个意思。

--out 约定：目标目录不存在时，给一句能照做的中文提示，退出码 1，
不许甩裸 traceback 给用户。
"""

import os
import re
import tempfile
import unittest

from tests.helpers import fixture, run_cli

HEADER = "成交日期,证券代码,买卖标志,成交价格,成交数量,成交金额,手续费\n"

# 两笔：一盈一亏，用来验 class 归属
ONE_WIN_ONE_LOSS = HEADER + (
    "2026-01-05,600000,买入,10.00,100,1000.00,5.00\n"
    "2026-01-10,600000,卖出,12.00,100,1200.00,6.20\n"
    "2026-01-08,000001,买入,20.00,50,1000.00,5.00\n"
    "2026-01-15,000001,卖出,18.00,50,900.00,4.50\n"
)


def css_color(html: str, cls: str) -> str:
    """从 <style> 里取 .cls{...color:#xxxxxx} 的颜色值。"""
    m = re.search(rf"\.{cls}\{{[^}}]*color:(#[0-9a-fA-F]{{6}})", html)
    if not m:
        raise AssertionError(f"样式表里找不到 .{cls} 的颜色定义")
    return m.group(1).lower()


class ReportColorTest(unittest.TestCase):
    """配色方向。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        csv_path = os.path.join(self.tmp.name, "t.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(ONE_WIN_ONE_LOSS)
        out = os.path.join(self.tmp.name, "report.html")
        code, _, err = run_cli(["recap", csv_path, "--out", out])
        self.assertEqual(code, 0, err)
        with open(out, encoding="utf-8") as fh:
            self.html = fh.read()

    def test_profit_is_red_and_loss_is_green(self):
        """盈利红、亏损绿——这是本次改动要钉住的那条。"""
        self.assertEqual(css_color(self.html, "pos"), "#ff6b6b", "盈利应该是红色")
        self.assertEqual(css_color(self.html, "neg"), "#5fd08a", "亏损应该是绿色")

    def test_unhit_is_not_green(self):
        """未命中不能是绿色：绿色已经表示「亏损」，一个颜色只能有一个意思。"""
        ok_color = css_color(self.html, "ok")
        self.assertNotEqual(
            ok_color, "#5fd08a", "「未命中」不能和「亏损」用同一个绿色"
        )
        self.assertEqual(css_color(self.html, "hit"), "#ff8a5c", "命中应该是橙色")

    def test_profit_row_carries_pos_class(self):
        """盈利那笔的净额单元格必须真的带 pos class（不能只是改了样式表）。"""
        profit_row = [ln for ln in self.html.splitlines() if "188.80" in ln]
        self.assertTrue(profit_row, "报告里找不到盈利那笔的净额")
        self.assertIn("pos", profit_row[0])

    def test_loss_row_carries_neg_class(self):
        loss_row = [ln for ln in self.html.splitlines() if "-109.50" in ln]
        self.assertTrue(loss_row, "报告里找不到亏损那笔的净额")
        self.assertIn("neg", loss_row[0])


class OutPathErrorTest(unittest.TestCase):
    """--out 指向不存在的目录时，不许甩裸 traceback。"""

    def test_missing_output_dir_gives_friendly_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "t.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(ONE_WIN_ONE_LOSS)
            missing = os.path.join(tmp, "no-such-dir", "report.md")
            code, out, err = run_cli(["recap", csv_path, "--out", missing])

        self.assertEqual(code, 1, "目录不存在应退出码 1")
        self.assertNotIn("Traceback", err, "不许甩裸 traceback")
        self.assertNotIn("FileNotFoundError", err)
        self.assertIn("目录不存在", err)
        self.assertIn("no-such-dir", err)

    def test_existing_output_dir_still_works(self):
        """正常的 --out 不能被这个改动弄坏。"""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "t.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(ONE_WIN_ONE_LOSS)
            out_path = os.path.join(tmp, "report.md")
            code, _, err = run_cli(["recap", csv_path, "--out", out_path])
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(out_path))
            self.assertTrue(os.path.exists(os.path.join(tmp, "report.html")))


if __name__ == "__main__":
    unittest.main()
