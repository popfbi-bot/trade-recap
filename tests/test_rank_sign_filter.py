"""判据（Issue #4）：最赚 / 最亏榜单必须按净盈亏符号过滤。

规则：
- 「最亏的三笔」只列 net_pnl < 0 的交易，不足 3 笔就有几笔列几笔；一笔不亏写「本期没有亏损交易」。
- 「最赚的三笔」只列 net_pnl > 0 的交易，同理；一笔不赚写「本期没有盈利交易」。
- 打码只改渲染，不许改变「哪几笔上榜」。

每个用例都自己在临时目录里写 CSV，不碰 fixtures/ 与仓库里的其它文件。
"""

import ast
import os
import re
import tempfile
import unittest
from decimal import Decimal, InvalidOperation

from tests.helpers import ROOT, run_cli

D = Decimal
HEADER = "成交日期,证券代码,买卖标志,成交价格,成交数量,成交金额,手续费\n"

# 四笔全赚：A +188.80 / C +89.40 / D +89.50 / E +79.00
ALL_WIN = HEADER + (
    "2026-01-05,600000,买入,10.00,100,1000.00,5.00\n"
    "2026-01-10,600000,卖出,12.00,100,1200.00,6.20\n"
    "2026-02-02,600519,买入,100.00,10,1000.00,5.10\n"
    "2026-02-20,600519,卖出,110.00,10,1100.00,5.50\n"
    "2026-03-02,000001,买入,20.00,50,1000.00,5.00\n"
    "2026-03-06,000001,卖出,22.00,50,1100.00,5.50\n"
    "2026-04-01,600036,买入,30.00,100,3000.00,5.00\n"
    "2026-04-08,600036,卖出,30.90,100,3090.00,6.00\n"
)

# 只有 1 笔亏损（-109.50），其余 3 笔盈利
ONE_LOSS = HEADER + (
    "2026-01-05,600000,买入,10.00,100,1000.00,5.00\n"
    "2026-01-10,600000,卖出,12.00,100,1200.00,6.20\n"
    "2026-01-08,000001,买入,20.00,50,1000.00,5.00\n"
    "2026-01-15,000001,卖出,18.00,50,900.00,4.50\n"
    "2026-02-02,600519,买入,100.00,10,1000.00,5.10\n"
    "2026-02-20,600519,卖出,110.00,10,1100.00,5.50\n"
    "2026-03-02,000001,买入,20.00,50,1000.00,5.00\n"
    "2026-03-06,000001,卖出,22.00,50,1100.00,5.50\n"
)

# 三笔全亏：-109.50 / -87.10 / -24.00
ALL_LOSS = HEADER + (
    "2026-01-08,000001,买入,20.00,50,1000.00,5.00\n"
    "2026-01-15,000001,卖出,18.00,50,900.00,4.50\n"
    "2026-02-02,600519,买入,100.00,10,1000.00,5.10\n"
    "2026-02-20,600519,卖出,92.30,10,923.00,5.00\n"
    "2026-03-02,600036,买入,30.00,100,3000.00,5.00\n"
    "2026-03-06,600036,卖出,29.86,100,2986.00,5.00\n"
)


def recap(csv_text, *extra, filename="trades.csv"):
    """在临时目录里生成报告，返回 (md, html, stdout)。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(csv_text)
        code, out, err = run_cli(["recap", path, "--mapping", "generic-cn", *extra], cwd=tmp)
        assert code == 0, err
        with open(os.path.join(tmp, "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        with open(os.path.join(tmp, "report.html"), encoding="utf-8") as fh:
            page = fh.read()
    return md, page, out


def section(md, title):
    """取出 markdown 里某个「## 标题」到下一个二级标题之间的正文。"""
    m = re.search(r"^## " + re.escape(title) + r".*?$(.*?)(?=^## |\Z)", md, re.S | re.M)
    assert m, f"报告里找不到小节：{title}"
    return m.group(1)


def pnl_column(block):
    """把榜单表格里的「净盈亏」列解析成 Decimal 列表；没有表格返回 []。

    --mask 下该列是相对百分比（如 57.9%），解析不出金额，返回 []。
    """
    values = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or cells[0] in ("代码", "---") or set(cells[0]) <= {"-"}:
            continue
        raw = cells[4].replace(" 元", "").replace("+", "")
        try:
            values.append(D(raw))
        except InvalidOperation:
            continue
    return values


class AllWinTest(unittest.TestCase):
    """判据 1：全部盈利 →「最亏的三笔」不出现任何正数，或明确说本期没有亏损交易。"""

    def test_worst_is_empty_not_filled_with_wins(self):
        md, page, _ = recap(ALL_WIN)
        block = section(md, "最亏的三笔（净盈亏 < 0）")
        self.assertEqual(pnl_column(block), [])
        self.assertIn("本期没有亏损交易", block)
        self.assertNotIn("| 600000 |", block)
        # html 同样不留空表
        self.assertIn("本期没有亏损交易", page)

    def test_best_still_lists_three_wins(self):
        md, _, _ = recap(ALL_WIN)
        self.assertEqual(
            pnl_column(section(md, "最赚的三笔（净盈亏 > 0）")),
            [D("188.80"), D("89.50"), D("89.40")],
        )


class OneLossTest(unittest.TestCase):
    """判据 2：只有 1 笔亏损 → 榜单恰好 1 行，且净盈亏 < 0。"""

    def test_exactly_one_row_and_negative(self):
        md, _, _ = recap(ONE_LOSS)
        values = pnl_column(section(md, "最亏的三笔（净盈亏 < 0）"))
        self.assertEqual(len(values), 1)
        self.assertEqual(values, [D("-109.50")])
        self.assertLess(values[0], 0)
        self.assertNotIn("本期没有亏损交易", md)

    def test_best_does_not_include_the_loss(self):
        md, _, _ = recap(ONE_LOSS)
        values = pnl_column(section(md, "最赚的三笔（净盈亏 > 0）"))
        self.assertEqual(values, [D("188.80"), D("89.50"), D("89.40")])
        self.assertTrue(all(v > 0 for v in values))


