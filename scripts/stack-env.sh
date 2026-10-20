# Shared environment for the n8n + API stack. Sourced by the other scripts.
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
ENV_FILE="${REELFACTORY_ENV_FILE:-$ROOT/.env}"
if [ ! -f "$ENV_FILE" ]; then echo "No $ENV_FILE yet: run scripts/setup-env.sh first." >&2; exit 1; fi
set -a; . "$ENV_FILE"; set +a
export REELFACTORY_ROOT="${REELFACTORY_ROOT:-$ROOT}"
export N8N_USER_FOLDER="${N8N_USER_FOLDER:-$ROOT/n8n/data}"
export N8N_PORT="${N8N_PORT:-5678}" N8N_LISTEN_ADDRESS=127.0.0.1 N8N_HOST=localhost
# workflows read secrets via $env, so env access must be allowed (this n8n is local-only)
export N8N_BLOCK_ENV_ACCESS_IN_NODE=false
# keep run history for 2 days (the command poller runs every 10 s)
export EXECUTIONS_DATA_PRUNE=true EXECUTIONS_DATA_MAX_AGE=48 EXECUTIONS_DATA_PRUNE_MAX_COUNT=5000
export N8N_DIAGNOSTICS_ENABLED=false N8N_PERSONALIZATION_ENABLED=false N8N_VERSION_NOTIFICATIONS_ENABLED=false
export GENERIC_TIMEZONE="${GENERIC_TIMEZONE:-$(readlink /etc/localtime | sed 's|.*zoneinfo/||')}"
export TZ="$GENERIC_TIMEZONE"
API_PORT=$(printf '%s' "${REELFACTORY_API_URL:-http://127.0.0.1:8765}" | sed 's|.*:||; s|/.*||')
N8N="$ROOT/n8n/node_modules/.bin/n8n"
