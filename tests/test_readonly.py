"""判据 9：只读 —— 跑前跑后输入文件 sha256 一致，且不在输入目录写垃圾。"""

import hashlib
import os
import shutil
import tempfile
import unittest

from tests.helpers import fixture, run_cli


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ReadOnlyTest(unittest.TestCase):
    def test_input_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "交割单.csv")
            shutil.copyfile(fixture("synthetic.csv"), csv_path)
            before = sha256(csv_path)
            code, out, err = run_cli(["recap", csv_path, "--mapping", "generic-cn", "--year", "2026"], cwd=tmp)
            self.assertEqual(code, 0, err)
            self.assertEqual(sha256(csv_path), before)

    def test_only_reports_are_written(self):
        """工作目录里只应多出 report.md / report.html，不留临时文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "交割单.csv")
            shutil.copyfile(fixture("synthetic.csv"), csv_path)
            before = set(os.listdir(tmp))
            code, _, err = run_cli(["recap", csv_path, "--mapping", "generic-cn", "--year", "2026"], cwd=tmp)
            self.assertEqual(code, 0, err)
            after = set(os.listdir(tmp))
            self.assertEqual(after - before, {"report.md", "report.html"})


if __name__ == "__main__":
    unittest.main()
