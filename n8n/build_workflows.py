"""Generate the n8n workflows for the Reel Factory control panel.

    python n8n/build_workflows.py      # writes n8n/workflows/*.json

Design: n8n orchestrates (schedules, Telegram I/O); the Python API does the work
and returns {"reply": html, "files": [...]}. Every workflow ends in the same
"send to Telegram" chain. Secrets are read from the environment ($env), which
scripts/start-stack.sh loads from the git-ignored .env, so no token is stored
in these files or in n8n's database.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).parent / "workflows"
API = "={{ $env.REELFACTORY_API_URL }}"
TG = "={{ $env.TELEGRAM_API_BASE }}/bot{{ $env.TELEGRAM_BOT_TOKEN }}"
TOKEN_HEADER = {"parameters": [{"name": "X-Reel-Token", "value": "={{ $env.REELFACTORY_API_TOKEN }}"}]}


# Telegram calls retry briefly: some networks occasionally drop the connection to api.telegram.org
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
SEQUENTIAL = {"batching": {"batch": {"batchSize": 1, "batchInterval": 400}}}   # space out sends so Telegram keeps their order


def node(name, type_, version, pos, params, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"reelfactory/{name}")), "name": name,
            "type": f"n8n-nodes-base.{type_}", "typeVersion": version, "position": list(pos),
            "parameters": params, **extra}


def schedule(name, pos, rule):
    return node(name, "scheduleTrigger", 1.2, pos, {"rule": {"interval": [rule]}})


def api_post(name, pos, path, body_expr, timeout_ms):
    return node(name, "httpRequest", 4.2, pos, {
        "method": "POST", "url": f"{API}{path}", "sendHeaders": True, "headerParameters": TOKEN_HEADER,
        "sendBody": True, "specifyBody": "json", "jsonBody": body_expr,
        "options": {"timeout": timeout_ms, **SEQUENTIAL}})


def code(name, pos, js):
    return node(name, "code", 2, pos, {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js})


SEND_CHAIN_JS_MESSAGES = """// one Telegram message per API response that has text to say
return $input.all()
  .filter(i => !i.json.idle && i.json.reply)
  .map(i => ({ json: { text: i.json.reply } }));"""

SEND_CHAIN_JS_FILES = """// one item per attached file; choose the Telegram method by file kind
const methods = { contact: ['sendPhoto', 'photo'], video: ['sendVideo', 'video'] };  // cover goes as a file: full resolution
const out = [];
for (const i of $input.all()) {
  if (i.json.idle) continue;
  for (const f of (i.json.files || [])) {
    const [method, field] = methods[f.kind] || ['sendDocument', 'document'];
    out.push({ json: { ...f, method, field } });
  }
}
return out;"""


def send_chain(source: str, x: int, y: int) -> tuple[list, dict]:
    """Nodes + connections that relay an API response to Telegram (text, then files)."""
    nodes = [
        code("Messages to send", (x, y - 120), SEND_CHAIN_JS_MESSAGES),
        node("Telegram: send message", "httpRequest", 4.2, (x + 260, y - 120), {
            "method": "POST", "url": f"{TG}/sendMessage", "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ chat_id: $env.TELEGRAM_CHAT_ID, text: $json.text, parse_mode: 'HTML', "
                        "link_preview_options: { is_disabled: true } }) }}",
            "options": {"timeout": 30000, **SEQUENTIAL}}, **RETRY),
        code("Files to send", (x, y + 120), SEND_CHAIN_JS_FILES),
        node("Fetch file from API", "httpRequest", 4.2, (x + 260, y + 120), {
            "method": "GET", "url": f"{API}/file", "sendQuery": True,
            "queryParameters": {"parameters": [{"name": "id", "value": "={{ $json.id }}"},
                                               {"name": "kind", "value": "={{ $json.kind }}"}]},
            "sendHeaders": True, "headerParameters": TOKEN_HEADER,
            "options": {"timeout": 120000, **SEQUENTIAL,
                        "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}}),
        node("Telegram: send file", "httpRequest", 4.2, (x + 520, y + 120), {
            "method": "POST", "url": f"{TG}/{{{{ $('Files to send').item.json.method }}}}", "sendBody": True,
            "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": [
                {"name": "chat_id", "value": "={{ $env.TELEGRAM_CHAT_ID }}"},
                {"name": "caption", "value": "={{ $('Files to send').item.json.caption }}"},
                {"parameterType": "formBinaryData", "name": "={{ $('Files to send').item.json.field }}",
                 "inputDataFieldName": "data"}]},
            "options": {"timeout": 300000, **SEQUENTIAL}}, **RETRY),
    ]
    conns = {
        source: {"main": [[{"node": "Messages to send", "type": "main", "index": 0},
                           {"node": "Files to send", "type": "main", "index": 0}]]},
        "Messages to send": {"main": [[{"node": "Telegram: send message", "type": "main", "index": 0}]]},
        "Files to send": {"main": [[{"node": "Fetch file from API", "type": "main", "index": 0}]]},
        "Fetch file from API": {"main": [[{"node": "Telegram: send file", "type": "main", "index": 0}]]},
    }
    return nodes, conns


def workflow(wid, name, nodes, conns, quiet: bool):
    # Save every run: with "none", n8n 2.x leaves each successful run stuck as "running".
    # The DB stays small because scripts/stack-env.sh turns on pruning (48 h / 5,000 runs).
    settings = {"executionOrder": "v1", "saveManualExecutions": True, "saveDataErrorExecution": "all",
                "saveDataSuccessExecution": "all"}
    return {"id": wid, "name": name, "nodes": nodes, "connections": conns, "settings": settings,
            "active": False, "pinData": {}, "meta": {"templateCredsSetupCompleted": True},
            "tags": []}


def daily(hour: int = 8, minute: int = 0):
    trig = schedule("Every morning", (0, 0), {"field": "days", "daysInterval": 1, "triggerAtHour": hour,
                                              "triggerAtMinute": minute})
    call = api_post("Discover + shortlist", (240, 0), "/daily", "={{ JSON.stringify({}) }}", 300000)
    chain, conns = send_chain("Discover + shortlist", 520, 0)
    conns["Every morning"] = {"main": [[{"node": "Discover + shortlist", "type": "main", "index": 0}]]}
    return workflow("rfDailyShortlist", "Reel Factory · 1 Daily shortlist", [trig, call, *chain], conns, quiet=False)


def watcher():
    trig = schedule("Every minute", (0, 0), {"field": "minutes", "minutesInterval": 1})
    call = api_post("Render next voiceover", (240, 0), "/watch", "={{ JSON.stringify({}) }}", 900000)
    chain, conns = send_chain("Render next voiceover", 520, 0)
    conns["Every minute"] = {"main": [[{"node": "Render next voiceover", "type": "main", "index": 0}]]}
    return workflow("rfVoiceWatcher01", "Reel Factory · 2 Voiceover watcher", [trig, call, *chain], conns, quiet=True)


PARSE_UPDATES_JS = """// Telegram getUpdates -> ONE item holding all new messages in order, plus `ack`
// (= highest update_id + 1) so the next node confirms them with Telegram right away;
// confirmed updates are never delivered twice, even if runs overlap. The API then runs
// the messages strictly one after another (so '/approve' always lands before '/published').
const updates = $input.first().json.result || [];
if (!updates.length) return [];
const ack = Math.max(...updates.map(u => u.update_id)) + 1;
const messages = updates
  .sort((a, b) => a.update_id - b.update_id)
  .map(u => u.message || u.edited_message || {})
  .map(m => ({ text: typeof m.text === 'string' ? m.text : '', chat_id: m.chat ? String(m.chat.id) : '' }));
