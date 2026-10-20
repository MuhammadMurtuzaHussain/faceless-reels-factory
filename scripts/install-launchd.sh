#!/bin/sh
# Runs the API + n8n stack in the background from login (no terminal needed).
#   sh scripts/install-launchd.sh            install (or reinstall) and start it
#   sh scripts/install-launchd.sh uninstall  stop it and remove it
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
LABEL=com.reelfactory.stack
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "$1" = "uninstall" ]; then
  rm -f "$DEST"
  echo "removed $LABEL; start the stack by hand with: sh scripts/start-stack.sh"
  exit 0
fi

case "$ROOT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "macOS blocks background jobs in $ROOT; move the project (e.g. to ~/Projects) first." >&2; exit 1;;
esac
NODE=$(command -v node || true)
[ -n "$NODE" ] || { echo "node not found on PATH (n8n needs it)" >&2; exit 1; }
PATH_FOR_JOB="$(dirname "$NODE"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__ROOT__|$ROOT|g" -e "s|__PATH__|$PATH_FOR_JOB|g" \
  "$ROOT/scripts/$LABEL.plist" > "$DEST"
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $LABEL: the stack starts at login and restarts if it stops (log: logs/stack.log)"
echo "dashboard http://127.0.0.1:8765 · n8n http://localhost:5678"
