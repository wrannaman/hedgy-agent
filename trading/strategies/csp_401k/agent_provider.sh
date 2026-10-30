# Sourced after REPO_ROOT and the Python PATH are configured.
# Local config is ignored by Git; CLI authentication stays with each provider.
if [ -f "$REPO_ROOT/.env.agent" ]; then
  set -a
  source "$REPO_ROOT/.env.agent"
  set +a
fi
export AGENT_PROVIDER="${AGENT_PROVIDER:-claude}"
case "$AGENT_PROVIDER" in
  claude|codex) ;;
  *) echo "Unsupported AGENT_PROVIDER: choose claude or codex" >&2; exit 1 ;;
esac
if [ "$AGENT_PROVIDER" = codex ]; then
  AGENT_LABEL=Codex
  AGENT_MODEL="${AGENT_MODEL:-${CODEX_MODEL:-}}"
else
  AGENT_LABEL=Claude
  AGENT_MODEL="${AGENT_MODEL:-${CLAUDE_MODEL:-claude-opus-5-5}}"
fi
export AGENT_MODEL
AGENT_MODEL_LABEL="${AGENT_MODEL:-CLI default}"
AGENT_ADAPTER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agent_cli.py"
AGENT_PROBE_CMD=(python3 "$AGENT_ADAPTER" probe)
AGENT_RUN_CMD=(python3 "$AGENT_ADAPTER" run)

for value in "${AGENT_TIMEOUT:-1200}" "${AGENT_MAX_ATTEMPTS:-2}"; do
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "AGENT_TIMEOUT and AGENT_MAX_ATTEMPTS must be positive integers" >&2
    exit 1
  fi
done
