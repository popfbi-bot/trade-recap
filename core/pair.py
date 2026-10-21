"""FIFO 配对：把买卖流水配对成「一笔完整交易」。

口径（写死，别自己发挥）：
- 买入进入该标的的 FIFO 队列，卖出从队首开始依次吃掉买入批次。
- 一次卖出可能吃掉多个买入批次 → 产出多条 ClosedTrade；一次买入也可能被多次卖出拆开。
- 卖出量 > 当前持仓 → 默认报错（RecapError），绝不出现负持仓。
  唯一例外是显式传入 allow_short=True（部分券商的「卖券还款 / 融券」场景），
  超出部分不参与配对，作为该标的的未平仓「卖空批次」返回，报告里单独提示。
- 费用按数量分摊：每条配对承担 fee × 该条数量 / 该行数量，合计不重不漏。
- 配对不设时间窗口，跨年也按 FIFO 全量配对（v0.1 已知边界）。
"""

from collections import defaultdict
from decimal import Decimal

from core.errors import RecapError
from core.models import ClosedTrade, OpenLot, PairResult


def pair_fifo(rows, allow_short: bool = False) -> PairResult:
    """输入已按 (date, line_no) 排序的行，输出闭环交易与剩余持仓。"""
    result = PairResult()
    queues = defaultdict(list)  # code -> [OpenLot]（未平仓买入批次）
    shorts = defaultdict(Decimal)  # code -> 未被买入覆盖的卖出量
    result.open_lots = queues

    for row in rows:
        if row.qty <= 0:
            raise RecapError(f"第 {row.line_no} 行数量必须为正数，实际是 {row.qty}")

        if row.is_buy:
            queues[row.code].append(
                OpenLot(date=row.date, price=row.price, qty=row.qty, fee=row.fee, line_no=row.line_no)
            )
            continue

        queue = queues[row.code]
        held = sum((lot.qty for lot in queue), Decimal("0"))
        if row.qty > held:
            if not allow_short:
                raise RecapError(
                    f"第 {row.line_no} 行卖出 {row.code} {row.qty} 股，但当时只有 {held} 股持仓。"
                    "交割单可能不完整（例如只导出了部分区间），或存在未被记录的数量变动（送股、配股、融券）。"
                    "请补充完整的买入记录后重试。"
                )
            # 允许卖空：超出部分只记欠量，不产生任何盈亏
            shorts[row.code] += row.qty - held
            matched_total = held
        else:
            matched_total = row.qty

        remaining = matched_total
        while remaining > 0:
            lot = queue[0]
            matched = min(lot.qty, remaining)
            result.closed.append(
                ClosedTrade(
                    code=row.code,
                    buy_date=lot.date,
                    buy_price=lot.price,
                    sell_date=row.date,
                    sell_price=row.price,
                    qty=matched,
                    buy_fee=lot.fee_per_share * matched,
                    sell_fee=row.fee * matched / row.qty,
                )
            )
            lot.qty -= matched
            remaining -= matched
            if lot.qty == 0:
                queue.pop(0)

    result.closed.sort(key=lambda t: (t.sell_date, t.code))
    result.shorts = dict(shorts)
    return result
