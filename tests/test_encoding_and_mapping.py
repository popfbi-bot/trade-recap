"""判据 4 / 5：GBK 编码读写，以及缺列时的清晰报错。"""

import os
import tempfile
import unittest

from tests.helpers import ROOT, fixture, run_cli
from core.errors import RecapError
from core.loader import load_csv, load_mapping, read_text

GBK_ROWS = "成交日期,证券代码,买卖标志,成交价格,成交数量,成交金额,手续费\n2026-01-05,600000,买入,10.00,100,1000.00,5.00\n2026-01-10,600000,卖出,12.00,100,1200.00,6.20\n"


class EncodingTest(unittest.TestCase):
    def test_gbk_csv_loads(self):
        """GBK 编码的交割单必须能正确读出，且加载结果里注明用了 gbk。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gbk.csv")
            with open(path, "wb") as fh:
                fh.write(GBK_ROWS.encode("gbk"))
            text, enc = read_text(path)
            self.assertEqual(enc, "gbk")
            self.assertIn("证券代码", text)
            loaded = load_csv(path, load_mapping("generic-cn"), "generic-cn")
            self.assertEqual(loaded.encoding, "gbk")
            self.assertEqual(len(loaded.rows), 2)
            self.assertEqual(loaded.rows[0].code, "600000")

    def test_report_notes_encoding(self):
        """报告里必须注明实际使用的编码。"""
        mapping = {
            "name": "probe",
            "columns": {
                "date": "d", "code": "c", "side": "s", "price": "p", "qty": "q", "amount": "a", "fee": "f",
            },
            "date_format": "%Y-%m-%d",
            "side_values": {"buy": ["买入"], "sell": ["卖出"]},
        }
        body = "d,c,s,p,q,a,f\n2026-01-05,600000,买入,10.00,100,1000.00,5.00\n2026-01-10,600000,卖出,12.00,100,1200.00,6.20\n"
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "gbk.csv")
            with open(csv_path, "wb") as fh:
                fh.write(body.encode("gbk"))
            code, out, err = run_cli(
                ["recap", csv_path, "--mapping", "generic-cn", "--year", "2026"], cwd=tmp
            )
            # 列名与 generic-cn 不同 → 应报错，报错里点明缺哪列
            self.assertEqual(code, 1)
            self.assertIn("成交日期", err)

            # 用临时映射文件重跑，验证成功路径里编码出现在报告中
            import json

            map_path = os.path.join(tmp, "probe.json")
            with open(map_path, "w", encoding="utf-8") as fh:
                json.dump(mapping, fh, ensure_ascii=False)
            code, out, err = run_cli(["recap", csv_path, "--mapping", map_path, "--year", "2026"], cwd=tmp)
            self.assertEqual(code, 0, err)
            with open(os.path.join(tmp, "report.md"), encoding="utf-8") as fh:
                md = fh.read()
            self.assertIn("gbk", md)

    def test_utf8_sig_preferred(self):
        """带 BOM 的 UTF-8 走 utf-8-sig，不会把 BOM 带进第一个列名。"""
        loaded = load_csv(fixture("synthetic.csv"), load_mapping("generic-cn"), "generic-cn")
        self.assertEqual(loaded.encoding, "utf-8-sig")


class MappingTest(unittest.TestCase):
    def test_missing_column_reports_clearly(self):
        """缺必需列时报错信息必须包含「缺哪一列」和「在哪配置」，不得抛裸 KeyError。"""
        broken = {
            "name": "broken",
            "columns": {
                "date": "成交日期", "code": "证券代码", "side": "买卖标志",
                "price": "成交价格", "qty": "成交数量", "amount": "成交金额",
                # 故意缺 fee
            },
            "date_format": "%Y-%m-%d",
            "side_values": {"buy": ["买入"], "sell": ["卖出"]},
        }
        with self.assertRaises(RecapError) as cm:
            load_csv(fixture("synthetic.csv"), broken, "broken")
        msg = str(cm.exception)
        self.assertIn("fee", msg)
        self.assertIn("mappings/", msg)
        self.assertIn("columns", msg)

    def test_csv_column_not_in_file_reports_clearly(self):
        """映射要的列在 CSV 里不存在时，报错要列出实际缺失的列名。"""
        good = load_mapping("huatai")  # huatai 用「发生日期」等列名
        with self.assertRaises(RecapError) as cm:
            load_csv(fixture("synthetic.csv"), good, "huatai")
        msg = str(cm.exception)
        self.assertIn("发生日期", msg)
        self.assertIn("cli.py columns", msg)

    def test_three_mappings_exist(self):
        """至少 3 个映射：generic-cn / huatai / eastmoney，结构符合约定。"""
        for name in ("generic-cn", "huatai", "eastmoney"):
            m = load_mapping(name)
            for field in ("date", "code", "side", "price", "qty", "amount", "fee"):
                self.assertIn(field, m["columns"], f"{name} 缺少 {field}")
            self.assertIn("buy", m["side_values"])
            self.assertIn("sell", m["side_values"])
            self.assertIn("date_format", m)

    def test_columns_command_lists_unmapped(self):
        """columns 子命令要明确指出未映射的列。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "extra.csv")
            body = (
                "成交日期,证券代码,买卖标志,成交价格,成交数量,成交金额,手续费,备注\n"
                + GBK_ROWS.split("\n", 1)[1]
            )
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            code, out, err = run_cli(["columns", path], cwd=tmp)
            self.assertEqual(code, 0, err)
            self.assertIn("未映射", out)
            self.assertIn("备注", out)


if __name__ == "__main__":
    unittest.main()