return [{ json: { ack, messages } }];"""

SPLIT_RESULTS_JS = """// one item per command result, keeping their order
return $input.first().json.results.map(r => ({ json: r }));"""


def commands():
    trig = schedule("Every 10 seconds", (0, 0), {"field": "seconds", "secondsInterval": 10})
    poll = node("Telegram: get messages", "httpRequest", 4.2, (220, 0), {
        "method": "GET", "url": f"{TG}/getUpdates", "sendQuery": True,
        "queryParameters": {"parameters": [{"name": "timeout", "value": "0"},
                                           {"name": "allowed_updates", "value": "[\"message\"]"}]},
        "options": {"timeout": 15000}}, **RETRY)
    parse = code("Messages in order", (440, 0), PARSE_UPDATES_JS)
    ack = node("Telegram: confirm received", "httpRequest", 4.2, (700, -160), {
        "method": "GET", "url": f"{TG}/getUpdates", "sendQuery": True,
        "queryParameters": {"parameters": [{"name": "offset", "value": "={{ $json.ack }}"},
                                           {"name": "limit", "value": "1"}, {"name": "timeout", "value": "0"}]},
        "options": {"timeout": 15000}}, executeOnce=True, **RETRY)
    run = api_post("Run commands in order", (700, 80), "/commands",
                   "={{ JSON.stringify({ messages: $json.messages }) }}", 1800000)
    split = code("One item per reply", (940, 80), SPLIT_RESULTS_JS)
    chain, conns = send_chain("One item per reply", 1180, 80)
    conns.update({
        "Every 10 seconds": {"main": [[{"node": "Telegram: get messages", "type": "main", "index": 0}]]},
        "Telegram: get messages": {"main": [[{"node": "Messages in order", "type": "main", "index": 0}]]},
        "Messages in order": {"main": [[{"node": "Telegram: confirm received", "type": "main", "index": 0},
                                        {"node": "Run commands in order", "type": "main", "index": 0}]]},
        "Run commands in order": {"main": [[{"node": "One item per reply", "type": "main", "index": 0}]]},
    })
    return workflow("rfTelegramCmds01", "Reel Factory · 3 Telegram commands", [trig, poll, parse, ack, run, split, *chain],
                    conns, quiet=True)


def main():
    OUT.mkdir(exist_ok=True)
    for wf in (daily(), watcher(), commands()):
        p = OUT / f"{wf['id']}.json"
        p.write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print(p)


if __name__ == "__main__":
    main()
