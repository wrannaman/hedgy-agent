import unittest

from strategies.csp_401k.blackscholes import put_price, put_delta


class BlackScholesTests(unittest.TestCase):
    def test_atm_put_price_reference(self):
        # ATM 1yr put, 20% vol, 4% rate ~ 6.04 (standard BS reference value).
        self.assertAlmostEqual(put_price(100, 100, 365, 20.0), 6.04, places=1)

    def test_intrinsic_at_expiry(self):
        self.assertEqual(put_price(90, 100, 0, 30.0), 10.0)   # ITM -> intrinsic
        self.assertEqual(put_price(110, 100, 0, 30.0), 0.0)   # OTM -> worthless

    def test_deep_otm_put_delta_small(self):
        # ~24% OTM put, 45 DTE, 45% vol: |delta| should be small single digits.
        d = put_delta(100, 76, 45, 45.0)
        self.assertTrue(-0.20 < d < 0.0)

    def test_iv_above_rv_implies_positive_ev(self):
        # Sold at IV (priced rich), fair value at lower RV is cheaper -> edge > 0.
        sold_at_iv = put_price(100, 80, 40, 50.0)
        fair_at_rv = put_price(100, 80, 40, 35.0)
        self.assertGreater(sold_at_iv - fair_at_rv, 0)


if __name__ == "__main__":
    unittest.main()
