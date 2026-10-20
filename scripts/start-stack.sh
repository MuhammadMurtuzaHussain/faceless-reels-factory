#!/bin/sh
# Starts the local Reel Factory API and n8n (http://localhost:5678). Ctrl+C stops both.
set -e
. "$(dirname "$0")/stack-env.sh"
missing=""
[ -n "$TELEGRAM_BOT_TOKEN" ] || missing="$missing TELEGRAM_BOT_TOKEN"
[ -n "$TELEGRAM_CHAT_ID" ] || missing="$missing TELEGRAM_CHAT_ID"
[ -z "$missing" ] || echo "warning: .env is missing$missing, so Telegram messages will fail until you add them." >&2
.venv/bin/python -m reelfactory serve --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID $N8N_PID 2>/dev/null' EXIT INT TERM
sleep 1
curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null && echo "API up on 127.0.0.1:$API_PORT; dashboard at http://127.0.0.1:$API_PORT"
"$N8N" start &
N8N_PID=$!
# if either one stops, stop both and exit, so launchd (KeepAlive) starts the whole stack again
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$N8N_PID" 2>/dev/null; do sleep 5; done
echo "$(date '+%H:%M:%S') the API or n8n stopped; shutting the stack down" >&2
exit 1
