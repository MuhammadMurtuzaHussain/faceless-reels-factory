"""Local HTTP API for orchestration (n8n), bound to 127.0.0.1 and token-protected.

Every action returns the same response shape so one n8n sub-workflow can relay it:

    {"ok": bool, "reply": "<Telegram HTML>", "files": [{"kind": "...", "id": "...", "caption": "..."}], ...}

Files are fetched separately with GET /file?id=...&kind=... (kinds are a fixed
allow-list that map to project paths, so no arbitrary file can be read).

The same server hosts a small browser dashboard at GET / (see dashboard.py). Browsers
sign in once at /login with the API token and get an HttpOnly, SameSite=Strict session
cookie; the token itself never appears in a page or URL. Cookie-authenticated POSTs
must also carry the page's CSRF token in X-CSRF-Token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import traceback
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, budget, discover, review, voice
from .paths import Paths

log = logging.getLogger(__name__)
RENDER_LOCK = threading.Lock()
COMMAND_LOCK = threading.Lock()   # chat commands run strictly one after another, in arrival order

HELP = (
    "<b>Reel Factory commands</b>\n"
    "/shortlist: today's ideas\n"
    "/daily: fetch fresh ideas now\n"
    "/pick 2: start idea #2 and get its Claude brief (or /pick my-note.md from inbox/ideas)\n"
    "/inbox: voiceovers waiting\n"
    "/voice AI-…: make the voiceover with your ElevenLabs voice (<i>force</i> shows the cost of redoing it, "
    "<i>force yes</i> spends it)\n"
    "/render AI-…: render now (add <i>force</i> to redo an approved one)\n"
    "/approve AI-… [note]\n"
    "/reject AI-… [what to fix]\n"
    "/published AI-… https://www.instagram.com/reel/…\n"
    "/status: today's reels, credits left and recent jobs"
)


def file_for(paths: Paths, idea_id: str, kind: str) -> tuple[Path, str] | None:
    """Allow-listed downloadable files: (path, content type)."""
    if not idea_id or "/" in idea_id or ".." in idea_id:
        return None
    table = {
        "video": (paths.drafts / f"{idea_id}.mp4", "video/mp4"),
        "contact": (paths.drafts / f"{idea_id}.contact.jpg", "image/jpeg"),
        "cover": (paths.covers / f"{idea_id}.jpg", "image/jpeg"),
        "caption": (paths.drafts / f"{idea_id}.caption.txt", "text/plain; charset=utf-8"),
        "review": (paths.drafts / f"{idea_id}.review.md", "text/markdown; charset=utf-8"),
        "brief": (paths.scripts / f"{idea_id}.brief.md", "text/markdown; charset=utf-8"),
        "storyboard": (paths.storyboard(idea_id), "application/json"),
    }
    hit = table.get(kind)
    return hit if hit and hit[0].exists() else None


# ---------------------------------------------------------------- actions (pure functions, unit-tested)


def resp(reply: str, files: list | None = None, ok: bool = True, **extra) -> dict:
    if len(reply) > 3900:                      # Telegram's message limit is 4096 characters
        reply = reply[:3900].rsplit("\n", 1)[0] + "\n…"
    return {"ok": ok, "reply": reply, "files": files or [], **extra}


def act_daily(paths: Paths) -> dict:
    paths.ensure_dirs()
    stats = discover.discover(paths)
    discover.rank(paths)
    discover.shortlist(paths)
    r = act_shortlist(paths)
    head = f"☀️ <b>{stats['new']} new stories</b> from {stats['feeds'] - len(stats['failed'])}/{stats['feeds']} feeds\n\n"
    return resp(head + r["reply"], stats=stats, shortlist=r.get("shortlist"))


def act_shortlist(paths: Paths) -> dict:
    items = discover.latest_shortlist(paths)
    if not items:
        return resp("No shortlist yet. Send /daily.", ok=False)
    lines = [f"<b>Shortlist {escape(items[0]['date'])}</b>"]
    for it in items:
        star = "⭐ " if it["top"] else ""
        used = " <i>(picked)</i>" if it["status"] == "used" else ""
        lines.append(f"{star}<b>{it['rank']}.</b> <a href=\"{escape(it['url'], quote=True)}\">{escape(it['title'])}</a> "
                     f"· {escape(it['source'] or '')} · {it['score']:.0f}{used}")
    lines.append("\nReply <code>/pick N</code> to start one.")
    return resp("\n".join(lines), shortlist=items)


def act_pick(paths: Paths, pick: str) -> dict:
    try:
        idea_id, sb, brief = discover.new_idea(paths, pick)
    except SystemExit as e:
        return resp(f"⚠️ {escape(str(e))}", ok=False)
    step3 = ("3. That's it: your ElevenLabs voice speaks the script, then the Reel renders and arrives here."
             if voice.configured(paths) else
             f"3. Record the script and save it as <code>inbox/voiceovers/{idea_id}.m4a</code>.\n"
             f"The watcher renders it automatically and sends it here.")
    reply = (f"✍️ <b>{idea_id}</b> created.\n\n"
             f"1. In Claude Code run <code>/reel {idea_id}</code> (or paste the attached brief into Claude); "
             f"it researches, fact-checks and fills the storyboard.\n"
             f"2. Save the JSON as <code>data/scripts/{idea_id}.json</code>.\n" + step3)
    return resp(reply, [{"kind": "brief", "id": idea_id, "caption": f"Claude brief for {idea_id}"}], id=idea_id)


def act_inbox(paths: Paths) -> dict:
    items = review.inbox(paths)
    if not items:
        return resp("📭 Inbox is empty.", items=[])
    lines = ["<b>Voiceover inbox</b>"]
    for it in items:
        mark = "🟢 ready" if it["ready"] else f"⏸ {escape(it['reason'])}"
        lines.append(f"<code>{it['id']}</code>: {mark}")
    return resp("\n".join(lines), items=items)


def act_render(paths: Paths, idea_id: str, force: bool = False) -> dict:
    from .pipeline import JobError, render_idea   # local import: pipeline imports a lot
    if not RENDER_LOCK.acquire(blocking=False):
        return resp("⏳ Another render is running; try again in a minute.", ok=False, busy=True)
    handler = logging.FileHandler(paths.logs / f"{idea_id}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    logging.getLogger().addHandler(handler)
    try:
        paths.ensure_dirs()
        try:
            ok = render_idea(paths, idea_id, force=force)
        except JobError as e:
            return resp(f"⚠️ <b>{idea_id}</b> not rendered: {escape(str(e))}", ok=False, id=idea_id)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
        RENDER_LOCK.release()
    m = review.manifest(paths, idea_id) or {}
    if not ok:
        failed = [c for c in m.get("checks", []) if not c["ok"] and c["severity"] != "warn"]
        why = "; ".join(f"{c['name']}: {c['detail']}" for c in failed[:3]) or "see logs/" + idea_id + ".log"
        return resp(f"❌ <b>{idea_id}</b> failed: {escape(why)}\nFix it, then /render {idea_id}", ok=False, id=idea_id)
    t = m.get("timing", {})
    dur = m.get("voiceover", {}).get("duration", 0)
    warn = [c for c in m.get("checks", []) if not c["ok"]]
    reply = (f"🎬 <b>{escape(m.get('title', idea_id))}</b>\n<code>{idea_id}</code> · {dur:.1f}s voice · validation PASS"
             f" · script match {t.get('match_ratio')}\n"
             + (f"⚠️ {len(warn)} warning(s) in the review report\n" if warn else "")
             + f"\nCheck the claims in the review file, then:\n/approve {idea_id}\n/reject {idea_id} what to fix")
    cap = file_for(paths, idea_id, "caption")
    if cap:                                    # copy-ready Instagram caption (tap the block to copy it)
        reply += f"\n\n📝 <b>Caption</b>\n<pre>{escape(cap[0].read_text(encoding='utf-8').strip())}</pre>"
    files = [{"kind": "contact", "id": idea_id, "caption": f"{idea_id} contact sheet"},
             {"kind": "video", "id": idea_id, "caption": idea_id},
             {"kind": "cover", "id": idea_id, "caption": "Thumbnail: in Instagram, Edit cover → Add from camera roll"},
             {"kind": "caption", "id": idea_id, "caption": "Instagram caption"},
             {"kind": "review", "id": idea_id, "caption": "Review report + claims to verify"}]
    return resp(reply, files, id=idea_id)


def act_voice(paths: Paths, idea_id: str, force: bool = False, confirmed: bool = False) -> dict:
    """Voice a storyboard. A forced re-voice of an existing voiceover only quotes its cost until ``confirmed``."""
    if force and paths.find_voiceover(idea_id) and paths.storyboard(idea_id).exists():
        note = escape(budget.spend_note(paths, idea_id))
        if not confirmed:
            return resp(f"💸 Re-voicing <b>{idea_id}</b> replaces its voiceover. {note}\n"
                        f"To go ahead, send /voice {idea_id} force yes", id=idea_id, confirm=True)
    try:
        out = voice.synthesize(paths, idea_id, force)
    except voice.VoiceError as e:
        from . import db
        with db.connect(paths.db) as con:          # park it so the watcher doesn't retry (and re-bill) every minute
            row = db.get(con, idea_id)
            if row and row["status"] == "selected":
                db.set_status(con, idea_id, "failed", error=f"voice: {e}")
        return resp(f"⚠️ <b>{idea_id}</b> voiceover not made: {escape(str(e))}\nFix it, then /voice {idea_id}",
                    ok=False, id=idea_id)
    left = escape(budget.line(budget.summary(paths)))
    return resp(f"🎙 <b>{idea_id}</b> voiceover ready: <code>{out.name}</code>. Rendering next.\n{left}", id=idea_id)


def act_watch(paths: Paths) -> dict:
    """Voice the first filled-in storyboard, else render the first ready voiceover (one per call)."""
    if RENDER_LOCK.locked():
        return resp("", idle=True)
    ready = [i for i in review.inbox(paths) if i["ready"]]
    if not ready and voice.configured(paths):
        todo = voice.pending(paths)
        if todo:
            v = act_voice(paths, todo[0])
            if not v["ok"]:
                return {**v, "idle": False}
            ready = [i for i in review.inbox(paths) if i["ready"] and i["id"] == todo[0]]
    if not ready:
        return resp("", idle=True)
    return {**act_render(paths, ready[0]["id"]), "idle": False}


def act_approve(paths: Paths, idea_id: str, note: str | None) -> dict:
    r = review.approve(paths, idea_id, note)
    return resp(f"✅ <b>{idea_id}</b> approved and copied to <code>output/approved/{idea_id}/</code>.\n"
                f"Post it on Instagram yourself, then send:\n/published {idea_id} https://www.instagram.com/reel/…",
                [{"kind": "caption", "id": idea_id, "caption": "Instagram caption draft"}], **r)


def act_reject(paths: Paths, idea_id: str, note: str | None) -> dict:
    r = review.reject(paths, idea_id, note)
    return resp(f"↩️ <b>{idea_id}</b> rejected{': ' + escape(note) if note else ''}.\n"
                f"Update the storyboard or re-record; a new voiceover file is picked up automatically, "
                f"or send /render {idea_id}.", **r)


def act_published(paths: Paths, idea_id: str, url: str) -> dict:
    r = review.published(paths, idea_id, url)
    return resp(f"📣 <b>{idea_id}</b> logged as published.\nAdd views/likes later in <code>output/publish-log.csv</code>.", **r)


STATUS_ICON = {"rendered": "🎬", "approved": "✅", "published": "📣", "failed": "❌", "rejected": "↩️",
               "rendering": "⏳", "selected": "✍️"}


def act_status(paths: Paths) -> dict:
    todays = review.today(paths)
    lines = [f"<b>Today</b> · {len(todays)} of {review.DAILY_SLOTS} reels"]
    for r in todays:
        flag = f" ({escape(r['status'])})" if r["status"] in ("failed", "rejected", "rendering") else ""
        lines.append(f"<code>{r['id']}</code> {escape(r['stage'])}{flag}: {escape((r['title'] or '')[:50])}")
    lines += ["○ open slot"] * max(0, review.DAILY_SLOTS - len(todays))
    b = budget.summary(paths)
    lines.append("\n🎙 " + escape(budget.line(b)))
    ids = {r["id"] for r in todays}
    jobs = [j for j in review.jobs(paths, 12) if j["id"] not in ids]
    if jobs:
        lines.append("\n<b>Recent jobs</b>")
        lines += [f"{STATUS_ICON.get(j['status'], '•')} <code>{j['id']}</code> {escape(j['status'])}: "
                  f"{escape((j['title'] or '')[:50])}" for j in jobs]
    return resp("\n".join(lines), jobs=jobs, today=todays, budget=b)


def run_command(paths: Paths, text: str, chat_id: str | None = None, owner: str | None = None) -> dict:
    """Parse one chat command ('/pick 2', '/approve AI-… looks great') and run it.

    When ``chat_id`` is given (a Telegram message), it must equal ``owner`` (TELEGRAM_CHAT_ID),
    otherwise the message is ignored silently: strangers who find the bot cannot drive it.
    """
    if chat_id is not None:
        owner = owner if owner is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        if not owner or str(chat_id).strip() != str(owner).strip():
            log.warning("ignored message from chat %s (not the owner)", chat_id)
            return resp("", idle=True, ignored=True)
    if not (text or "").strip():
        return resp("", idle=True)
    parts = (text or "").strip().split(maxsplit=2)
    if not parts or not parts[0].startswith("/"):
        return resp(HELP)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else None
    rest = parts[2] if len(parts) > 2 else None
    try:
        if cmd in ("/start", "/help"):
            return resp(HELP)
        if cmd == "/daily":
            return act_daily(paths)
        if cmd == "/shortlist":
            return act_shortlist(paths)
        if cmd == "/pick" and arg:
            return act_pick(paths, arg)
        if cmd == "/inbox":
            return act_inbox(paths)
        if cmd == "/voice" and arg:
            words = (rest or "").strip().lower().split()
            return act_voice(paths, arg, force=words[:1] == ["force"], confirmed=words[1:2] == ["yes"])
        if cmd in ("/render", "/retry") and arg:
            return act_render(paths, arg, force=(rest or "").strip().lower() == "force")
        if cmd == "/approve" and arg:
            return act_approve(paths, arg, rest)
        if cmd == "/reject" and arg:
            return act_reject(paths, arg, rest)
        if cmd == "/published" and arg and rest:
            return act_published(paths, arg, rest.strip())
        if cmd == "/status":
            return act_status(paths)
    except ValueError as e:
        return resp(f"⚠️ {escape(str(e))}", ok=False)
    return resp("Unknown or incomplete command.\n\n" + HELP, ok=False)


def run_commands(paths: Paths, messages: list[dict], owner: str | None = None) -> dict:
    """Run a batch of chat messages sequentially (order matters: /approve before /published)."""
    results = []
    with COMMAND_LOCK:
        for m in messages:
            chat = m.get("chat_id")
            results.append(run_command(paths, m.get("text") or "", None if chat in (None, "") else str(chat), owner))
    return {"ok": True, "results": [r for r in results if not r.get("idle")]}


# ---------------------------------------------------------------- browser sessions (dashboard)

SESSION_COOKIE = "rf_session"
SESSION_MAX_AGE = 30 * 24 * 3600
FONT_RE = re.compile(r"^[A-Za-z0-9_-]+\.ttf$")


def _sign(token: str, purpose: str, msg: str) -> str:
    return hmac.new(token.encode(), f"{purpose}:{msg}".encode(), hashlib.sha256).hexdigest()


def new_session(token: str, now: float | None = None) -> str:
    """A signed, stateless session value: '<issued>.<nonce>.<hmac>'. Rotating the token logs everyone out."""
    body = f"{int(now if now is not None else time.time())}.{secrets.token_urlsafe(18)}"
    return f"{body}.{_sign(token, 'session', body)}"


def check_session(token: str, value: str, now: float | None = None) -> str | None:
    """The session id (issued.nonce) when ``value`` is a valid, unexpired session, else None."""
    try:
        issued, nonce, sig = value.split(".")
        age = (now if now is not None else time.time()) - int(issued)
    except ValueError:
        return None
    body = f"{issued}.{nonce}"
    if not token or not hmac.compare_digest(sig, _sign(token, "session", body)) or not 0 <= age < SESSION_MAX_AGE:
        return None
    return body


def csrf_for(token: str, session: str) -> str:
    return _sign(token, "csrf", session)


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """'bytes=a-b' -> inclusive (start, end) within ``size``; None when absent, unsupported or unsatisfiable."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or size <= 0 or (not m[1] and not m[2]):
        return None
    if m[1]:
        start, end = int(m[1]), int(m[2]) if m[2] else size - 1
    else:                                       # suffix range: the last N bytes
        start, end = max(0, size - int(m[2])), size - 1
    end = min(end, size - 1)
    return (start, end) if start <= end else None


