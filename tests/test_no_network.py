"""判据 6：零网络 —— 用 ast 静态扫描全部 .py，禁用模块一个都不许进来。

这条测试必须「能被证明会失败」：在任意 .py 里临时加 `import socket` 后重跑本测试应立刻变红。
"""

import ast
import os
import unittest

from tests.helpers import ROOT

FORBIDDEN = ("socket", "urllib", "http", "requests", "ftplib", "ssl", "telnetlib", "smtplib", "asyncio")
SKIP_DIRS = {".git", "__pycache__", "node_modules"}


def iter_py_files(root=ROOT):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _module_root(name: str) -> str:
    return name.split(".")[0]


def imports_of(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
    return found


class NoNetworkTest(unittest.TestCase):
    def test_no_network_imports(self):
        violations = []
        for path in iter_py_files():
            for name in imports_of(path):
                if _module_root(name) in FORBIDDEN:
                    violations.append(f"{os.path.relpath(path, ROOT)}: import {name}")
        self.assertEqual(violations, [], "发现网络相关 import：" + "; ".join(violations))

    def test_scanner_actually_detects_violation(self):
        """先证明扫描器有效：给自己造的坏样本必须被抓出来，否则上面那条测试是空转。"""
        import tempfile

        bad = "import socket\nimport urllib.request\nfrom http.client import HTTPConnection\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(bad)
            found = [_module_root(n) for n in imports_of(path)]
        self.assertIn("socket", found)
        self.assertIn("urllib", found)
        self.assertIn("http", found)

    def test_no_open_url_patterns(self):
        """同时禁掉常见的「软网络」调用痕迹（扫描时跳过本文件，避免自我匹配）。"""
        patterns = ("url" + "open(", "requests" + ".get", "requests" + ".post", "socket" + ".socket", "create_" + "connection(")
        hits = []
        for path in iter_py_files():
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for p in patterns:
                if p in text:
                    hits.append(f"{os.path.relpath(path, ROOT)}: {p}")
        self.assertEqual(hits, [], "发现网络调用痕迹：" + "; ".join(hits))


if __name__ == "__main__":
    unittest.main()
