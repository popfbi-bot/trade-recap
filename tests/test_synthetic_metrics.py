"""判据 1：fixtures/synthetic.csv 的每个期望值都手算，精确到分。

synthetic.csv 内容（8 行）：
  01-05 600000 买 10.00 × 100 = 1000.00 费 5.00
  01-10 600000 卖 12.00 × 100 = 1200.00 费 6.20
  01-08 000001 买 20.00 ×  50 = 1000.00 费 5.00
  01-15 000001 卖 18.00 ×  50 =  900.00 费 4.50
  02-02 600519 买 100.00 × 10 = 1000.00 费 5.10
  02-20 600519 卖 110.00 × 10 = 1100.00 费 5.50
  03-02 000001 买 20.00 ×  50 = 1000.00 费 5.00
  03-06 000001 卖 22.00 ×  50 = 1100.00 费 5.50

四笔完整交易（FIFO 一一对应，无拆分）：
  A 600000 01-05→01-10  毛 (12-10)*100 = +200.00  净 200.00-5.00-6.20 = +188.80  持有 5 天
  B 000001 01-08→01-15  毛 (18-20)*50  = -100.00  净 -100.00-5.00-4.50 = -109.50 持有 7 天
  C 600519 02-02→02-20  毛 (110-100)*10= +100.00  净 100.00-5.10-5.50 = +89.40   持有 18 天
  D 000001 03-02→03-06  毛 (22-20)*50  = +100.00  净 100.00-5.00-5.50 = +89.50   持有 4 天
"""

import unittest
from decimal import Decimal

from tests.helpers import fixture
from core.loader import load_csv, load_mapping
from core.metrics import code_attribution, compute_metrics, concentration, months_covered, sum_buy_amount, sum_fees
from core.pair import pair_fifo

D = Decimal


