"""指标计算。每个指标的口径都写在函数 docstring 里，调用方不许重定义。

金额一律 Decimal；所有比率用 Decimal 计算，导出时再格式化。
口径约定：
- 「完整交易」= FIFO 配对形成的一条 ClosedTrade。
- 胜率 = 盈利的完整交易数 / 完整交易数；盈亏按净盈亏（已扣买卖两端分摊费用）判定。
- 盈亏比 = 平均盈利额 / |平均亏损额|，两者都按净盈亏算。
- 平均持仓天数 = 配对后 (卖出日 - 买入日) 的算术平均，自然日，按笔（不是按数量）平均。
- 毛盈亏 = Σ 净盈亏（全量合计，含亏损笔）。
- 「最赚的三笔」= net_pnl > 0 的交易按净盈亏降序取前 3；一笔都不赚时为空。
- 「最亏的三笔」= net_pnl < 0 的交易按净盈亏升序取前 3；一笔都不亏时为空。
  两个榜单都按符号过滤，绝不拿盈利笔去填「最亏」，反之亦然。
- net_win_sum（旧名 gross_profit，保留为同义键）= 仅盈利笔的净盈亏之和，不是毛盈亏之和；
  仅用于成本占比与成本侵蚀。名字里没有 gross，别再读错。
"""

from collections import defaultdict
from decimal import Decimal

from core.models import ClosedTrade

ZERO = Decimal("0")
BUCKETS = (
    ("≤1天", 0, 1),
    ("2–5天", 2, 5),
    ("6–20天", 6, 20),
    (">20天", 21, None),
)


def _avg(values):
    values = list(values)
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def hold_bucket(days: int) -> str:
    """按持仓天数分桶，边界：0–1 / 2–5 / 6–20 / >20。"""
    for name, lo, hi in BUCKETS:
        if days >= lo and (hi is None or days <= hi):
            return name
    return BUCKETS[-1][0]


def compute_metrics(closed, total_buy_amount: Decimal, total_fee: Decimal, months: int):
    wins = [t for t in closed if t.net_pnl > 0]
    losses = [t for t in closed if t.net_pnl < 0]
    count = len(closed)

    avg_win = _avg([t.net_pnl for t in wins])
    avg_loss = _avg([t.net_pnl for t in losses])
    win_rate = Decimal(len(wins)) / Decimal(count) if count else None
    profit_loss_ratio = None
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        profit_loss_ratio = avg_win / abs(avg_loss)

    # net_win_sum：盈利笔「净盈亏」之和（已扣两端费用），口径同胜率，不是毛盈亏。
    net_win_sum = sum((t.net_pnl for t in wins), ZERO)
    net_win_gross_sum = sum((t.gross_pnl for t in wins), ZERO)
    total_pnl = sum((t.net_pnl for t in closed), ZERO)

    # 交易成本占比 = 手续费+印花税合计 / net_win_sum；net_win_sum ≤ 0 时为 None（报告显示「不适用」）
    cost_ratio = (total_fee / net_win_sum) if net_win_sum > 0 else None

    by_code = defaultdict(lambda: {"pnl": ZERO, "count": 0, "buy_amount": ZERO})
    by_month = defaultdict(lambda: {"pnl": ZERO, "count": 0})
    by_bucket = {name: {"pnl": ZERO, "count": 0} for name, _, _ in BUCKETS}
    for t in closed:
        item = by_code[t.code]
        item["pnl"] += t.net_pnl
        item["count"] += 1
        by_month[t.sell_date.strftime("%Y-%m")]["pnl"] += t.net_pnl
        by_month[t.sell_date.strftime("%Y-%m")]["count"] += 1
        bucket = by_bucket[hold_bucket(t.hold_days)]
        bucket["pnl"] += t.net_pnl
        bucket["count"] += 1

    return {
        "trade_count": count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": count - len(wins) - len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "avg_hold_days": _avg([Decimal(t.hold_days) for t in closed]),
        "avg_hold_days_win": _avg([Decimal(t.hold_days) for t in wins]),
        "avg_hold_days_loss": _avg([Decimal(t.hold_days) for t in losses]),
        "total_pnl": total_pnl,
        "net_win_sum": net_win_sum,
        # 旧键名保留（值为同一口径的净额），避免外部脚本炸掉；新代码请用 net_win_sum
        "gross_profit": net_win_sum,
        "net_win_gross_sum": net_win_gross_sum,
        "total_fee": total_fee,
        "cost_ratio": cost_ratio,
        "trades_per_month": Decimal(count) / Decimal(months) if months else None,
        "total_buy_amount": total_buy_amount,
        "by_code": by_code,
        "by_month": by_month,
        "by_bucket": by_bucket,
        # 最赚 / 最亏：先按净盈亏符号过滤，再各取前 3；不足 3 笔就有几笔列几笔
        "best": sorted(wins, key=lambda t: t.net_pnl, reverse=True)[:3],
        "worst": sorted(losses, key=lambda t: t.net_pnl)[:3],
    }


def concentration(rows) -> dict:
    """集中度：单标的累计买入金额 / 总买入金额，取最大者。"""
    buy_by_code = defaultdict(lambda: ZERO)
    total = ZERO
    for row in rows:
        if row.is_buy:
            buy_by_code[row.code] += row.amount
            total += row.amount
    if total <= 0:
        return {"top_code": None, "top_share": None}
    code, amount = max(buy_by_code.items(), key=lambda kv: kv[1])
    return {"top_code": code, "top_share": amount / total}


def months_covered(rows) -> int:
    """覆盖的月份数：按首笔到末笔所在自然月计数，至少 1。用于月均交易数。"""
    if not rows:
        return 1
    first, last = rows[0].date, rows[-1].date
    return max(1, (last.year - first.year) * 12 + (last.month - first.month) + 1)


def sum_fees(rows) -> Decimal:
    return sum((r.fee for r in rows), ZERO)


def sum_buy_amount(rows) -> Decimal:
    return sum((r.amount for r in rows if r.is_buy), ZERO)


def code_attribution(m: dict, limit: int = 10):
    """按标的归因：按累计盈亏绝对值取前 N。"""
    items = sorted(m["by_code"].items(), key=lambda kv: abs(kv[1]["pnl"]), reverse=True)
    return items[:limit]


def format_trade(t: ClosedTrade) -> dict:
    """给报告用的一笔交易摘要。"""
    return {
        "code": t.code,
        "buy_date": t.buy_date.isoformat(),
        "sell_date": t.sell_date.isoformat(),
        "hold_days": t.hold_days,
        "qty": t.qty,
        "pnl": t.net_pnl,
        "gross_pnl": t.gross_pnl,
        "fees": t.buy_fee + t.sell_fee,
    }
