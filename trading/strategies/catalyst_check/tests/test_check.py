import tempfile
import unittest
from pathlib import Path

from strategies.catalyst_check import check


class CatalystCheckTests(unittest.TestCase):
    def test_blocks_severe_bad_news_terms(self):
        articles = [
            check.Article(
                title="XYZ falls after SEC investigation into accounting irregularities",
                link="https://example.com/xyz",
                published="2026-06-03T12:00:00+00:00",
                summary="Company says it is cooperating.",
            )
        ]

        result = check.classify_articles("XYZ", articles)

        self.assertEqual(result["verdict"], "block")
        self.assertEqual(result["hits"][0]["severity"], "block")

    def test_cautions_on_fetch_error(self):
        result = check.classify_articles("XYZ", [], fetch_error="network down")

        self.assertEqual(result["verdict"], "caution")
        self.assertIn("review", result["summary"])

    def test_run_uses_candidate_from_decision_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision = root / "morning_decision.json"
            state = root / "state"
            decision.write_text(
                '{"screen_timestamp":"2026-06-03T07:00:00",'
                '"best_candidate":{"symbol":"MSTR","expiration":"2026-07-17"}}'
            )

            payload = check.run(decision_path=decision, state_dir=state, fetch=False)

            self.assertEqual(payload["symbol"], "MSTR")
            self.assertEqual(payload["screen_timestamp"], "2026-06-03T07:00:00")
            self.assertEqual(payload["verdict"], "caution")
            self.assertTrue((state / "latest.json").exists())
            self.assertTrue((state / "MSTR.json").exists())
            self.assertTrue((state / "latest_summary.txt").exists())

    def test_uses_top_scored_candidate_when_best_candidate_absent(self):
        decision = {
            "action": "CHECK_CANDIDATE",
            "best_candidate": None,
            "candidates": [{"symbol": "MSTR", "expiration": "2026-07-17"}],
        }

        symbol, expiration = check.candidate_from_decision(decision)

        self.assertEqual(symbol, "MSTR")
        self.assertEqual(expiration, "2026-07-17")

    def test_does_not_fallback_to_put_when_decision_is_not_candidate_check(self):
        decision = {
            "action": "CHECK_COVERED_CALL",
            "best_candidate": None,
            "candidates": [{"symbol": "MSTR", "expiration": "2026-07-17"}],
        }

        symbol, expiration = check.candidate_from_decision(decision)

        self.assertIsNone(symbol)
        self.assertIsNone(expiration)


if __name__ == "__main__":
    unittest.main()
