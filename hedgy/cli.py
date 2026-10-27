"""Small agent-friendly entry points over the independent strategy modules."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from hedgy import __version__


class SetupError(RuntimeError):
    pass


def checkout_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / 'trading' / 'run_tests.sh').is_file():
        raise SetupError(
            'Hedgy runs from a source checkout. Clone https://github.com/wrannaman/hedgy-agent '
            'and run `python -m pip install -e .` there. A standalone wheel has no strategy workspace.'
        )
    return root


def strategy_environment(root: Path, *, demo: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root / 'trading')
    if demo:
        # The demo must not inherit a real account mapping, token, or integration.
        for key in list(env):
            if key.startswith(('HEDGY_', 'SCHWAB_', 'SLACK_', 'FINNHUB_', 'CLAUDE_')):
                del env[key]
        env['HEDGY_ACCOUNTS_CONFIG'] = str(root / 'trading' / 'accounts.example.json')
        env['HEDGY_NO_LOCAL_ENV'] = '1'
        env['HEDGY_STANDING_RISK_CONFIG'] = str(root / 'trading/strategies/csp_401k/standing_risk.json')
    return env


def run_strategy(root: Path, script: str, arguments: list[str], *, demo: bool = False) -> int:
    command = [sys.executable, str(root / 'trading' / script), *arguments]
    return subprocess.run(command, cwd=root, env=strategy_environment(root, demo=demo)).returncode


def demo(root: Path, output: Path | None) -> int:
    # A new directory per run cannot overwrite a real report or trading state.
    if output:
        output = output.expanduser().resolve()
        if output.exists():
            raise SetupError('Demo output must be a new directory; existing data is never overwritten.')
        if output == root or root in output.parents and 'trading' in output.relative_to(root).parts:
            raise SetupError('Keep demo output outside the trading workspace.')
        output.mkdir(parents=True, mode=0o700)
    else:
        output = Path(tempfile.mkdtemp(prefix='hedgy-demo-'))
    common = ['--no-quotes', '--positions-dir', str(root / 'trading/examples/positions')]
    print('Hedgy demo: synthetic holdings, no credentials, no network, no orders.', flush=True)
    for script, report, extra in [
        ('sweep.py', 'portfolio', []),
        ('rebalance.py', 'rebalance', ['--target', '1000']),
    ]:
        rc = run_strategy(root, f'strategies/portfolio_watch/{script}', [
            *common, '--state-dir', str(output / report), *extra], demo=True)
        if rc:
            return rc
    # Report locations are explicit and machine-readable.
    manifest = {'synthetic': True, 'portfolio': str(output / 'portfolio/latest.json'),
                'rebalance': str(output / 'rebalance/rebalance.json')}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'DEMO OK\nReports: {output}\nManifest: {output / "manifest.json"}')
    return 0


def doctor(root: Path, live: bool) -> int:
    checks = [
        ('Python >=3.11', sys.version_info >= (3, 11)),
        ('source checkout', (root / 'trading/run_tests.sh').is_file()),
        ('requests', importlib.util.find_spec('requests') is not None),
        ('python-dotenv', importlib.util.find_spec('dotenv') is not None),
        ('synthetic sample', (root / 'trading/examples/positions/demo.csv').is_file()),
    ]
    for name, ok in checks:
        print(f'{"OK" if ok else "MISSING"} {name}')
    if live:
        # Check presence only. Never open or display credentials or tokens.
        credential_file = (root / 'trading/.schwab').is_file()
        checks.extend([
            ('optional Schwab package', importlib.util.find_spec('schwab') is not None),
            ('Schwab credential configuration', credential_file or bool(
                os.environ.get('SCHWAB_APP_KEY') and os.environ.get('SCHWAB_APP_SECRET'))),
            ('local OAuth token (authenticate with hedgy auth)', (root / 'trading/token.json').is_file()),
            ('account selection configuration', (root / 'trading/.env.local').is_file() or bool(
                os.environ.get('SCHWAB_ACCOUNT_SUFFIX'))),
        ])
        for name, ok in checks[-4:]:
            print(f'{"OK" if ok else "MISSING"} {name}')
    else:
        print('Optional: Schwab market data, Finnhub earnings, Slack, Claude scheduler (not needed for CSV/demo).')
    ok = all(passed for _, passed in checks)
    print('DOCTOR OK' if ok else 'DOCTOR: setup incomplete; see docs/SETUP.md')
    return 0 if ok else 1


def init_config(root: Path) -> int:
    for source, target in [('accounts.example.json', 'accounts.local.json'),
                           ('.env.example', '.schwab'), ('.env.local.example', '.env.local')]:
        dest = root / 'trading' / target
        if dest.exists():
            print(f'Kept existing trading/{target}')
            continue
        # Exclusive create avoids clobbering credentials, including concurrent runs.
        with open(dest, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            handle.write((root / 'trading' / source).read_text())
        print(f'Created private template trading/{target}')
    print('Edit these files locally. Do not paste their contents into an agent conversation.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Agent-assisted research and recommendations. Never places orders.')
    parser.add_argument('--version', action='version', version=f'hedgy {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('demo', help='Run synthetic portfolio analysis with no account or network.')
    p.add_argument('--output', type=Path, help='New directory for demo reports (default: a new temporary directory).')
    p = commands.add_parser('doctor', help='Check setup without opening credentials or contacting services.')
    p.add_argument('--live', action='store_true', help='Also check presence of optional Schwab setup.')
    commands.add_parser('init', help='Create private account/credential templates; never overwrite existing files.')
    commands.add_parser('auth', help='Explicit interactive Schwab login; redirect URL stays in your terminal.')
    commands.add_parser('test', help='Run isolated strategy test suites (requires .[dev] and Bash).')
    p = commands.add_parser('portfolio', help='Analyze your CSV snapshots (offline by default).')
    p.add_argument('operation', choices=['sweep', 'rebalance'])
    p.add_argument('--positions-dir', type=Path, required=True)
    p.add_argument('--state-dir', type=Path, help='Private report directory; default is strategy state/.')
    p.add_argument('--accounts', type=Path, help='Local account metadata JSON (overrides default).')
    p.add_argument('--live-quotes', action='store_true', help='Opt into Schwab quote requests; requires live setup.')
    p.add_argument('--target', type=float, default=None, help='Rebalance cash target.')
    p.add_argument('--ca-rate', type=float, default=None, help='Rebalance state marginal capital-gain rate.')
    p.add_argument('--fed-rate', type=float, default=None, help='Rebalance federal long-term capital-gain rate.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = checkout_root()
        if args.command == 'demo':
            return demo(root, args.output)
        if args.command == 'doctor':
            return doctor(root, args.live)
        if args.command == 'init':
            return init_config(root)
        if args.command == 'auth':
            return run_strategy(root, 'shared/login.py', [])
        if args.command == 'test':
            bash = shutil.which('bash')
            if not bash:
                raise SetupError('Install Bash to run the isolated strategy test harness.')
            env = strategy_environment(root, demo=True)
            env['HEDGY_PYTHON'] = sys.executable
            return subprocess.run([bash, str(root / 'trading/run_tests.sh')], cwd=root, env=env).returncode
        if args.command == 'portfolio':
            arguments = ['--positions-dir', str(args.positions_dir.expanduser().resolve())]
            if not args.live_quotes:
                arguments.append('--no-quotes')
            if args.state_dir:
                arguments += ['--state-dir', str(args.state_dir.expanduser().resolve())]
            if args.operation == 'sweep' and any(v is not None for v in [args.target, args.ca_rate, args.fed_rate]):
                raise SetupError('--target, --ca-rate and --fed-rate are rebalance options.')
            for attr in ['target', 'ca_rate', 'fed_rate']:
                value = getattr(args, attr)
                if value is not None:
                    arguments += ['--' + attr.replace('_', '-'), str(value)]
            env = strategy_environment(root)
            if args.accounts:
                env['HEDGY_ACCOUNTS_CONFIG'] = str(args.accounts.expanduser().resolve())
            return subprocess.run([sys.executable, str(root / f'trading/strategies/portfolio_watch/{args.operation}.py'),
                                   *arguments], cwd=root, env=env).returncode
    except (SetupError, ValueError, OSError) as exc:
        print(f'hedgy: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
