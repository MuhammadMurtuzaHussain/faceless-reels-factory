#!/bin/sh
# (Re)generate the workflows and import + publish them into the local n8n.
# Run while n8n is stopped (or restart it afterwards).
set -e
. "$(dirname "$0")/stack-env.sh"
.venv/bin/python n8n/build_workflows.py >/dev/null
"$N8N" import:workflow --separate --input=n8n/workflows
for id in rfDailyShortlist rfVoiceWatcher01 rfTelegramCmds01; do
  "$N8N" publish:workflow --id="$id"
done
echo "Imported and published. Start everything with scripts/start-stack.sh"
