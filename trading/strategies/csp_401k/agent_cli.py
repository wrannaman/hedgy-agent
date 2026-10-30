"""Small CLI adapter; both providers execute the same research runbook."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def settings(env):
    provider = env.get('AGENT_PROVIDER', 'claude')
    if provider not in ('claude', 'codex'):
        raise ValueError(f'Unsupported AGENT_PROVIDER={provider!r}; choose claude or codex')
    model = env.get('AGENT_MODEL') or env.get('CLAUDE_MODEL' if provider == 'claude' else 'CODEX_MODEL')
    if not model and provider == 'claude':
        model = 'claude-opus-5-5'
    binary = env.get('CLAUDE_BIN' if provider == 'claude' else 'CODEX_BIN') or provider
    return provider, binary, model


def command(env, prompt, probe=False, output=None):
    provider, binary, model = settings(env)
    if provider == 'claude':
        args = [binary, '--model', model]
        if not probe:
            args += ['--dangerously-skip-permissions']
        return args + ['-p', prompt]
    args = [binary]
    if not probe:
        args += ['--search']
    args += ['exec', '--sandbox', 'read-only' if probe else 'danger-full-access', '--color', 'never']
    if model:
        args += ['--model', model]
    if output:
        args += ['--output-last-message', str(output)]
    return args + [prompt]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('probe', 'run'))
    p.add_argument('prompt', nargs='?')
    a = p.parse_args()
    env = os.environ.copy()
    try:
        provider, _, _ = settings(env)
        if provider == 'codex':
            for key in ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY'):
                env.pop(key, None)
        if a.mode == 'run':
            if not a.prompt:
                p.error('run requires a prompt')
            args = command(env, a.prompt)
            os.execvpe(args[0], args, env)
        with tempfile.TemporaryDirectory(prefix='hedgy-agent-probe-') as tmp:
            output = Path(tmp) / 'last-message.txt'
            args = command(env, 'Without using tools, reply with exactly: PONG', probe=True, output=output)
            result = subprocess.run(args, env=env, capture_output=True, text=True)
            final = output.read_text().strip() if provider == 'codex' and output.exists() else result.stdout.strip()
            if result.returncode or final != 'PONG':
                print(result.stderr, file=sys.stderr, end='')
                print(final or 'Agent returned no final response', file=sys.stderr)
                return (128 - result.returncode) if result.returncode < 0 else (result.returncode or 1)
            print('PONG')
            return 0
    except (ValueError, OSError) as exc:
        print(f'Agent error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
