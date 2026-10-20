"""The local web dashboard: one server-rendered HTML page plus a login form.

Every button posts a chat command to POST /ui/command, which runs it through
``api.run_command`` exactly like a Telegram message, so behaviour never drifts.
Everything interpolated into HTML goes through ``escape``; the page loads nothing
from outside 127.0.0.1 (fonts come from assets/fonts via GET /fonts/<file>).
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from . import __version__, budget, discover, review
from .api import file_for
from .paths import Paths

FILE_KINDS = ("video", "contact", "cover", "caption", "review", "brief")
FONT_FILES = ("Fraunces72ptSoft-SemiBold.ttf", "Fraunces9ptSoft-Regular.ttf", "Inter-Regular.ttf",
              "Inter-Medium.ttf", "Inter-SemiBold.ttf")

STATUS_LABEL = {"selected": "writing", "rendering": "rendering", "rendered": "ready for review", "failed": "failed",
                "rejected": "rejected", "approved": "approved", "published": "published"}

CSS = """
@font-face{font-family:"RF Display";src:url(/fonts/Fraunces72ptSoft-SemiBold.ttf) format("truetype");font-weight:600}
@font-face{font-family:"RF Text";src:url(/fonts/Fraunces9ptSoft-Regular.ttf) format("truetype");font-weight:400}
@font-face{font-family:"RF Sans";src:url(/fonts/Inter-Regular.ttf) format("truetype");font-weight:400}
@font-face{font-family:"RF Sans";src:url(/fonts/Inter-Medium.ttf) format("truetype");font-weight:500}
@font-face{font-family:"RF Sans";src:url(/fonts/Inter-SemiBold.ttf) format("truetype");font-weight:600}
:root{--bg:#efece7;--card:#fbf8f3;--line:#e6dfd5;--chip:#f1ebe2;--ink:#2a211c;--muted:#857a70;--accent:#d97757;
  --accent-ink:#b85a3c;--sage:#7fa27f;--mustard:#d9a441;--slate:#6b86b3;--plum:#a2708f;--sand:#ecdcc6;
  --display:"RF Display",Georgia,serif;--text:"RF Text",Georgia,serif;--sans:"RF Sans",-apple-system,system-ui,sans-serif;
  color-scheme:light}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;min-height:100vh;background:linear-gradient(180deg,#efece7,#e4e0d9) fixed;color:var(--ink);font:400 15px/1.5 var(--sans);
  -webkit-font-smoothing:antialiased}
a{color:var(--ink);text-decoration-color:var(--line);text-underline-offset:3px}
a:hover{text-decoration-color:var(--accent)}
code,.mono{font:500 12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 64px}
header.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.brand h1{font:600 34px/1.05 var(--display);margin:0;letter-spacing:-.01em}
.brand h1 em{font-style:normal;color:var(--accent)}
.brand p{margin:6px 0 0;color:var(--muted);font:400 15px/1.4 var(--text)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:minmax(0,380px) minmax(0,1fr);gap:24px;align-items:start}
@media (max-width:900px){.grid{grid-template-columns:minmax(0,1fr)}}
.col{display:flex;flex-direction:column;gap:24px;min-width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:0 1px 2px rgba(90,70,54,.05),
  0 8px 24px -12px rgba(90,70,54,.18);padding:20px 20px 18px}
.card h2{font:600 21px/1.2 var(--display);margin:0 0 4px}
.card .sub{color:var(--muted);font-size:13px;margin:0 0 14px}
.label{font:600 11px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
ol.list,ul.list{list-style:none;margin:0;padding:0}
.list li{display:flex;gap:12px;align-items:flex-start;padding:11px 0;border-top:1px solid var(--line)}
.list li:first-child{border-top:0;padding-top:2px}
.rank{flex:0 0 24px;font:600 17px/1.3 var(--display);color:var(--muted)}
.rank.top{color:var(--accent)}
.grow{flex:1;min-width:0}
.title{font-weight:500;overflow-wrap:anywhere}
.meta{color:var(--muted);font-size:12.5px;margin-top:2px}
.state{margin-top:6px}
.btn{appearance:none;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;
  font:600 13px/1 var(--sans);padding:9px 14px;cursor:pointer;white-space:nowrap;transition:background .15s,border-color .15s}
.btn:hover{border-color:#d6cbbd;background:#fff}
.btn:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary:hover{background:var(--accent-ink);border-color:var(--accent-ink)}
.btn.quiet{background:transparent}
.btn:disabled{opacity:.5;cursor:default}
.btn.small{padding:7px 11px;font-size:12.5px}
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 10px;background:var(--chip);
  font:600 12px/1 var(--sans);color:var(--ink);white-space:nowrap}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--muted)}
