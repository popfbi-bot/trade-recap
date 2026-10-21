"""CSV 读取：编码探测 + 列映射。

设计原则：
- 券商列名各不相同，所以列名一律来自 mappings/*.json，代码里不出现任何具体列名。
- 编码按 utf-8-sig → gbk 顺序尝试，把实际使用的编码一路带到报告里。
- 金额用 Decimal(str(x)) 转换，永不经过 float。
"""

import csv
import io
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.errors import RecapError
from core.models import TradeRecapRow

REQUIRED_FIELDS = ("date", "code", "side", "price", "qty", "amount", "fee")
ENCODINGS = ("utf-8-sig", "gbk")
MAPPING_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mappings")


class LoadResult:
    """读入结果：行数据 + 本次实际使用的编码 + 列映射信息。"""

    def __init__(self, rows, encoding, mapping_name, mapping, columns_used):
        self.rows = rows
        self.encoding = encoding
        self.mapping_name = mapping_name
        self.mapping = mapping
        self.columns_used = columns_used


def list_mappings():
    """返回 (名称列表, 详细字典)。名称取自 json 的 name 字段，缺省用文件名。"""
    out = []
    if not os.path.isdir(MAPPING_DIR):
        return out
    for fn in sorted(os.listdir(MAPPING_DIR)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(MAPPING_DIR, fn), encoding="utf-8") as fh:
            data = json.load(fh)
        out.append((data.get("name") or fn[:-5], data, fn))
    return out


def load_mapping(name_or_path: str) -> dict:
    """按名字或文件路径加载映射。名字不含路径分隔符时到 mappings/ 下找。"""
    if os.sep in name_or_path or name_or_path.endswith(".json"):
        path = name_or_path
        if not os.path.isfile(path):
            raise RecapError(f"找不到映射文件：{path}")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    candidates = [item for item in list_mappings() if item[0] == name_or_path or item[2][:-5] == name_or_path]
    if not candidates:
        available = "、".join(item[0] for item in list_mappings()) or "（无）"
        raise RecapError(f"不认识的映射名：{name_or_path}。可用映射：{available}（也可直接传 json 文件路径）")
    return candidates[0][1]


def validate_mapping(mapping: dict, mapping_ref: str) -> None:
    """缺必需列时给出人话报错：缺哪一列、在哪配置映射。"""
    columns = mapping.get("columns") or {}
    missing = [f for f in REQUIRED_FIELDS if not columns.get(f)]
    if missing:
        raise RecapError(
            "列映射不完整：缺少 "
            + "、".join(missing)
            + f" 对应的列名配置。请在 mappings/ 下的映射文件里补齐 columns 字段"
            + f"（当前映射：{mapping_ref}；可用字段：{', '.join(REQUIRED_FIELDS)}）"
        )
    side_values = mapping.get("side_values") or {}
    for key in ("buy", "sell"):
        if not side_values.get(key):
            raise RecapError(
                f"列映射不完整：side_values.{key} 为空，无法识别买卖方向。"
                f"请在 mappings/ 下的映射文件里配置 side_values.{key}（当前映射：{mapping_ref}）"
            )


def read_text(path: str):
    """按 utf-8-sig → gbk 顺序尝试解码，返回 (文本, 编码名)。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw:
        raise RecapError(f"文件是空的：{path}")
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise RecapError(f"无法识别文件编码（已尝试 {' → '.join(ENCODINGS)}）：{path}。请另存为 UTF-8 或 GBK 后重试")


def _decimal(value: Any, field: str, line_no: int) -> Decimal:
    text = ("" if value is None else str(value)).strip().replace(",", "").replace("，", "")
    if text in ("", "-", "--"):
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise RecapError(f"第 {line_no} 行的 {field} 不是合法数字：{value!r}") from None


def _parse_date(value: Any, fmt: str, line_no: int):
    text = ("" if value is None else str(value)).strip()
    fmt = fmt or "%Y-%m-%d"
    for candidate in (text, text.replace("/", "-"), text.replace(".", "-")):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
        for alt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, alt).date()
            except ValueError:
                continue
    raise RecapError(f"第 {line_no} 行的日期无法解析：{value!r}（映射里配置的格式是 {fmt}）")


def read_header(path: str):
    """只读表头，给 `columns` 子命令用。返回 (表头列表, 编码)。"""
    text, enc = read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or []), enc


def _norm_side(value: str, side_values: dict) -> str:
    v = (value or "").strip().lower()
    for key in ("buy", "sell"):
        for option in side_values.get(key) or []:
            if v == str(option).strip().lower():
                return key
    return ""


def load_csv(path: str, mapping: dict, mapping_ref: str = "") -> LoadResult:
    """读入交割单并规范化。

    amount 列若为空，用 price × qty 兜底（很多券商导出不含成交金额列）。
    """
    validate_mapping(mapping, mapping_ref or mapping.get("name", "<未知>"))
    if not os.path.isfile(path):
        raise RecapError(f"找不到输入文件：{path}")

    text, encoding = read_text(path)
    columns = mapping["columns"]
    date_format = mapping.get("date_format") or "%Y-%m-%d"
    side_values = mapping["side_values"]

    reader = csv.DictReader(io.StringIO(text))
    header = list(reader.fieldnames or [])
    missing_in_file = [columns[f] for f in REQUIRED_FIELDS if columns[f] not in header]
    if missing_in_file:
        raise RecapError(
            "CSV 里找不到映射要求的列："
            + "、".join(missing_in_file)
            + f"。请核对列名（当前映射：{mapping_ref or mapping.get('name', '<未知>')}），"
            + "或用 `python cli.py columns <文件>` 查看实际列名后修改 mappings/ 下的映射文件。"
        )

    rows: list[TradeRecapRow] = []
    for idx, raw in enumerate(reader, start=2):
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        side = _norm_side(raw.get(columns["side"], ""), side_values)
        if not side:
            raise RecapError(
                f"第 {idx} 行的方向无法识别：{raw.get(columns['side'])!r}。"
                f"请在 mappings/ 的 side_values 里补上这个取值（当前映射：{mapping_ref or mapping.get('name', '')}）"
            )
        price = _decimal(raw.get(columns["price"]), "价格", idx)
        qty = _decimal(raw.get(columns["qty"]), "数量", idx)
        amount = _decimal(raw.get(columns["amount"]), "成交金额", idx)
        if amount == 0:
            amount = price * qty
        rows.append(
            TradeRecapRow(
                line_no=idx,
                date=_parse_date(raw.get(columns["date"]), date_format, idx),
                code=(raw.get(columns["code"]) or "").strip(),
                side=side,
                price=price,
                qty=qty,
                amount=amount,
                fee=_decimal(raw.get(columns["fee"]), "费用", idx),
            )
        )

    if not rows:
        raise RecapError(f"交割单里没有任何有效数据行：{path}")

    rows.sort(key=lambda r: (r.date, r.line_no))
    return LoadResult(rows, encoding, mapping_ref or mapping.get("name", ""), mapping, columns)