class AllLossTest(unittest.TestCase):
    """判据 3：全部亏损 →「最赚的三笔」不出现任何负数。"""

    def test_best_is_empty_not_filled_with_losses(self):
        md, page, _ = recap(ALL_LOSS)
        block = section(md, "最赚的三笔（净盈亏 > 0）")
        self.assertEqual(pnl_column(block), [])
        self.assertIn("本期没有盈利交易", block)
        self.assertIn("本期没有盈利交易", page)

    def test_worst_lists_three_losses_ascending(self):
        md, _, _ = recap(ALL_LOSS)
        self.assertEqual(
            pnl_column(section(md, "最亏的三笔（净盈亏 < 0）")),
            [D("-109.50"), D("-87.10"), D("-24.00")],
        )


class MaskKeepsRankingTest(unittest.TestCase):
    """判据 4：--mask 只去数值，不改变「哪几笔上榜」。"""

    def test_same_trades_on_board_when_masked(self):
        plain_md, plain_html, plain_out = recap(ONE_LOSS)
        mask_md, mask_html, mask_out = recap(ONE_LOSS, "--mask")

        plain_block = section(plain_md, "最亏的三笔（净盈亏 < 0）")
        mask_block = section(mask_md, "最亏的三笔（净盈亏 < 0）")
        # 行数不变（打码后净盈亏列是百分比，数不了钱，只数行数与日期区间）
        self.assertEqual(len(pnl_column(plain_block)), 1)
        self.assertEqual(len([ln for ln in mask_block.splitlines() if "00****" in ln]), 1)
        self.assertIn("000001 | 2026-01-08 → 2026-01-15", plain_block)
        self.assertIn("00**** | 2026-01-08 → 2026-01-15", mask_block)
        # 真实金额与真实代码不得泄漏
        for secret in ("109.50", "000001"):
            self.assertIn(secret, plain_block)
            self.assertNotIn(secret, mask_block)
        self.assertNotIn("109.50", plain_out)
        self.assertNotIn("109.50", mask_out)

    def test_empty_rank_stays_empty_when_masked(self):
        mask_md, _, _ = recap(ALL_WIN, "--mask")
        block = section(mask_md, "最亏的三笔（净盈亏 < 0）")
        self.assertEqual(pnl_column(block), [])
        self.assertIn("本期没有亏损交易", block)


class RankingIsSignFilteredAtSourceTest(unittest.TestCase):
    """榜单在 metrics 层就过滤好了，渲染层拿不到「用盈利笔填坑」的数据。"""

    def test_metrics_best_worst_are_sign_pure(self):
        import sys

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from core.loader import load_csv, load_mapping
        from core.metrics import compute_metrics, months_covered, sum_buy_amount, sum_fees
        from core.pair import pair_fifo

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trades.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ONE_LOSS)
            loaded = load_csv(path, load_mapping("generic-cn"), "generic-cn")
        paired = pair_fifo(loaded.rows)
        m = compute_metrics(
            paired.closed,
            sum_buy_amount(loaded.rows),
            sum_fees(loaded.rows),
            months_covered(loaded.rows),
        )
        self.assertTrue(all(t.net_pnl > 0 for t in m["best"]))
        self.assertTrue(all(t.net_pnl < 0 for t in m["worst"]))
        self.assertEqual(len(m["worst"]), m["loss_count"])

    def test_no_sign_filtering_left_in_renderer(self):
        """防止有人把过滤挪回渲染层（那边没有符号信息，只会重新出错）。"""
        with open(os.path.join(ROOT, "core", "metrics.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        src = ast.unparse(tree)
        self.assertIn("'best'", src.replace('"', "'"))
        self.assertIn("wins", src)
        self.assertIn("losses", src)


class GrossProfitNamingTest(unittest.TestCase):
    """「毛盈利」改名为 net_win_sum，口径写进报告：盈利笔的净盈亏之和。"""

    def test_metric_exposes_both_names_with_same_value(self):
        import sys

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from core.loader import load_csv, load_mapping
        from core.metrics import compute_metrics, months_covered, sum_buy_amount, sum_fees
        from core.pair import pair_fifo

        from tests.helpers import fixture

        loaded = load_csv(fixture("synthetic.csv"), load_mapping("generic-cn"), "generic-cn")
        paired = pair_fifo(loaded.rows)
        m = compute_metrics(
            paired.closed,
            sum_buy_amount(loaded.rows),
            sum_fees(loaded.rows),
            months_covered(loaded.rows),
        )
        # 净额口径：188.80 + 89.40 + 89.50 = 367.70
        self.assertEqual(m["net_win_sum"], D("367.70"))
        self.assertEqual(m["gross_profit"], m["net_win_sum"])
        # 毛额口径另算：+200.00 + 100.00 + 100.00 = 400.00，两者必须可区分
        self.assertEqual(m["net_win_gross_sum"], D("400.00"))
        self.assertEqual(m["cost_ratio"], D("41.80") / D("367.70"))

    def test_report_states_the_convention(self):
        md, page, _ = recap(ONE_LOSS)
        self.assertIn("| 毛盈利 `net_win_sum` |", md)
        self.assertIn("净盈亏", md)
        self.assertIn("毛盈利 net_win_sum", md)
        self.assertIn("net_win_sum", page)


if __name__ == "__main__":
    unittest.main()