# ---------------------------------------------------------------- HTTP layer


class Handler(BaseHTTPRequestHandler):
    server_version = f"reelfactory/{__version__}"
    paths: Paths
    token: str

    def log_message(self, fmt, *args):  # route through logging instead of stderr spam
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, ctype: str = "application/json", filename: str | None = None,
              headers: dict | None = None, inline: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'{"inline" if inline else "attachment"}; filename="{filename}"')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _html(self, code: int, page: str, nonce: str, headers: dict | None = None) -> None:
        csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
               "img-src 'self'; media-src 'self'; font-src 'self'; connect-src 'self'; form-action 'self'; "
               "base-uri 'none'; frame-ancestors 'none'")
        self._send(code, page.encode("utf-8"), "text/html; charset=utf-8",
                   headers={"Content-Security-Policy": csp, "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                            "Cache-Control": "no-store", **(headers or {})})

    def _redirect(self, where: str, headers: dict | None = None) -> None:
        self._send(303, b"", "text/plain", headers={"Location": where, "Cache-Control": "no-store", **(headers or {})})

    def _send_file(self, path: Path, ctype: str, inline: bool) -> None:
        """Serve one allow-listed file, honouring a single byte Range (Safari won't play <video> without it)."""
        if inline and ctype.startswith("text/markdown"):
            ctype = "text/plain; charset=utf-8"           # show briefs/reports in the tab instead of downloading
        size = path.stat().st_size
        extra = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-cache"}
        rng = self.headers.get("Range")
        if rng:
            span = parse_range(rng, size)
            if span is None:
                return self._send(416, b"", ctype, headers={"Content-Range": f"bytes */{size}"})
            start, end = span
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            return self._send(206, data, ctype, filename=path.name, inline=inline,
                              headers={**extra, "Content-Range": f"bytes {start}-{end}/{size}"})
        return self._send(200, path.read_bytes(), ctype, filename=path.name, inline=inline, headers=extra)

    # -- auth: the X-Reel-Token header (n8n, curl) or a dashboard session cookie (browsers)

    def _local_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def _host_ok(self) -> bool:
        """Browsers must address us by a loopback name; blocks DNS-rebinding pages that resolve to 127.0.0.1."""
        return self.headers.get("Host", "") in self._local_hosts()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in self._local_hosts()}

    def _header_auth(self) -> bool:
        got = self.headers.get("X-Reel-Token", "")
        return bool(self.token) and bool(got) and hmac.compare_digest(got, self.token)

    def _session(self) -> str | None:
        if not self._host_ok():
            return None
        # parsed by hand: other localhost apps (n8n on :5678 …) share this cookie jar, and one odd cookie
        # of theirs can make http.cookies drop the whole header
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and value:
                return check_session(self.token, value)
        return None

    def _auth(self) -> tuple[str | None, str | None]:
        """('header', None) | ('cookie', session id) | (None, None)."""
        if self._header_auth():
            return "header", None
        sess = self._session()
        return ("cookie", sess) if sess else (None, None)

    def _csrf_ok(self, sess: str) -> bool:
        got = self.headers.get("X-CSRF-Token", "")
        return bool(got) and self._origin_ok() and hmac.compare_digest(got, csrf_for(self.token, sess))

    def _cookie(self, value: str, max_age: int) -> dict:
        return {"Set-Cookie": f"{SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"}

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    # -- routes

    def _get_font(self, name: str) -> None:
        f = self.paths.fonts / name
        if not FONT_RE.match(name) or not f.is_file():
            return self._json(404, {"ok": False, "error": "no such font"})
        self._send(200, f.read_bytes(), "font/ttf", headers={"Cache-Control": "public, max-age=86400"})

    def _get_login(self) -> None:
        from . import dashboard
        if not self._host_ok():
            return self._json(403, {"ok": False, "error": "open the dashboard at http://127.0.0.1"})
        if self._session():
            return self._redirect("/")
        nonce = secrets.token_urlsafe(16)
        self._html(200, dashboard.login_page(nonce), nonce)

    def _post_login(self) -> None:
        from . import dashboard
        if not (self._host_ok() and self._origin_ok()):
            return self._json(403, {"ok": False, "error": "cross-site login refused"})
        n = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(min(n, 4096)).decode("utf-8", "replace")) if n else {}
        got = (form.get("token") or [""])[0].strip()
        if self.token and got and hmac.compare_digest(got, self.token):
            return self._redirect("/", self._cookie(new_session(self.token), SESSION_MAX_AGE))
        time.sleep(0.5)                                    # make guessing slow; the token is long and random anyway
        nonce = secrets.token_urlsafe(16)
        self._html(401, dashboard.login_page(nonce, "That token doesn't match REELFACTORY_API_TOKEN."), nonce)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/health":
            return self._json(200, {"ok": True, "version": __version__})
        if u.path == "/login":
            return self._get_login()
        if u.path.startswith("/fonts/"):                   # open-licensed (OFL) fonts for the login page and dashboard
            return self._get_font(u.path.removeprefix("/fonts/"))
        how, sess = self._auth()
        if how is None:
            if u.path == "/":
                return self._redirect("/login")
            return self._json(401, {"ok": False, "error": "missing or wrong X-Reel-Token (browsers: sign in at /login)"})
        try:
            if u.path == "/":
                from . import dashboard
                nonce = secrets.token_urlsafe(16)
                csrf = csrf_for(self.token, sess) if sess else ""
                return self._html(200, dashboard.dashboard_page(self.paths, nonce, csrf), nonce)
            if u.path == "/file":
                hit = file_for(self.paths, q.get("id", ""), q.get("kind", ""))
                if not hit:
                    return self._json(404, {"ok": False, "error": "no such file"})
                return self._send_file(hit[0], hit[1], inline=q.get("inline") == "1")
            routes = {"/shortlist": lambda: act_shortlist(self.paths), "/inbox": lambda: act_inbox(self.paths),
                      "/status": lambda: act_status(self.paths)}
            if u.path in routes:
                return self._json(200, routes[u.path]())
            return self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            log.error("GET %s failed: %s", u.path, traceback.format_exc())
            return self._json(500, {"ok": False, "error": str(e), "reply": f"⚠️ Server error: {escape(str(e))}"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/login":
            return self._post_login()
        how, sess = self._auth()
        if how is None:
            return self._json(401, {"ok": False, "error": "missing or wrong X-Reel-Token"})
        if how == "cookie" and not self._csrf_ok(sess):
            return self._json(403, {"ok": False, "error": "missing or wrong CSRF token; reload the dashboard"})
        try:
            if u.path == "/logout":
                return self._send(200, b'{"ok": true}', headers=self._cookie("", 0))
            b = self._body()
            if u.path == "/ui/command":                    # dashboard buttons: same parser as Telegram, same queue
                with COMMAND_LOCK:
                    return self._json(200, run_command(self.paths, b.get("text") or ""))
            if u.path == "/command":
                chat = b.get("chat_id")
                return self._json(200, run_command(self.paths, b.get("text") or "", None if chat in (None, "") else str(chat)))
            if u.path == "/commands":
                return self._json(200, run_commands(self.paths, b.get("messages") or []))
            if u.path == "/watch":
                return self._json(200, act_watch(self.paths))
            if u.path == "/daily":
                return self._json(200, act_daily(self.paths))
            return self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            log.error("POST %s failed: %s", u.path, traceback.format_exc())
            return self._json(500, {"ok": False, "error": str(e), "reply": f"⚠️ Server error: {escape(str(e))}"})


def make_server(paths: Paths, token: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the API only binds to localhost")
    if len(token) < 24:
        raise ValueError("REELFACTORY_API_TOKEN must be set (24+ characters); run scripts/setup-env.sh")
    handler = type("BoundHandler", (Handler,), {"paths": paths, "token": token})
    return ThreadingHTTPServer((host, port), handler)


def serve(paths: Paths, port: int = 8765) -> None:
    token = os.environ.get("REELFACTORY_API_TOKEN", "")
    srv = make_server(paths, token, port=port)
    log.info("Reel Factory API on http://127.0.0.1:%d (root %s); dashboard at http://127.0.0.1:%d/", port, paths.root, port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
