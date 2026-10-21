"""测试公用：路径、跑 CLI、读报告。"""

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures")
TESTS = os.path.dirname(os.path.abspath(__file__))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def run_cli(argv, cwd=None) -> tuple:
    """在进程内跑 cli.main，返回 (退出码, stdout, stderr)。不落任何临时文件到仓库。"""
    import cli

    out, err = io.StringIO(), io.StringIO()
    old_cwd = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
    finally:
        os.chdir(old_cwd)
    return code, out.getvalue(), err.getvalue()