.pill.rendered::before{background:var(--slate)}.pill.approved::before{background:var(--sage)}
.pill.published::before{background:var(--plum)}.pill.failed::before{background:var(--accent)}
.pill.rejected::before,.pill.rendering::before{background:var(--mustard)}
.pill.ready::before{background:var(--sage)}
.empty{color:var(--muted);font:400 15px/1.5 var(--text);margin:4px 0 2px}
.job{display:grid;grid-template-columns:200px minmax(0,1fr);gap:20px;padding:18px 0;border-top:1px solid var(--line)}
.job:first-of-type{border-top:0;padding-top:4px}
@media (max-width:620px){.job{grid-template-columns:minmax(0,1fr)}.job .media{max-width:240px}}
.media video,.media img.cover{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:12px;background:var(--chip);
  border:1px solid var(--line);display:block}
.media .ph{aspect-ratio:9/16;border-radius:12px;background:var(--chip);border:1px dashed #d6cbbd;display:flex;
  align-items:center;justify-content:center;color:var(--muted);font-size:12.5px;text-align:center;padding:12px}
.job h3{font:600 20px/1.2 var(--display);margin:0 0 6px;overflow-wrap:anywhere}
.job .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.job .facts{color:var(--muted);font-size:13px;margin:8px 0 0}
.job .note{margin:10px 0 0;padding:10px 12px;border-radius:10px;background:var(--chip);font-size:13.5px}
.job .note.err{background:#f6e1d8}
.contact{margin-top:14px}
.contact img{width:100%;border-radius:10px;border:1px solid var(--line);display:block}
.actions{display:flex;flex-direction:column;gap:8px;margin-top:14px}
.inline{display:flex;gap:8px;flex-wrap:wrap}
.inline input{flex:1;min-width:180px}
input[type=text],input[type=url],input[type=password]{font:400 14px/1.2 var(--sans);color:var(--ink);background:#fff;
  border:1px solid var(--line);border-radius:999px;padding:9px 14px}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
details summary{cursor:pointer;font-weight:600;font-size:13px;color:var(--muted)}
details pre{white-space:pre-wrap;overflow-wrap:anywhere;font:400 12.5px/1.5 ui-monospace,Menlo,monospace;
  background:var(--chip);border-radius:10px;padding:12px;margin:10px 0 0;max-height:360px;overflow:auto}
.links{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px}
#toast{position:sticky;top:12px;z-index:5;margin:0 0 20px;display:none}
#toast.show{display:block}
#toast .card{white-space:pre-line;border-left:4px solid var(--sage);padding:14px 16px 12px}
#toast.bad .card{border-left-color:var(--accent)}
#toast .x{float:right;margin:-4px -4px 0 8px}
#toast .files{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:13px;white-space:normal}
.busy{opacity:.6;pointer-events:none}
footer{margin-top:32px;color:var(--muted);font-size:12px;text-align:center}
#today{margin-bottom:24px}
#today .head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.slots{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:6px}
@media (max-width:900px){.slots{grid-template-columns:minmax(0,1fr)}}
.slot{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fff;min-width:0}
.slot.open{background:transparent;border-style:dashed;color:var(--muted);font:400 14px/1.5 var(--text)}
.slot .title{margin:4px 0 10px}
ol.stages{list-style:none;margin:0;padding:0;display:flex;gap:4px;flex-wrap:wrap}
.stages li{font:600 11px/1 var(--sans);padding:5px 8px;border-radius:999px;background:var(--chip);color:var(--muted)}
.stages li.done{background:var(--sand);color:var(--ink)}
.stages li.now{background:var(--accent);color:#fff}
.slot .flag{margin-top:8px}
.budget{min-width:240px;max-width:360px;font-size:13px;color:var(--muted)}
.budget meter{width:100%;height:10px;margin-top:6px}
.budget.low{color:var(--accent-ink)}
.login{max-width:420px;margin:12vh auto 0}
.login form{display:flex;flex-direction:column;gap:12px;margin-top:14px}
.login .err{color:var(--accent-ink);font-size:13.5px;margin:0}
"""

JS = r"""
(() => {
  const csrf = document.querySelector('meta[name="csrf"]').content;
  const toast = document.getElementById('toast');
  const ALLOWED = new Set(['B', 'STRONG', 'I', 'EM', 'CODE']);

  // Replies are Telegram HTML built server-side; keep only its few tags (and http(s) links) anyway.
  function clean(html) {
    const src = new DOMParser().parseFromString('<body>' + html, 'text/html').body;
    const out = document.createDocumentFragment();
    (function walk(from, to) {
      for (const n of from.childNodes) {
        if (n.nodeType === 3) { to.appendChild(document.createTextNode(n.textContent)); continue; }
        if (n.nodeType !== 1) continue;
        let el = null;
        if (ALLOWED.has(n.tagName)) el = document.createElement(n.tagName);
        else if (n.tagName === 'A' && /^https?:\/\//i.test(n.getAttribute('href') || '')) {
          el = document.createElement('a'); el.href = n.getAttribute('href');
          el.target = '_blank'; el.rel = 'noopener noreferrer';
        }
        if (el) { walk(n, el); to.appendChild(el); } else walk(n, to);
      }
    })(src, out);
    return out;
  }

  function show(reply, ok, files) {
    toast.className = 'show' + (ok ? '' : ' bad');
    const body = toast.querySelector('.body');
    body.replaceChildren(clean(reply || (ok ? 'Done.' : 'Something went wrong.')));
    const list = toast.querySelector('.files');
    list.replaceChildren();
    for (const f of files || []) {
      const a = document.createElement('a');
      a.href = '/file?' + new URLSearchParams({id: f.id, kind: f.kind, inline: '1'});
      a.target = '_blank'; a.rel = 'noopener';
      a.textContent = '↗ ' + (f.caption || f.kind);
      list.appendChild(a);
    }
    toast.scrollIntoView({block: 'nearest'});
  }

  async function refresh() {
    const r = await fetch('/', {credentials: 'same-origin', cache: 'no-store'});
    if (!r.ok) return;
    const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    const fresh = doc.getElementById('content');
    if (fresh) document.getElementById('content').replaceWith(fresh);
  }

  async function post(url, body) {
    const r = await fetch(url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(body || {})});
    if (r.status === 401) { location.href = '/login'; throw new Error('signed out'); }
    return r.json();
  }

  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('button[data-cmd]');
    if (btn) {
      let text = btn.dataset.cmd;
      if (btn.dataset.input) {
        const input = document.getElementById(btn.dataset.input);
        const v = (input && input.value || '').trim();
        if (btn.dataset.required && !v) { input.focus(); input.reportValidity && input.reportValidity(); return; }
        if (v) text += ' ' + v;
      }
      if (btn.dataset.confirm && !confirm(btn.dataset.confirm)) return;
      const scope = btn.closest('[data-scope]') || btn;
      const label = btn.textContent;
      btn.disabled = true; scope.classList.add('busy');
      if (btn.dataset.wait) btn.textContent = btn.dataset.wait;
      try {
        const res = await post('/ui/command', {text});
        show(res.reply, res.ok, res.files);
        if (res.ok) await refresh();          // on an error keep what was typed so it can be fixed
      } catch (e) {
        if (e.message !== 'signed out') show('⚠️ ' + e.message, false);
      } finally {
        btn.disabled = false; btn.textContent = label; scope.classList.remove('busy');
      }
      return;
    }
    if (ev.target.closest('#toast .x')) toast.className = '';
    if (ev.target.closest('#logout')) {
      await post('/logout').catch(() => {});
      location.href = '/login';
    }
  });
})();
"""


def _page(title: str, body: str, nonce: str, csrf: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="csrf" content="{escape(csrf, quote=True)}">'
            f'<title>{escape(title)}</title><style nonce="{nonce}">{CSS}</style></head>'
            f'<body>{body}</body></html>')


def login_page(nonce: str, error: str = "") -> str:
    err = f'<p class="err" role="alert">{escape(error)}</p>' if error else ""
    body = f"""<main class="wrap"><div class="login card">
