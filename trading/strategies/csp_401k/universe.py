"""Re-export of the canonical screening universe.

The list itself lives in shared/universe.py — one list, defined once, imported
everywhere (FUND.md §6). It moved there because the PEAD sleeve screens the same
names and sleeves may never import each other's code; shared/ is the sanctioned
home. This module stays so every csp_401k import path keeps working.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.universe import UNIVERSE  # noqa: F401,E402
