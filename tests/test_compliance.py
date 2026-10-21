"""判据 8：合规文案专项。

红线：
1. report.md / report.html 必须含完整免责声明（原文照抄）。
2. 报告中不得出现投资建议类词汇。
"""

import os
import tempfile
import unittest

from tests.helpers import fixture, run_cli
from core.report import BANNED_WORDS, DISCLAIMER

EXPECTED_DISCLAIMER = (
    "本工具仅对用户本人的历史交易记录做统计与归因，不构成任何投资建议，不预测未来收益。"
    "所有结论仅反映过去已发生的交易事实。投资有风险，决策请自行判断。"
)


def generate(tmp, *extra):
    code, out, err = run_cli(
        ["recap", fixture("synthetic.csv"), "--mapping", "generic-cn", "--year", "2026", *extra], cwd=tmp
    )
    assert code == 0, err
    return (
        open(os.path.join(tmp, "report.md"), encoding="utf-8").read(),
        open(os.path.join(tmp, "report.html"), encoding="utf-8").read(),
        out,
    )


class ComplianceTest(unittest.TestCase):
    def test_disclaimer_text_is_verbatim(self):
        self.assertEqual(DISCLAIMER, EXPECTED_DISCLAIMER)

    def test_disclaimer_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, page, out = generate(tmp)
            self.assertIn(EXPECTED_DISCLAIMER, md)
            self.assertIn(EXPECTED_DISCLAIMER, page)

    def test_no_banned_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, page, out = generate(tmp)
            for word in BANNED_WORDS:
                self.assertNotIn(word, md, f"report.md 出现违规词：{word}")
                self.assertNotIn(word, page, f"report.html 出现违规词：{word}")
                self.assertNotIn(word, out, f"终端摘要出现违规词：{word}")

    def test_banned_list_is_not_empty(self):
        """防止有人把黑名单清空让测试假绿。"""
        self.assertGreaterEqual(len(BANNED_WORDS), 4)
        self.assertIn("目标价", BANNED_WORDS)

    def test_html_is_self_contained(self):
        """report.html 必须单文件内联：不许外链 CSS/JS/图片。"""
        with tempfile.TemporaryDirectory() as tmp:
            _, page, _ = generate(tmp)
            self.assertIn("<style>", page)
            self.assertNotIn("<link", page)
            self.assertNotIn("<script", page)
            self.assertNotIn("http://", page)
            self.assertNotIn("https://", page)

    def test_html_has_big_cards_upfront(self):
        """首屏要有 4 个核心数字卡片 + 一句话结论。"""
        with tempfile.TemporaryDirectory() as tmp:
            _, page, _ = generate(tmp)
            self.assertEqual(page.count('class="card"'), 4)
            self.assertIn('class="verdict"', page)


if __name__ == "__main__":
    unittest.main()
