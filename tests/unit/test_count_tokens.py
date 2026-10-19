"""Dev-only real-tokenizer S5 (ADR-051 item 5), exercised with a fake counter: no network, no key."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_tool():
    spec = importlib.util.spec_from_file_location("count_tokens_under_test", ROOT / "bench" / "count_tokens.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CountTokens(unittest.TestCase):
    def setUp(self):
        self.ct = load_tool()

    def test_missing_key_is_an_error_never_a_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(self.ct.TokenizerUnavailable):
                self.ct.Counter()

    def test_s5_real_subtracts_framing_and_records_hashes(self):
        fake = lambda text, key: 10 + len(text.split())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), mock.patch.object(self.ct, "_request", fake):
            counter = self.ct.Counter()
            self.assertEqual(counter.baseline, 10)
            dirs = sorted(d for d in (ROOT / "bench" / "tasks").iterdir() if d.is_dir())[:2]
            res = self.ct.s5_real(dirs, counter)
        self.assertEqual(res["meta"]["model"], self.ct.MODEL)
        row = res["rows"][0]
        self.assertEqual(row["lm"]["raw"] - row["lm"]["net"], 10)
        self.assertEqual(len(row["py_full"]["sha256"]), 64)
        self.assertGreater(res["median_vs_full"], 0)
        self.assertIn("Anthropic tokenizer", self.ct.summary_section(res))


if __name__ == "__main__":
    unittest.main()
