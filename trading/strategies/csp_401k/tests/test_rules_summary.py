"""RULES.md's one-page summary must quote the numbers rules.py actually uses."""

import re
import unittest
from pathlib import Path

from shared.universe import UNIVERSE
from strategies.csp_401k import rules

RULES_MD = Path(__file__).resolve().parents[1] / "RULES.md"
ROW = re.compile(r"^\|[^|]*\|[^|]*\|((?: *`[A-Z_]+`,?)+) *\| *([0-9., ]+?) *\|$", re.M)


def summary():
    text = RULES_MD.read_text()
    start = text.index("## The strategy on one page")
    return text[start:text.index("\n## 0.", start)]


class RulesSummaryTests(unittest.TestCase):
    def test_every_quoted_number_matches_rules_py(self):
        rows = ROW.findall(summary())
        self.assertGreaterEqual(len(rows), 15, "summary tables went missing or changed shape")
        for names, values in rows:
            names = re.findall(r"[A-Z_]+", names)
            values = [float(v) for v in values.split(",")]
            self.assertEqual(len(names), len(values), names)
            for name, value in zip(names, values):
                self.assertEqual(float(getattr(rules, name)), value, name)

    def test_prose_numbers_match(self):
        text = summary()
        self.assertIn(f"all {len(UNIVERSE)} optionable names", text)
        self.assertIn(f"`NEAR_52W_LOW_BAND_PCT` ({rules.NEAR_52W_LOW_BAND_PCT})", text)
        self.assertFalse(rules.MANAGE_DTE_CUTS_LOSERS, "summary says a far-OTM loser is held at 21 DTE")
        self.assertEqual(rules.MAX_POSITIONS_PER_UNDERLYING, 1, "summary says one position per underlying")


if __name__ == "__main__":
    unittest.main()
