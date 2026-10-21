"""数据模型：交割单行、完整交易（配对结果）。

金额一律 Decimal，进入系统的第一刻就转换，绝不出现 float。
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class TradeRecapRow:
    """交割单的一行。amount 为成交金额（价格 × 数量），不含费用。"""

    line_no: int
    date: date
    code: str
    side: str  # 规范化后只有 "buy" / "sell"
    price: Decimal
    qty: Decimal
    amount: Decimal
    fee: Decimal

    @property
    def is_buy(self) -> bool:
        return self.side == "buy"


@dataclass
class OpenLot:
    """未平仓的买入批次（FIFO 队列元素）。"""

    date: date
    price: Decimal
    qty: Decimal
    fee: Decimal
    line_no: int

    @property
    def fee_per_share(self) -> Decimal:
        return self.fee / self.qty if self.qty else Decimal("0")


@dataclass
class ClosedTrade:
    """一笔完整交易：某个买入批次的一部分 被 某个卖出批次的一部分 平掉。

    一笔卖出可能拆成多条 ClosedTrade；多条 ClosedTrade 合起来才是「这次卖出」。
    """

    code: str
    buy_date: date
    buy_price: Decimal
    sell_date: date
    sell_price: Decimal
    qty: Decimal
    buy_fee: Decimal
    sell_fee: Decimal

    @property
    def hold_days(self) -> int:
        """自然日持仓天数：卖出日 - 买入日。"""
        return (self.sell_date - self.buy_date).days

    @property
    def gross_pnl(self) -> Decimal:
        """毛盈亏 = (卖价 - 买价) × 数量，未扣费。"""
        return (self.sell_price - self.buy_price) * self.qty

    @property
    def net_pnl(self) -> Decimal:
        """净盈亏 = 毛盈亏 - 买入分摊费用 - 卖出分摊费用。"""
        return self.gross_pnl - self.buy_fee - self.sell_fee

    @property
    def cost(self) -> Decimal:
        """这一笔的买入成本（用于计算收益率）。"""
        return self.buy_price * self.qty


@dataclass
class PairResult:
    """配对结果：闭环交易 + 剩余未平仓批次。"""

    closed: list[ClosedTrade] = field(default_factory=list)
    open_lots: dict[str, list[OpenLot]] = field(default_factory=dict)
    # 仅在 allow_short=True 时非空：卖出量超出持仓的部分（不参与任何盈亏计算）
    shorts: dict[str, Decimal] = field(default_factory=dict)
