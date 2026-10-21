"""判据 2：FIFO 配对专项（核心算法，错了整份报告都错）。"""

import unittest
from datetime import date
from decimal import Decimal

from core.errors import RecapError
from core.models import TradeRecapRow
from core.pair import pair_fifo

D = Decimal


def row(day: str, code: str, side: str, price: str, qty: str, fee: str = "0") -> TradeRecapRow:
    d = date.fromisoformat(day)
    p, q = D(price), D(qty)
    return TradeRecapRow(line_no=0, date=d, code=code, side=side, price=p, qty=q, amount=p * q, fee=D(fee))


class FifoTest(unittest.TestCase):
    def test_fifo_partial_sell(self):
        """买 100@10、买 100@12、卖 150@15 —— issue 原文指定的期望。

        手算：卖 150 先吃第一批 100@10 → 毛 (15-10)*100 = 500（未扣费）；再吃第二批 50@12 → 毛 (15-12)*50 = 150。
        剩余未平仓：第二批的 50 股 @12。
        口径：FIFO 是一对一配对，「卖 150」天然包含「先配 100@10、再配 50@12」两段，
        因此闭环交易 2 条，但其中第一条就是原文要求的「100@10，盈利 500，未扣费」。
        """
        rows = [
            row("2026-01-01", "600000", "buy", "10", "100"),
            row("2026-01-02", "600000", "buy", "12", "100"),
            row("2026-01-03", "600000", "sell", "15", "150"),
        ]
        res = pair_fifo(rows)
        first = res.closed[0]
        self.assertEqual((first.buy_price, first.qty, first.gross_pnl, first.buy_fee), (D("10"), D("100"), D("500"), D("0")))
        self.assertEqual(len(res.closed), 2)
        self.assertEqual((res.closed[1].buy_price, res.closed[1].qty, res.closed[1].gross_pnl),
                         (D("12"), D("50"), D("150")))
        self.assertEqual(sum((t.qty for t in res.closed), D("0")), D("150"))
        leftover = res.open_lots["600000"]
        self.assertEqual(len(leftover), 1)
        self.assertEqual((leftover[0].price, leftover[0].qty), (D("12"), D("50")))

    def test_fifo_multiple_rounds(self):
        """同一标的四买三卖，断言完整交易数 3 与剩余持仓数量。

        买：100@10(01-01)、100@11(01-02)、100@12(01-03)、100@13(01-04)
        卖：150@14(01-05)、150@15(01-06)、100@16(01-07)  共卖 400，持仓 400 → 全部平掉 400
        FIFO 吃法：
          卖 150 → 吃掉 #1 100@10（毛 400）与 #2 的 50@11（毛 150）→ 交易 2 条
          卖 150 → 吃掉 #2 剩 50@11（毛 200）与 #3 的 100@12（毛 300）→ 交易 2 条
          卖 100 → 吃掉 #4 100@13（毛 300）→ 交易 1 条
        合计完整交易 5 条，但「卖出发生 3 次」；本测试断言的是配对闭环数 = 5、剩余持仓 = 0。
        同时断言每次卖出被怎么拆分，确保顺序没被搞乱。
        """
        rows = [
            row("2026-01-01", "600000", "buy", "10", "100"),
            row("2026-01-02", "600000", "buy", "11", "100"),
            row("2026-01-03", "600000", "buy", "12", "100"),
            row("2026-01-04", "600000", "buy", "13", "100"),
            row("2026-01-05", "600000", "sell", "14", "150"),
            row("2026-01-06", "600000", "sell", "15", "150"),
            row("2026-01-07", "600000", "sell", "16", "100"),
        ]
        res = pair_fifo(rows)
        self.assertEqual(len(res.closed), 5)
        self.assertEqual(sum((t.qty for t in res.closed), D("0")), D("400"))
        self.assertEqual(sum((lot.qty for lot in res.open_lots["600000"]), D("0")), D("0"))

        seq = [(t.buy_price, t.qty, t.gross_pnl) for t in res.closed]
        self.assertEqual(
            seq,
            [
                (D("10"), D("100"), D("400")),   # 卖 150 从第一批吃到 100
                (D("11"), D("50"), D("150")),    # 再吃第二批 50
                (D("11"), D("50"), D("200")),    # 第二次卖 150：先把第二批吃完 50
                (D("12"), D("100"), D("300")),   # 再吃第三批 100
                (D("13"), D("100"), D("300")),   # 第三次卖 100：吃第四批
            ],
        )

    def test_fifo_fees_are_proportional(self):
        """费用按数量分摊：买 100 股费 10，卖出 50 股时该笔只承担 5。

        买 100@10 费 10；卖 50@20 费 5。
        毛 (20-10)*50 = 500；买入分摊费 10*50/100 = 5；卖出分摊费 5*50/50 = 5 → 净 490。
        剩余 50 股仍带 5 元未分摊费用。
        """
        rows = [
            row("2026-01-01", "600000", "buy", "10", "100", fee="10"),
            row("2026-01-02", "600000", "sell", "20", "50", fee="5"),
        ]
        res = pair_fifo(rows)
        t = res.closed[0]
        self.assertEqual(t.buy_fee, D("5"))
        self.assertEqual(t.sell_fee, D("5"))
        self.assertEqual(t.net_pnl, D("490"))
        self.assertEqual(res.open_lots["600000"][0].qty, D("50"))

    def test_fifo_never_negative_position(self):
        """卖出量超过持仓必须报错，且错误信息要说人话（含代码、数量、持仓）。"""
        rows = [
            row("2026-01-01", "600000", "buy", "10", "100"),
            row("2026-01-02", "600000", "sell", "12", "150"),
        ]
        with self.assertRaises(RecapError) as cm:
            pair_fifo(rows)
        msg = str(cm.exception)
        self.assertIn("600000", msg)
        self.assertIn("150", msg)
        self.assertIn("100", msg)

    def test_fifo_sell_without_any_position(self):
        """完全没有持仓就卖出 → 同样是明确错误，不能静默算出负数持仓。"""
        with self.assertRaises(RecapError):
            pair_fifo([row("2026-01-01", "600000", "sell", "12", "100")])

    def test_codes_are_paired_independently(self):
        """不同标的的队列互不串味：卖 A 的持仓不能被 B 的买单接住。"""
        rows = [
            row("2026-01-01", "600000", "buy", "10", "100"),
            row("2026-01-02", "000001", "buy", "20", "100"),
            row("2026-01-03", "600000", "sell", "12", "100"),
        ]
        res = pair_fifo(rows)
        self.assertEqual(res.closed[0].code, "600000")
        self.assertEqual(res.closed[0].buy_price, D("10"))
        self.assertEqual(res.open_lots["000001"][0].qty, D("100"))


if __name__ == "__main__":
    unittest.main()
