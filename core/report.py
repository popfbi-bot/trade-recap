"""报告渲染：终端摘要、report.md、report.html。

三条硬约束（改代码前先读）：
1. DISCLAIMER 原文照抄进 md 与 html，一个字都不许改。
2. 黑名单词（建议买/建议卖/目标价/推荐买入…）不得出现在产物里。
3. 打码只在这里生效，指标数值本身不动。
"""

import html
from decimal import Decimal

from core import VERSION
from core.diagnosis import one_liner
from core.masking import Masker

DISCLAIMER = (
    "本工具仅对用户本人的历史交易记录做统计与归因，不构成任何投资建议，不预测未来收益。"
    "所有结论仅反映过去已发生的交易事实。投资有风险，决策请自行判断。"
)

BANNED_WORDS = ("建议买", "建议卖", "目标价", "推荐买入", "推荐卖出", "建议持有", "看好", "预期收益")


def build_report(data: dict, mask: bool = False) -> dict:
    """data 是 cli 组装好的上下文字典；这里只负责渲染，不改数值。"""
    m = data["metrics"]
    unit = m["best"][0].net_pnl if m["best"] and m["best"][0].net_pnl > 0 else None
    mk = Masker(mask, unit)
    ctx = _context(data, mk, mask)
    ctx["one_liner"] = one_liner(m, data["diagnosis"], _pnl_phrase(m, mk))
    return {
        "summary": _summary(ctx),
        "markdown": _markdown(ctx),
        "html": _html(ctx),
        "one_liner": ctx["one_liner"],
    }


def _pnl_phrase(m, mk) -> str:
    """一句话结论里的盈亏描述。打码时不许出现真实金额，只给比例/方向。"""
    pnl = m["total_pnl"]
    if not mk.enabled:
        return f"{abs(pnl):.2f} 元"
    if pnl == 0:
        return "0 元"
    return f"（绝对金额已打码，占最大单笔盈利的 {mk.money(abs(pnl))}）"


def _pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{Decimal(value) * 100:.{digits}f}%"


def _ratio(value, digits: int = 2) -> str:
    return "—" if value is None else f"{Decimal(value):.{digits}f}"


def _context(data, mk: Masker, mask: bool) -> dict:
    m = data["metrics"]
    items = data["diagnosis"]
    return {
        "mk": mk,
        "mask": mask,
        "version": VERSION,
        "encoding": data["encoding"],
        "mapping": data["mapping"],
        "range": data["range"],
        "m": m,
        "items": items,
        "code_rows": data["code_rows"],
        "month_rows": data["month_rows"],
        "bucket_rows": data["bucket_rows"],
        "best": data["best"],
        "worst": data["worst"],
        "open_lots": data["open_lots"],
        "warnings": data.get("warnings", []),
    }


def _summary(ctx) -> str:
    """终端摘要，10 行以内。"""
    m, mk = ctx["m"], ctx["mk"]
    mark = "命中" if any(i["hit"] for i in ctx["items"]) else "未命中"
    hits = "、".join(i["title"] for i in ctx["items"] if i["hit"]) or "无"
    lines = [
        f"trade-recap v{ctx['version']} · {ctx['range']} · 映射 {ctx['mapping']} · 编码 {ctx['encoding']}",
        ctx["one_liner"],
        f"完整交易 {m['trade_count']} 笔 | 胜率 {_pct(m['win_rate'])} | 盈亏比 {_ratio(m['profit_loss_ratio'])}"
        f" | 平均持仓 {_ratio(m['avg_hold_days'], 1)} 天",
        f"净盈亏 {mk.total(m['total_pnl'])} | 费用 {mk.total(m['total_fee'])}"
        f" | 成本占比 {_pct(m['cost_ratio'])}",
        f"行为诊断（{mark}）：{hits}",
        f"未平仓批次 {len(ctx['open_lots'])} 个（不计入以上指标）",
        "完整报告：report.md / report.html",
    ]
    return "\n".join(lines)


def _multi(items) -> str:
    return "、".join(items) if items else "无"


BEST_EMPTY = "本期没有盈利交易"
WORST_EMPTY = "本期没有亏损交易"


