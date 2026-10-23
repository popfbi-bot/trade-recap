#!/usr/bin/env python3
"""trade-recap 命令行入口。纯本地、零第三方依赖、零网络。

    python cli.py recap 交割单.csv --mapping generic-cn --year 2026
    python cli.py recap 交割单.csv --mapping huatai --from 2026-01-01 --to 2026-06-30 --out report.md
    python cli.py columns 交割单.csv
    python cli.py mappings
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import VERSION  # noqa: E402
from core.diagnosis import diagnose  # noqa: E402
from core.errors import RecapError  # noqa: E402
from core.loader import REQUIRED_FIELDS, list_mappings, load_csv, load_mapping, read_header  # noqa: E402
from core.metrics import (  # noqa: E402
    code_attribution,
    compute_metrics,
    concentration,
    format_trade,
    months_covered,
    sum_buy_amount,
    sum_fees,
)
from core.pair import pair_fifo  # noqa: E402
from core.report import build_report  # noqa: E402


def _parse_date(text: str):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RecapError(f"日期格式看不懂：{text}，请用 YYYY-MM-DD")


def _filter(rows, from_date, to_date):
    return [r for r in rows if (from_date is None or r.date >= from_date) and (to_date is None or r.date <= to_date)]


def _range_text(from_date, to_date, year):
    if year:
        return f"{year} 年度"
    left = from_date.isoformat() if from_date else "最早"
    right = to_date.isoformat() if to_date else "最新"
    return f"{left} → {right}"


def cmd_recap(args) -> int:
    mapping = load_mapping(args.mapping)
    loaded = load_csv(args.csv, mapping, args.mapping)

    from_date, to_date = None, None
    if args.year:
        from_date, to_date = date(args.year, 1, 1), date(args.year, 12, 31)
    if args.date_from:
        from_date = _parse_date(args.date_from)
    if args.date_to:
        to_date = _parse_date(args.date_to)
    if from_date and to_date and from_date > to_date:
        raise RecapError(f"--from {from_date} 晚于 --to {to_date}，区间为空")

    rows = _filter(loaded.rows, from_date, to_date)
    if not rows:
        raise RecapError("该区间内没有任何成交记录，检查一下 --year / --from / --to 是否写错了")

    warnings = []
    if from_date or to_date:
        warnings.append("统计区间内的卖出若对应区间外的买入，FIFO 配对会报「无持仓」错误；请确保区间覆盖完整持仓周期")

    result = pair_fifo(rows)
    closed = result.closed
    if not closed:
        raise RecapError("区间内没有任何买卖闭环（只有买入没有卖出），无法形成完整交易，指标无意义")

    m = compute_metrics(closed, sum_buy_amount(rows), sum_fees(rows), months_covered(rows))
    conc = concentration(rows)
    items = diagnose(m, conc)

    open_lots = [{"code": code, "lots": len(q)} for code, q in result.open_lots.items() if q]
    data = {
        "metrics": m,
        "diagnosis": items,
        "code_rows": code_attribution(m),
        "month_rows": m["by_month"],
        "bucket_rows": m["by_bucket"],
        "best": [format_trade(t) for t in m["best"]],
        "worst": [format_trade(t) for t in m["worst"]],
        "open_lots": open_lots,
        "encoding": loaded.encoding,
        "mapping": loaded.mapping_name,
        "range": _range_text(from_date, to_date, args.year),
        "warnings": warnings,
    }

    rendered = build_report(data, mask=args.mask)
    print(rendered["summary"])

    out = args.out
    if out:
        ext = os.path.splitext(out)[1].lower()
        if ext == ".html":
            _write(out, rendered["html"])
            _write(os.path.join(os.path.dirname(out) or ".", "report.md"), rendered["markdown"])
        elif ext == ".md":
            _write(out, rendered["markdown"])
            _write(os.path.join(os.path.dirname(out) or ".", "report.html"), rendered["html"])
        else:
            raise RecapError(f"--out 只支持 .md 或 .html，收到：{out}")
    else:
        _write("report.md", rendered["markdown"])
        _write("report.html", rendered["html"])
    return 0


def _write(path: str, content: str) -> None:
    try:
        # newline=""：不把 \n 转成 \r\n。Windows 上默认的文本模式会把整个文件
        # 翻成 CRLF，生成的产物跟仓库里的版本行尾不一致，diff 会变成整文件变化。
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
    except FileNotFoundError:
        # 典型场景：--out 指向了一个还不存在的目录。
        # 裸 FileNotFoundError 的 traceback 对用户没有意义，给一句能照做的话。
        parent = os.path.dirname(os.path.abspath(path))
        raise RecapError(
            f"输出路径的目录不存在：{parent}\n"
            f"  先创建这个目录，或把 --out 换到一个已存在的目录。"
        ) from None
    except OSError as exc:
        raise RecapError(f"写文件失败：{path}（{exc.strerror or exc}）") from None
    print(f"已写入 {path}")


def cmd_columns(args) -> int:
    header, encoding = read_header(args.csv)
    mapping = None
    if args.mapping:
        mapping = load_mapping(args.mapping)
    else:
        try:
            mapping = load_mapping("generic-cn")
        except RecapError:
            mapping = None

    print(f"文件：{args.csv}")
    print(f"编码：{encoding}（自动探测 utf-8-sig → gbk）")
    print(f"共 {len(header)} 列")
    print("")
    used = {}
    if mapping:
        used = {v: k for k, v in (mapping.get("columns") or {}).items() if v}
        print(f"参照映射：{mapping.get('name', '')}")
    print(f"{'列名':<24}映射到")
    print("-" * 40)
    for col in header:
        field = used.get(col)
        print(f"{col:<24}{field if field else '（未映射）'}")
    unmapped = [c for c in header if c not in used]
    if unmapped:
        print("")
        print("未映射的列：" + "、".join(unmapped))
        print("这些列会被忽略。若其中包含必需字段，请在 mappings/ 下的映射文件里配置 columns 字段：")
        print("  " + ", ".join(REQUIRED_FIELDS))
    missing = [f for f in REQUIRED_FIELDS if f not in (mapping.get("columns") or {} if mapping else {})]
    if mapping and missing:
        print("")
        print("映射里缺少必需字段：" + "、".join(missing))
    return 0


def cmd_mappings(args) -> int:
    items = list_mappings()
    if not items:
        print("mappings/ 下没有任何映射文件")
        return 0
    print(f"共 {len(items)} 个列映射（可加入 --mapping <名字> 使用）：")
    print("")
    for name, data, filename in items:
        desc = data.get("description") or ""
        print(f"- {name:<14}{desc}")
        print(f"  文件：mappings/{filename}")
        print(f"  列：{json.dumps(data.get('columns', {}), ensure_ascii=False)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-recap", description="交割单年度复盘：FIFO 配对 + 行为诊断，纯本地运行")
    p.add_argument("--version", action="version", version=f"trade-recap {VERSION}")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("recap", help="生成复盘报告")
    r.add_argument("csv", help="交割单 CSV 路径（只读，不会修改）")
    r.add_argument("--mapping", default="generic-cn", help="列映射名或 json 路径（默认 generic-cn，见 mappings 子命令）")
    r.add_argument("--year", type=int, help="只看某个自然年")
    r.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    r.add_argument("--to", dest="date_to", help="截止日期 YYYY-MM-DD")
    r.add_argument("--out", help="主报告输出路径（.md 或 .html；另一份自动写到同目录）")
    r.add_argument("--mask", action="store_true", help="金额与股票代码打码（比率不变，绝对值改为比例）")
    r.set_defaults(func=cmd_recap)

    c = sub.add_parser("columns", help="打印 CSV 识别到的列与映射情况")
    c.add_argument("csv")
    c.add_argument("--mapping", help="参照哪个映射检查")
    c.set_defaults(func=cmd_columns)

    mm = sub.add_parser("mappings", help="列出可用列映射")
    mm.set_defaults(func=cmd_mappings)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except RecapError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
