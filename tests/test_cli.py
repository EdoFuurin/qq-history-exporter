"""端到端测试：用合成假库跑通导出流程（不依赖任何真实数据）。

运行：
    pip install -e .            # 或把仓库 src/ 加入 PYTHONPATH
    python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from qqhex import cli  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ntdb")
KEY = "FIXTUREKEY123456"


class TestUnits(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(cli.safe_name("a/b:c*?"), "a_b_c__")
        self.assertEqual(cli.safe_name("普通好友"), "普通好友")

    def test_fmt_ts(self):
        self.assertTrue(cli.fmt_ts(0).startswith("1970-01-01"))
        self.assertEqual(cli.fmt_ts("not-a-ts"), "not-a-ts")


class TestExport(unittest.TestCase):
    def _export(self, peers):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
        os.makedirs(base, exist_ok=True)
        n = sum(1 for x in os.listdir(base) if x.startswith("run_"))
        out = os.path.join(base, "run_%d" % n)
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        args = ["--ntdb-dir", FIXTURE, "--key", KEY, "--uin", "10001",
                "--out", out] + (["--peers"] + peers if peers else [])
        cli.main(args)
        return out

    def test_export_friendA_full(self):
        out = self._export(["好友A"])
        chats = os.path.join(out, "chats")
        path = os.path.join(chats, "buddy_好友A.md")
        self.assertTrue(os.path.exists(path), "应生成好友A的导出文件")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("你好，这是发给好友A的测试消息一", text)
        self.assertIn("测试消息二：收到收到", text)
        self.assertRegex(text, r"\[2026-\d{2}-\d{2}")   # 时间戳正常渲染
        self.assertGreaterEqual(text.count("\n["), 3)  # A：3 条（含一条无文本占位）
        self.assertIn("对方: [（无文本", text)          # 空 blob 行以占位形式保留
        idx = open(os.path.join(chats, "_index.md"), encoding="utf-8").read()
        self.assertIn("好友A", idx)

    def test_export_friendB(self):
        out = self._export(["好友B"])
        self.assertTrue(os.path.exists(os.path.join(out, "chats", "buddy_好友B.md")))
        self.assertFalse(os.path.exists(os.path.join(out, "chats", "buddy_好友A.md")))


if __name__ == "__main__":
    unittest.main()
