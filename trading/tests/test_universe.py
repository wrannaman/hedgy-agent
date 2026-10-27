import unittest

from shared.universe import UNIVERSE, display_name


class UniverseTests(unittest.TestCase):
    def test_spacex_is_screened_and_named(self):
        self.assertIn("SPCX", UNIVERSE)
        self.assertEqual(display_name("SPCX"), "SpaceX (SPCX)")
        self.assertEqual(UNIVERSE.count("SPCX"), 1)


if __name__ == "__main__":
    unittest.main()
