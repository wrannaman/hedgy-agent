"""Exercise CLI invocation and health checking with synthetic executables."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from strategies.csp_401k.agent_cli import command, settings

ADAPTER = Path(__file__).resolve().parents[1] / 'agent_cli.py'


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_probe_and_run_use_selected_cli_and_separate_final_output(tmp_path, provider):
    fake = tmp_path / 'fake-agent'
    fake.write_text('''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
args=sys.argv[1:]
Path(os.environ['CAPTURE']).write_text(json.dumps({'args':args,'claude_token_present':'CLAUDE_CODE_OAUTH_TOKEN' in os.environ}))
if '--output-last-message' in args:
 Path(args[args.index('--output-last-message')+1]).write_text(os.environ.get('FINAL','PONG'))
 print('progress and unrelated stdout')
else:
 print(os.environ.get('FINAL','PONG'))
sys.exit(int(os.environ.get('FAKE_EXIT','0')))
''')
    fake.chmod(0o755)
    capture = tmp_path / 'args.json'
    env = {**os.environ, 'AGENT_PROVIDER': provider, 'AGENT_MODEL': 'test-model',
           'CLAUDE_BIN': str(fake), 'CODEX_BIN': str(fake), 'CAPTURE': str(capture),
           'CLAUDE_CODE_OAUTH_TOKEN': 'synthetic'}
    result = subprocess.run([sys.executable, str(ADAPTER), 'probe'], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == 'PONG\n'
    data = json.loads(capture.read_text())
    assert 'test-model' in data['args']
    if provider == 'codex':
        assert not data['claude_token_present']
        assert 'read-only' in data['args']
    for final, code in [('not ready', '0'), ('PONG', '7')]:
        bad = subprocess.run([sys.executable, str(ADAPTER), 'probe'],
                             env={**env, 'FINAL': final, 'FAKE_EXIT': code}, capture_output=True)
        assert bad.returncode != 0
    run = subprocess.run([sys.executable, str(ADAPTER), 'run', 'synthetic task'], env=env, capture_output=True)
    assert run.returncode == 0
    args = json.loads(capture.read_text())['args']
    assert args[-1] == 'synthetic task'
    # Load the real shell configuration and invoke its probe command, as cron does.
    (tmp_path / '.env.agent').write_text(f'AGENT_PROVIDER={provider}\nAGENT_MODEL=from-local\n')
    loader = ADAPTER.with_name('agent_provider.sh')
    shell = subprocess.run(['bash', '-c', 'set -u; REPO_ROOT="$1"; source "$2"; "${AGENT_PROBE_CMD[@]}"',
                            'test', str(tmp_path), str(loader)], env=env, capture_output=True, text=True)
    assert shell.returncode == 0 and shell.stdout == 'PONG\n'
    assert 'from-local' in json.loads(capture.read_text())['args']
    assert ('danger-full-access' in args) if provider == 'codex' else ('--dangerously-skip-permissions' in args)


def test_defaults_overrides_and_unknown_provider():
    assert settings({}) == ('claude', 'claude', 'claude-opus-5-5')
    assert settings({'AGENT_PROVIDER': 'codex'}) == ('codex', 'codex', None)
    assert settings({'AGENT_PROVIDER': 'codex', 'CODEX_MODEL': 'chosen'})[2] == 'chosen'
    assert settings({'AGENT_MODEL': 'common', 'CLAUDE_MODEL': 'legacy'})[2] == 'common'
    with pytest.raises(ValueError, match='Unsupported'):
        command({'AGENT_PROVIDER': 'unknown'}, 'test')