<p class="label">Reel Factory</p>
<h2>Sign in to the dashboard</h2>
<p class="sub">Paste <code>REELFACTORY_API_TOKEN</code> from your <code>.env</code>. It is checked once and
never stored in the page; your browser keeps a session cookie instead.</p>
<form method="post" action="/login" autocomplete="off">
<input type="password" name="token" placeholder="API token" aria-label="API token" required autofocus>
{err}<button class="btn primary" type="submit">Sign in</button>
</form></div></main>"""
    return _page("Sign in · Reel Factory", body, nonce)


def _when(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%-d %b, %H:%M")
    except ValueError:
        return ts


def _read(paths: Paths, idea_id: str, kind: str, limit: int = 20000) -> str | None:
    hit = file_for(paths, idea_id, kind)
    if not hit:
        return None
    text = hit[0].read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= limit else text[:limit] + "\n…"


def _file_url(idea_id: str, kind: str, inline: bool = False) -> str:
    return escape(f"/file?id={idea_id}&kind={kind}" + ("&inline=1" if inline else ""), quote=True)


def _shortlist_card(items: list[dict]) -> str:
    if not items:
        rows = '<p class="empty">No shortlist yet. Fetch today\'s ideas to get one.</p>'
        date = ""
    else:
        date = f" · {escape(items[0]['date'])}"
        lis = []
        for it in items:
            picked = it["status"] == "used"
            btn = ('<span class="pill">picked</span>' if picked else
                   f'<button class="btn small" data-cmd="/pick {it["rank"]}" data-wait="Picking…">Pick</button>')
            source = escape(it["source"] or "")
            score = f"{it['score']:.0f}" if it["score"] is not None else "–"
            lis.append(f'<li data-scope><span class="rank{" top" if it["top"] else ""}">{it["rank"]}</span>'
                       f'<div class="grow"><div class="title"><a href="{escape(it["url"] or "#", quote=True)}" '
                       f'target="_blank" rel="noopener noreferrer">{escape(it["title"])}</a></div>'
                       f'<div class="meta">{"★ top pick · " if it["top"] else ""}{source} · score {score}</div></div>'
                       f'{btn}</li>')
        rows = f'<ol class="list">{"".join(lis)}</ol>'
    return (f'<section class="card" id="shortlist"><h2>Today\'s shortlist</h2>'
            f'<p class="sub">Ranked RSS ideas{date}. Pick one to create its storyboard and Claude brief.</p>{rows}</section>')


def _inbox_card(items: list[dict]) -> str:
    if not items:
        rows = ('<p class="empty">No voiceovers waiting.</p>'
                '<p class="meta">Save a recording as <code>inbox/voiceovers/&lt;ID&gt;.m4a</code>; the watcher renders it.</p>')
    else:
        lis = []
        for it in items:
            state = ('<span class="pill ready">ready to render</span>' if it["ready"]
                     else f'<span class="meta">{escape(it["reason"])}</span>')
            btn = (f'<button class="btn small" data-cmd="/render {escape(it["id"], quote=True)}" '
                   f'data-wait="Rendering…">Render</button>' if it["ready"] else "")
            lis.append(f'<li data-scope><div class="grow"><div class="title mono">{escape(it["id"])}</div>'
                       f'<div class="meta">{escape(it["voiceover"])}</div><div class="state">{state}</div></div>'
                       f'{btn}</li>')
        rows = f'<ul class="list">{"".join(lis)}</ul>'
    return (f'<section class="card" id="inbox"><h2>Voiceover inbox</h2>'
            f'<p class="sub">Recordings in <code>inbox/voiceovers/</code> and whether they will render.</p>{rows}</section>')


def _job_actions(j: dict) -> str:
    jid = escape(j["id"], quote=True)
    status = j["status"]
    out = []
    if status == "rendered":
        out.append(f'<div class="inline"><button class="btn primary" data-cmd="/approve {jid}" data-input="note-{jid}" '
                   f'data-confirm="Approve {jid}? It is copied to output/approved/ and locked." '
                   f'data-wait="Approving…">Approve</button>'
                   f'<button class="btn" data-cmd="/reject {jid}" data-input="note-{jid}" data-wait="Rejecting…">Reject</button>'
                   f'<input type="text" id="note-{jid}" placeholder="Note (optional): what to fix, or why it is good" '
                   f'aria-label="Review note for {jid}" maxlength="500"></div>')
    elif status in ("failed", "rejected", "selected") and j["files"].get("voiceover"):
        out.append(f'<div class="inline"><button class="btn" data-cmd="/render {jid}" data-wait="Rendering…">'
                   f'Render again</button></div>')
    if status == "approved":
        out.append(f'<div class="inline"><input type="url" id="url-{jid}" required '
                   f'placeholder="https://www.instagram.com/reel/…" aria-label="Instagram URL for {jid}">'
                   f'<button class="btn primary" data-cmd="/published {jid}" data-input="url-{jid}" data-required="1" '
                   f'data-wait="Saving…">Mark published</button></div>')
    return f'<div class="actions">{"".join(out)}</div>' if out else ""


def _job(paths: Paths, j: dict) -> str:
    jid = j["id"]
    files = j["files"]
    if files["video"]:
        poster = f' poster="{_file_url(jid, "cover")}"' if files["cover"] else ""
        media = (f'<video controls playsinline preload="metadata"{poster} src="{_file_url(jid, "video")}">'
                 f'</video>')
    elif files["cover"]:
        media = f'<img class="cover" src="{_file_url(jid, "cover")}" alt="Cover for {escape(jid, quote=True)}">'
    else:
        media = f'<div class="ph">{"Rendering…" if j["status"] == "rendering" else "No video yet"}</div>'
    m = review.manifest(paths, jid) or {}
    facts = [f"<code>{escape(jid)}</code>"]
    dur = (m.get("voiceover") or {}).get("duration")
    if dur:
        facts.append(f"{dur:.1f}s")
    if m.get("validation"):
        facts.append(f"validation {escape(str(m['validation']))}")
    warn = [c for c in m.get("checks", []) if not c.get("ok")]
    if warn:
        facts.append(f"{len(warn)} warning{'s' if len(warn) != 1 else ''}")
    if j.get("attempts"):
        facts.append(f"{j['attempts']} attempt{'s' if j['attempts'] != 1 else ''}")
    facts.append(escape(_when(j.get("updated_at"))))
    notes = ""
    if j.get("error") and j["status"] == "failed":
        notes += f'<p class="note err">{escape(j["error"])}</p>'
    if j.get("review_note"):
        notes += f'<p class="note"><span class="label">Note</span><br>{escape(j["review_note"])}</p>'
    if j.get("post_url"):
        notes += (f'<p class="note">Published: <a href="{escape(j["post_url"], quote=True)}" target="_blank" '
                  f'rel="noopener noreferrer">{escape(j["post_url"])}</a></p>')
    contact = (f'<div class="contact"><img src="{_file_url(jid, "contact")}" alt="Contact sheet for '
               f'{escape(jid, quote=True)}" loading="lazy"></div>' if files["contact"] else "")
    details = ""
    review_md = _read(paths, jid, "review")
    if review_md:
        details += f'<details><summary>Review report and claims to verify</summary><pre>{escape(review_md)}</pre></details>'
    caption = _read(paths, jid, "caption")
    if caption:
        details += f'<details><summary>Instagram caption draft</summary><pre>{escape(caption)}</pre></details>'
    links = [f'<a href="{_file_url(jid, k, inline=True)}" target="_blank" rel="noopener">{label}</a>'
             for k, label in (("video", "Open video"), ("brief", "Claude brief"), ("caption", "Caption .txt"))
             if files[k]]
    status = j["status"]
    return (f'<article class="job" data-scope id="job-{escape(jid, quote=True)}"><div class="media">{media}</div>'
            f'<div class="info"><div class="row"><span class="pill {escape(status, quote=True)}">'
            f'{escape(STATUS_LABEL.get(status, status))}</span></div>'
            f'<h3>{escape(j["title"] or jid)}</h3><p class="facts">{" · ".join(facts)}</p>{notes}'
            f'{_job_actions(j)}{contact}{details}'
            f'{"<div class=links>" + "".join(links) + "</div>" if links else ""}</div></article>')


def _jobs_card(paths: Paths, jobs: list[dict]) -> str:
    if not jobs:
        body = '<p class="empty">No jobs yet. Pick an idea from the shortlist to start one.</p>'
    else:
        body = "".join(_job(paths, j) for j in jobs)
    return (f'<section class="card" id="jobs"><h2>Recent jobs</h2>'
            f'<p class="sub">Watch the draft, check the claims, then approve or send it back.</p>{body}</section>')


def _budget(b: dict) -> str:
    if b["limit"] is None:
        return (f'<div class="budget"><span class="label">ElevenLabs · {escape(b["month"])}</span><br>'
                f'{b["used"]:,} characters used. Set <code>voice.monthly_characters</code> in style.json to '
                f'see what is left.</div>')
    low = b["left"] < 3 * 500                     # under about three voiceovers left
    return (f'<div class="budget{" low" if low else ""}"><span class="label">ElevenLabs · {escape(b["month"])}</span><br>'
            f'{b["used"]:,} of {b["limit"]:,} characters used · <b>{max(b["left"], 0):,} left</b>'
            f'<meter min="0" max="{b["limit"]}" low="{int(b["limit"] * 0.7)}" high="{int(b["limit"] * 0.9)}" '
            f'optimum="0" value="{min(b["used"], b["limit"])}" aria-label="ElevenLabs characters used"></meter></div>')


def _slot(paths: Paths, r: dict) -> str:
    rid = r["id"]
    now = review.STAGES.index(r["stage"])
    steps = "".join(f'<li class="{"now" if k == now else "done" if k < now else ""}">{name}</li>'
                    for k, name in enumerate(review.STAGES))
    flag = ""
    if r["status"] in ("failed", "rejected", "rendering"):
        flag = f'<div class="flag"><span class="pill {r["status"]}">{escape(STATUS_LABEL[r["status"]])}</span></div>'
    if r["status"] == "failed" and r.get("error"):
        flag += f'<p class="meta">{escape(r["error"][:200])}</p>'
    j = {**r, "files": {"voiceover": paths.find_voiceover(rid) is not None}}
    return (f'<div class="slot" data-scope id="slot-{escape(rid, quote=True)}"><div class="mono">{escape(rid)}</div>'
            f'<div class="title">{escape(r["title"] or rid)}</div><ol class="stages">{steps}</ol>{flag}'
            f'{_job_actions(j)}</div>')


def _today_card(paths: Paths, todays: list[dict], b: dict) -> str:
    slots = [_slot(paths, r) for r in todays]
    slots += ['<div class="slot open">Open slot. Pick an idea from the shortlist, or drop a note in '
              '<code>inbox/ideas/</code>.</div>'] * max(0, review.DAILY_SLOTS - len(todays))
    return (f'<section class="card" id="today"><div class="head"><div><h2>Today</h2>'
            f'<p class="sub">{len(todays)} of {review.DAILY_SLOTS} reels · {escape(datetime.now().strftime("%A %-d %B"))}'
            f'</p></div>{_budget(b)}</div><div class="slots">{"".join(slots)}</div></section>')


def gather_jobs(paths: Paths, limit: int = 12) -> list[dict]:
    jobs = review.jobs(paths, limit)
    for j in jobs:
        j["files"] = {k: file_for(paths, j["id"], k) is not None for k in FILE_KINDS}
        j["files"]["voiceover"] = paths.find_voiceover(j["id"]) is not None
    return jobs


def dashboard_page(paths: Paths, nonce: str, csrf: str) -> str:
    content = (f'<div id="content">{_today_card(paths, review.today(paths), budget.summary(paths))}'
               f'<div class="grid"><div class="col">{_shortlist_card(discover.latest_shortlist(paths))}'
               f'{_inbox_card(review.inbox(paths))}</div>'
               f'<div class="col">{_jobs_card(paths, gather_jobs(paths))}</div></div></div>')
    body = f"""<div class="wrap">
<header class="top"><div class="brand"><h1>Reel <em>Factory</em></h1>
<p>Ideas in, calm Reels out. Same commands as the Telegram bot.</p></div>
<div class="toolbar" data-scope>
<button class="btn" data-cmd="/daily" data-wait="Fetching feeds…">Fetch fresh ideas</button>
<button class="btn quiet" id="logout" type="button">Sign out</button></div></header>
<div id="toast" role="status" aria-live="polite"><div class="card"><button class="btn small quiet x" type="button"
aria-label="Dismiss">✕</button><div class="body"></div><div class="files"></div></div></div>
{content}
<footer>reelfactory {escape(__version__)} · local only, 127.0.0.1 · nothing is posted automatically</footer>
</div><script nonce="{nonce}">{JS}</script>"""
    return _page("Reel Factory", body, nonce, csrf)
