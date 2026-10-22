"""行为诊断：只用交割单能证明的东西，每条都写清判定式与阈值。

未命中的项也会输出实际数值，方便看到「我这项是好的」。
"""

from decimal import Decimal

# 阈值（判定式里出现的数字，一律放这里，报告里直接引用，避免两处口径不一致）
HOLD_RATIO_THRESHOLD = Decimal("0.7")      # 处置效应：盈利单持仓 / 亏损单持仓 < 0.7
TRADES_PER_MONTH_THRESHOLD = Decimal("15")  # 频繁交易：月均完整交易数 > 15
CONCENTRATION_THRESHOLD = Decimal("0.4")    # 集中度：单标的买入占比 > 40%
COST_RATIO_THRESHOLD = Decimal("0.2")       # 成本侵蚀：费用 / 毛盈利 > 20%
WIN_RATE_HIGH = Decimal("0.55")             # 盈亏比失衡：胜率 > 55% 且 盈亏比 < 1.0
WIN_RATE_LOW = Decimal("0.45")              # 盈亏比失衡：胜率 < 45% 且 盈亏比 > 2.0
PL_RATIO_LOW = Decimal("1.0")
PL_RATIO_HIGH = Decimal("2.0")


def diagnose(m: dict, conc: dict) -> list:
    """返回诊断项列表，每项含：key、title、formula、value、threshold、hit、verdict。"""
    items = []

    # 处置效应
    win_hold = m["avg_hold_days_win"]
    loss_hold = m["avg_hold_days_loss"]
    hold_ratio = (win_hold / loss_hold) if (win_hold is not None and loss_hold) else None
    items.append(
        {
            "key": "disposition",
            "title": "处置效应",
            "formula": "盈利单平均持仓天数 < 亏损单平均持仓天数 × 0.7",
            "value": f"{hold_ratio:.2f}" if hold_ratio is not None else "数据不足",
            "detail": (
                f"盈利单 {win_hold:.1f} 天 / 亏损单 {loss_hold:.1f} 天"
                if hold_ratio is not None
                else "缺少盈利单或亏损单，无法比较"
            ),
            "threshold": "< 0.7",
            "hit": hold_ratio is not None and hold_ratio < HOLD_RATIO_THRESHOLD,
            "verdict": "赚了就跑，亏了死扛",
        }
    )

    # 频繁交易
    tpm = m["trades_per_month"]
    items.append(
        {
            "key": "overtrading",
            "title": "频繁交易",
            "formula": "月均完整交易数 > 15",
            "value": f"{tpm:.1f}" if tpm is not None else "0",
            "detail": f"共 {m['trade_count']} 笔完整交易",
            "threshold": "> 15 笔/月",
            "hit": tpm is not None and tpm > TRADES_PER_MONTH_THRESHOLD,
            "verdict": "交易频率偏高，成本与失误概率同步放大",
        }
    )

    # 集中度
    share = conc.get("top_share")
    items.append(
        {
            "key": "concentration",
            "title": "集中度过高",
            "formula": "单标的累计买入金额 / 总买入金额 > 40%",
            "value": f"{share * 100:.1f}%" if share is not None else "数据不足",
            "detail": f"最大标的 {conc.get('top_code') or '—'}",
            "threshold": "> 40%",
            "hit": share is not None and share > CONCENTRATION_THRESHOLD,
            "verdict": "单一标的风险敞口过大",
        }
    )

    # 盈亏比与胜率失衡
    wr = m["win_rate"]
    plr = m["profit_loss_ratio"]
    plot_hit = wr is not None and plr is not None and wr > WIN_RATE_HIGH and plr < PL_RATIO_LOW
    lowhit = wr is not None and plr is not None and wr < WIN_RATE_LOW and plr > PL_RATIO_HIGH
    verdict = "—"
    if plot_hit:
        verdict = "小赚大亏型"
    elif lowhit:
        verdict = "低胜率高赔率型"
    items.append(
        {
            "key": "win_loss_balance",
            "title": "盈亏比与胜率失衡",
            "formula": "胜率 > 55% 且 盈亏比 < 1.0 → 小赚大亏型；胜率 < 45% 且 盈亏比 > 2.0 → 低胜率高赔率型",
            "value": (
                f"胜率 {wr * 100:.1f}% / 盈亏比 {plr:.2f}"
                if wr is not None and plr is not None
                else (f"胜率 {wr * 100:.1f}% / 盈亏比 无法计算" if wr is not None else "数据不足")
            ),
            "detail": "盈利笔数多不等于赚钱，看平均每笔的大小",
            "threshold": "见判定式",
            "hit": plot_hit or lowhit,
            "verdict": verdict,
        }
    )

    # 成本侵蚀
    cr = m["cost_ratio"]
    items.append(
        {
            "key": "cost_erosion",
            "title": "成本侵蚀",
            "formula": "交易费用 / 毛盈利 net_win_sum > 20%",
            "value": f"{cr * 100:.1f}%" if cr is not None else "不适用",
            "detail": (
                f"费用合计 {m['total_fee']}，毛盈利 net_win_sum {m['net_win_sum']}"
                if cr is not None
                else "毛盈利不大于 0，比率无意义"
            ),
            "threshold": "> 20%",
            "hit": cr is not None and cr > COST_RATIO_THRESHOLD,
            "verdict": "手续费吃掉了太多利润",
        }
    )

    return items


def one_liner(m: dict, items: list, pnl_text: str = "") -> str:
    """一句话结论：先说事实（赚没赚、多少笔），再说命中了什么。

    pnl_text 由渲染层传入（已按 --mask 处理），这里不碰原始金额，避免打码泄漏。
    """
    hits = [i for i in items if i["hit"]]
    pnl = m["total_pnl"]
    tone = "赚了" if pnl > 0 else ("亏了" if pnl < 0 else "打平")
    amount = pnl_text or f"{abs(pnl)} 元"
    base = f"这一年完成 {m['trade_count']} 笔完整交易，净{tone} {amount}"
    if m["trade_count"] and m["win_rate"] is not None:
        base += f"，胜率 {m['win_rate'] * 100:.0f}%"
    if hits:
        return base + "；问题出在：" + "、".join(i["title"] for i in hits) + "。"
    return base + "；这份记录里没有命中任何已知的坏习惯。"