def _rank_section(L, title, rows, mk: Masker, empty_text: str) -> None:
    """最赚 / 最亏榜单。榜单已按净盈亏符号过滤，空就是真的没有，不留空表。"""
    L.append(f"## {title}")
    L.append("")
    if not rows:
        L.append(empty_text)
        L.append("")
        return
    L.append("| 代码 | 买卖日期 | 持有天数 | 数量 | 净盈亏 | 毛盈亏 |")
    L.append("|---|---|---|---|---|---|")
    L.extend(_trade_lines(rows, mk))
    L.append("")


def _trade_lines(rows, mk: Masker) -> list:
    out = []
    for t in rows:
        out.append(
            f"| {mk.code(t['code'])} | {t['buy_date']} → {t['sell_date']} | {t['hold_days']} 天 "
            f"| {mk.qty(t['qty'])} | {mk.money(t['pnl'])} | {mk.money(t['gross_pnl'])} |"
        )
    return out


def _markdown(ctx) -> str:
    m, mk = ctx["m"], ctx["mk"]
    L = []
    L.append("# 交易复盘报告")
    L.append("")
    L.append(f"**一句话结论**：{ctx['one_liner']}")
    L.append("")
    L.append("## 核心数字")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append(f"| 完整交易数 | {m['trade_count']} 笔 |")
    L.append(f"| 胜率 | {_pct(m['win_rate'])}（{m['win_count']} 盈 / {m['loss_count']} 亏 / {m['flat_count']} 平） |")
    L.append(f"| 盈亏比 | {_ratio(m['profit_loss_ratio'])} |")
    L.append(f"| 净盈亏 | {mk.total(m['total_pnl'])} |")
    L.append(f"| 平均持仓天数 | {_ratio(m['avg_hold_days'], 1)} 天 |")
    L.append("")
    L.append("## 明细指标")
    L.append("")
    L.append("| 指标 | 定义 | 数值 |")
    L.append("|---|---|---|")
    L.append(f"| 平均盈利额 | 盈利笔净盈亏的算术平均 | {mk.money(m['avg_win'])} |")
    L.append(f"| 平均亏损额 | 亏损笔净盈亏的算术平均 | {mk.money(m['avg_loss'])} |")
    L.append(f"| 毛盈利 `net_win_sum` | 所有**盈利笔**的**净盈亏**之和（已扣两端费用，不含亏损笔；"
             f"仅盈利笔毛盈亏之和为 {mk.total(m['net_win_gross_sum'])}） | {mk.total(m['net_win_sum'])} |")
    L.append(f"| 交易费用合计 | 手续费 + 印花税合计 | {mk.total(m['total_fee'])} |")
    cost_ratio = "不适用" if m["cost_ratio"] is None else _pct(m["cost_ratio"])
    L.append(f"| 交易成本占比 | 交易费用合计 / 毛盈利 `net_win_sum`（分母是净额而非毛额，毛盈利 ≤ 0 时不算比率）"
             f" | {cost_ratio} |")
    L.append(f"| 月均完整交易数 | 完整交易数 / 覆盖月份数 | {_ratio(m['trades_per_month'], 1)} 笔/月 |")
    L.append("")
    _rank_section(L, "最赚的三笔（净盈亏 > 0）", ctx["best"], mk, BEST_EMPTY)
    _rank_section(L, "最亏的三笔（净盈亏 < 0）", ctx["worst"], mk, WORST_EMPTY)
    L.append("## 归因 · 按标的（盈亏绝对值前 10）")
    L.append("")
    L.append("| 代码 | 完整交易笔数 | 净盈亏 |")
    L.append("|---|---|---|")
    for code, item in ctx["code_rows"]:
        L.append(f"| {mk.code(code)} | {item['count']} | {mk.money(item['pnl'])} |")
    L.append("")
    L.append("## 归因 · 按月份（按卖出日归属）")
    L.append("")
    L.append("| 月份 | 笔数 | 净盈亏 |")
    L.append("|---|---|---|")
    for month in sorted(ctx["month_rows"]):
        item = ctx["month_rows"][month]
        L.append(f"| {month} | {item['count']} | {mk.money(item['pnl'])} |")
    L.append("")
    L.append("## 归因 · 按持有天数")
    L.append("")
    L.append("| 持仓区间 | 笔数 | 净盈亏 |")
    L.append("|---|---|---|")
    for name, item in ctx["bucket_rows"].items():
        L.append(f"| {name} | {item['count']} | {mk.money(item['pnl'])} |")
    L.append("")
    L.append("## 行为诊断")
    L.append("")
    L.append("| 诊断项 | 判定式 | 你的数值 | 判定阈值 | 结果 |")
    L.append("|---|---|---|---|---|")
    for i in ctx["items"]:
        result = f"命中：{i['verdict']}" if i["hit"] else "未命中"
        L.append(f"| {i['title']} | {i['formula']} | {i['value']} | {i['threshold']} | {result} |")
    L.append("")
    L.append("## 数据说明")
    L.append("")
    L.append(f"- 数据来源：本地交割单文件（只读，未修改）")
    L.append(f"- 区间：{ctx['range']}")
    L.append(f"- 列映射：{ctx['mapping']}")
    L.append(f"- 文件编码：{ctx['encoding']}（自动探测 utf-8-sig → gbk）")
    L.append(f"- 配对算法：FIFO，按标的先进先出配对；剩余未平仓批次 {len(ctx['open_lots'])} 个，不计入任何指标")
    for w in ctx["warnings"]:
        L.append(f"- 注意：{w}")
    L.append("")
    L.append("## 免责声明")
    L.append("")
    L.append(f"> {DISCLAIMER}")
    L.append("")
    return "\n".join(L)


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:32px;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
background:#0f1115;color:#e8eaed;line-height:1.6}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px;font-weight:600}
.meta{color:#8b93a1;font-size:13px;margin-bottom:24px}
.verdict{font-size:19px;font-weight:600;background:#1a1f2b;border-left:4px solid #4c8dff;
padding:16px 18px;border-radius:8px;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}
.card{background:#181d27;border:1px solid #232a37;border-radius:12px;padding:16px}
.card .k{color:#8b93a1;font-size:12px;letter-spacing:.04em}
.card .v{font-size:30px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
.card .u{font-size:13px;color:#8b93a1;margin-left:3px;font-weight:400}
h2{font-size:16px;margin:28px 0 10px;color:#cfd5e1}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #232a37}
th{color:#8b93a1;font-weight:500}
td.num{font-variant-numeric:tabular-nums}
/* 配色语义（issue #10）：盈利红、亏损绿——与 life-kline 的「阳红阴绿」统一，
   也符合 A 股「红涨绿跌」的直觉。
   .hit 命中诊断 = 橙（这条要改）  .ok 未命中 = 灰蓝（无事发生）
   别把 .ok 改回绿色：绿色已经表示「亏损」，一个颜色只能有一个意思。 */
.hit{color:#ff8a5c;font-weight:600}
.ok{color:#8b93a1}
.pos{color:#ff6b6b}
.neg{color:#5fd08a}
.footer{margin-top:32px;padding-top:16px;border-top:1px solid #232a37;color:#7b8391;font-size:12.5px}
@media(max-width:640px){.cards{grid-template-columns:repeat(2,1fr)}body{padding:18px}}
"""


def _html(ctx) -> str:
    m, mk = ctx["m"], ctx["mk"]
    e = html.escape

    def num_cls(value):
        if value is None:
            return ""
        return "pos" if value > 0 else ("neg" if value < 0 else "")

    cards = [
        ("完整交易", f"{m['trade_count']}", "笔"),
        ("胜率", _pct(m["win_rate"], 0), ""),
        ("盈亏比", _ratio(m["profit_loss_ratio"]), ""),
        ("净盈亏", mk.total(m["total_pnl"]), ""),
    ]
    card_html = "".join(
        f'<div class="card"><div class="k">{e(k)}</div><div class="v">{e(v)}<span class="u">{e(u)}</span></div></div>'
        for k, v, u in cards
    )

    diag_rows = "".join(
        "<tr>"
        f"<td>{e(i['title'])}</td>"
        f"<td>{e(i['formula'])}</td>"
        f"<td class='num'>{e(i['value'])}</td>"
        f"<td>{e(i['threshold'])}</td>"
        f"<td class=\"{'hit' if i['hit'] else 'ok'}\">{e('命中 · ' + i['verdict'] if i['hit'] else '未命中')}</td>"
        "</tr>"
        for i in ctx["items"]
    )

    def rank_table(rows, empty_text):
        """榜单空时不留空表，直接说明「本期没有」。"""
        if not rows:
            return f'<p class="meta">{e(empty_text)}</p>'
        return (
            "<table><tr><th>代码</th><th>买卖日期</th><th>持有天数</th><th>数量</th><th>净盈亏</th></tr>"
            f"{trade_rows(rows)}</table>"
        )

    def trade_rows(rows):
        return "".join(
            "<tr>"
            f"<td>{e(mk.code(t['code']))}</td>"
            f"<td>{e(t['buy_date'])} → {e(t['sell_date'])}</td>"
            f"<td class='num'>{t['hold_days']}</td>"
            f"<td class='num'>{e(mk.qty(t['qty']))}</td>"
            f"<td class='num {num_cls(t['pnl'])}'>{e(mk.money(t['pnl']))}</td>"
            "</tr>"
            for t in rows
        )

    code_rows = "".join(
        f"<tr><td>{e(mk.code(code))}</td><td class='num'>{item['count']}</td>"
        f"<td class='num {num_cls(item['pnl'])}'>{e(mk.money(item['pnl']))}</td></tr>"
        for code, item in ctx["code_rows"]
    )
    month_rows = "".join(
        f"<tr><td>{e(month)}</td><td class='num'>{ctx['month_rows'][month]['count']}</td>"
        f"<td class='num {num_cls(ctx['month_rows'][month]['pnl'])}'>"
        f"{e(mk.money(ctx['month_rows'][month]['pnl']))}</td></tr>"
        for month in sorted(ctx["month_rows"])
    )
    bucket_rows = "".join(
        f"<tr><td>{e(name)}</td><td class='num'>{item['count']}</td>"
        f"<td class='num {num_cls(item['pnl'])}'>{e(mk.money(item['pnl']))}</td></tr>"
        for name, item in ctx["bucket_rows"].items()
    )
    warnings = "".join(f"<li>{e(w)}</li>" for w in ctx["warnings"])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>交易复盘报告 · trade-recap v{e(ctx['version'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>交易复盘报告</h1>
<div class="meta">{e(ctx['range'])} · 映射 {e(ctx['mapping'])} · 编码 {e(ctx['encoding'])} · trade-recap v{e(ctx['version'])}</div>
<div class="verdict">{e(ctx['one_liner'])}</div>
<div class="cards">{card_html}</div>

<h2>最赚的 3 笔（净盈亏 &gt; 0）</h2>
{rank_table(ctx['best'], BEST_EMPTY)}

<h2>最亏的 3 笔（净盈亏 &lt; 0）</h2>
{rank_table(ctx['worst'], WORST_EMPTY)}

<h2>归因 · 按标的（前 10）</h2>
<table><tr><th>代码</th><th>笔数</th><th>净盈亏</th></tr>{code_rows}</table>

<h2>归因 · 按月份</h2>
<table><tr><th>月份</th><th>笔数</th><th>净盈亏</th></tr>{month_rows}</table>

<h2>归因 · 按持有天数</h2>
<table><tr><th>持仓区间</th><th>笔数</th><th>净盈亏</th></tr>{bucket_rows}</table>

<h2>行为诊断</h2>
<table><tr><th>诊断项</th><th>判定式</th><th>你的数值</th><th>阈值</th><th>结果</th></tr>{diag_rows}</table>

<h2>数据说明</h2>
<table>
<tr><th>区间</th><td>{e(ctx['range'])}</td></tr>
<tr><th>列映射</th><td>{e(ctx['mapping'])}</td></tr>
<tr><th>文件编码</th><td>{e(ctx['encoding'])}（自动探测 utf-8-sig → gbk）</td></tr>
<tr><th>配对算法</th><td>FIFO；剩余未平仓批次 {len(ctx['open_lots'])} 个，不计入任何指标</td></tr>
<tr><th>平均持仓天数</th><td class="num">{_ratio(m['avg_hold_days'], 1)} 天</td></tr>
<tr><th>交易费用合计</th><td class="num">{e(mk.total(m['total_fee']))}</td></tr>
<tr><th>毛盈利 net_win_sum</th><td class="num">{e(mk.total(m['net_win_sum']))}</td></tr>
<tr><th>交易成本占比</th><td class="num">{'不适用' if m['cost_ratio'] is None else _pct(m['cost_ratio'])}（费用合计 / 毛盈利，分母为盈利笔净额）</td></tr>
</table>
{f'<ul>{warnings}</ul>' if warnings else ''}

<div class="footer">{e(DISCLAIMER)}</div>
</div>
</body>
</html>
"""