class SyntheticMetricsTest(unittest.TestCase):
    def setUp(self):
        mapping = load_mapping("generic-cn")
        self.loaded = load_csv(fixture("synthetic.csv"), mapping, "generic-cn")
        self.paired = pair_fifo(self.loaded.rows)
        self.m = compute_metrics(
            self.paired.closed,
            sum_buy_amount(self.loaded.rows),
            sum_fees(self.loaded.rows),
            months_covered(self.loaded.rows),
        )

    def test_four_closed_trades_each_pnl_to_the_cent(self):
        # 期望：每笔净盈亏精确到分，见文件头手算
        expected = [
            ("600000", D("188.80")),
            ("000001", D("-109.50")),
            ("600519", D("89.40")),
            ("000001", D("89.50")),
        ]
        got = [(t.code, t.net_pnl) for t in self.paired.closed]
        self.assertEqual(got, expected)

    def test_hold_days(self):
        # 5 天 / 7 天 / 18 天 / 4 天，均为自然日
        self.assertEqual([t.hold_days for t in self.paired.closed], [5, 7, 18, 4])

    def test_trade_count_and_win_rate(self):
        # 完整交易 4 笔；盈 3 亏 1 → 胜率 3/4 = 0.75
        self.assertEqual(self.m["trade_count"], 4)
        self.assertEqual(self.m["win_count"], 3)
        self.assertEqual(self.m["win_rate"], D("0.75"))

    def test_total_and_gross_profit(self):
        # 净盈亏合计 = 188.80 - 109.50 + 89.40 + 89.50 = 258.20
        # 毛盈利（仅盈利笔）= 188.80 + 89.40 + 89.50 = 367.70
        self.assertEqual(self.m["total_pnl"], D("258.20"))
        self.assertEqual(self.m["gross_profit"], D("367.70"))

    def test_avg_win_loss_and_ratio(self):
        # 平均盈利 = 367.70 / 3 = 122.5666...（不四舍五入，保留 Decimal)
        # 平均亏损 = -109.50
        # 盈亏比 = 122.5666... / 109.50 = 1.1193302891...
        self.assertEqual(self.m["avg_loss"], D("-109.50"))
        self.assertEqual(self.m["avg_win"], D("367.70") / D(3))
        self.assertEqual(self.m["profit_loss_ratio"], (D("367.70") / D(3)) / D("109.50"))

    def test_avg_hold_days(self):
        # (5 + 7 + 18 + 4) / 4 = 34/4 = 8.5
        self.assertEqual(self.m["avg_hold_days"], D("8.5"))

    def test_fee_total_and_cost_ratio(self):
        # 费用合计 = 5.00+6.20+5.00+4.50+5.10+5.50+5.00+5.50 = 41.80
        # 成本占比 = 41.80 / 367.70 = 0.1136796301...
        self.assertEqual(self.m["total_fee"], D("41.80"))
        self.assertEqual(self.m["cost_ratio"], D("41.80") / D("367.70"))

    def test_trades_per_month(self):
        # 覆盖 1..3 月共 3 个月，月均 = 4/3
        self.assertEqual(self.m["trades_per_month"], D(4) / D(3))

    def test_month_attribution(self):
        # 按卖出日归属：1 月 A+B = 188.80-109.50 = 79.30（2 笔）
        # 2 月 C = 89.40（1 笔）；3 月 D = 89.50（1 笔）
        self.assertEqual(self.m["by_month"]["2026-01"]["pnl"], D("79.30"))
        self.assertEqual(self.m["by_month"]["2026-01"]["count"], 2)
        self.assertEqual(self.m["by_month"]["2026-02"]["pnl"], D("89.40"))
        self.assertEqual(self.m["by_month"]["2026-03"]["pnl"], D("89.50"))

    def test_hold_bucket_attribution(self):
        # ≤1天: 无；2–5天: A(5天)+D(4天) = 188.80+89.50 = 278.30，2 笔
        # 6–20天: B(7天)+C(18天) = -109.50+89.40 = -20.10，2 笔；>20天: 无
        b = self.m["by_bucket"]
        self.assertEqual((b["≤1天"]["count"], b["≤1天"]["pnl"]), (0, D("0")))
        self.assertEqual((b["2–5天"]["count"], b["2–5天"]["pnl"]), (2, D("278.30")))
        self.assertEqual((b["6–20天"]["count"], b["6–20天"]["pnl"]), (2, D("-20.10")))
        self.assertEqual((b[">20天"]["count"], b[">20天"]["pnl"]), (0, D("0")))

    def test_code_attribution(self):
        # 600000: 1 笔 +188.80；000001: 2 笔 -109.50+89.50 = -20.00；600519: 1 笔 +89.40
        # 按绝对值排序：600000(188.80) > 600519(89.40) > 000001(20.00)
        rows = code_attribution(self.m)
        self.assertEqual([c for c, _ in rows], ["600000", "600519", "000001"])
        self.assertEqual(rows[2][1]["pnl"], D("-20.00"))
        self.assertEqual(rows[2][1]["count"], 2)

    def test_best_and_worst_three(self):
        # 口径（Issue #4 修正后）：先按净盈亏符号过滤，再各取前 3 笔；不足 3 笔就有几笔列几笔。
        # 最赚（仅 net_pnl > 0）：188.80 > 89.50 > 89.40
        # 最亏（仅 net_pnl < 0）：只有 B 一笔 -109.50，不再拿盈利笔填坑
        self.assertEqual([t.net_pnl for t in self.m["best"]], [D("188.80"), D("89.50"), D("89.40")])
        self.assertEqual([t.net_pnl for t in self.m["worst"]], [D("-109.50")])

    def test_gross_profit_is_net_win_sum(self):
        # 毛盈利改名 net_win_sum，口径 = 盈利笔净盈亏之和（367.70），不是毛额（400.00）
        self.assertEqual(self.m["net_win_sum"], D("367.70"))
        self.assertEqual(self.m["net_win_gross_sum"], D("400.00"))
        self.assertEqual(self.m["gross_profit"], self.m["net_win_sum"])

    def test_concentration(self):
        # 总买入 = 1000*4 = 4000；单标的买入：600000 1000，000001 2000，600519 1000
        # 最大 000001 = 2000/4000 = 50%
        conc = concentration(self.loaded.rows)
        self.assertEqual(conc["top_code"], "000001")
        self.assertEqual(conc["top_share"], D("0.5"))


if __name__ == "__main__":
    unittest.main()
