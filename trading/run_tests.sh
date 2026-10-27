#!/usr/bin/env bash
# Every test suite in the trading repo, one command, one exit code.
#
# Each strategy is an independent package with its own tests, and they do NOT share a
# sys.path: scripts inside a strategy import their siblings bare (`import rules`,
# `from event_scanner import ...`) because that is how they run in production, while
# the tests import them by package path (`from strategies.csp_401k import rules`).
# So each suite needs BOTH the repo root and its own strategy folder on PYTHONPATH.
# Running pytest once over the whole tree collapses those into a single path and
# silently loads some modules twice under two names — see the dual-import note in
# strategies/csp_401k/tests/test_earnings_blindspot.py, where that produced a test
# that passed for a completely fabricated reason.
#
# Usage:  trading/run_tests.sh          # all suites
#         trading/run_tests.sh -q       # extra args pass through to pytest
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

PY="${HEDGY_PYTHON:-$HERE/../.venv/bin/python3}"
[ -x "$PY" ] || PY="$HERE/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
[ -x "$PY" ] || { echo "no python3 found"; exit 1; }

SUITES=(tests strategies/*/tests)
failed=()

# Root-level test files sit beside the modules they cover instead of in a tests/ dir,
# so the directory globs above miss them. Include renderer and root-module coverage
# so a position verdict cannot contradict its proposed ticket without detection.
# Root modules need only the trading root on PYTHONPATH. The glob automatically
# includes newly added root test files.
shopt -s nullglob
ROOT_TESTS=(test_*.py)
shopt -u nullglob
if [ ${#ROOT_TESTS[@]} -gt 0 ]; then
  out="$(PYTHONPATH="." "$PY" -m pytest "${ROOT_TESTS[@]}" -q "$@" 2>&1)"
  rc=$?
  tail="$(printf '%s\n' "$out" | tail -1)"
  if [ $rc -eq 0 ]; then
    printf '  ok    %-42s %s\n' "test_*.py (repo root)" "$tail"
  else
    printf '  FAIL  %-42s %s\n' "test_*.py (repo root)" "$tail"
    printf '%s\n' "$out" | sed 's/^/        /'
    failed+=("test_*.py (repo root)")
  fi
fi

for suite in "${SUITES[@]}"; do
  [ -d "$suite" ] || continue
  owner="$(dirname "$suite")"          # repo root for trading/tests, else the strategy dir
  out="$(PYTHONPATH=".:$owner" "$PY" -m pytest "$suite" -q "$@" 2>&1)"
  rc=$?
  tail="$(printf '%s\n' "$out" | tail -1)"
  if [ $rc -eq 0 ]; then
    printf '  ok    %-42s %s\n' "$suite" "$tail"
  else
    printf '  FAIL  %-42s %s\n' "$suite" "$tail"
    printf '%s\n' "$out" | sed 's/^/        /'
    failed+=("$suite")
  fi
done

if [ ${#failed[@]} -gt 0 ]; then
  echo
  echo "FAILED: ${failed[*]}"
  exit 1
fi
echo "all suites passed"
