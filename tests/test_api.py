import json
import threading
import urllib.request

import pytest

from reelfactory import api, db, review


def seed(paths, status="rendered", voice=True, script="Real script here."):
    paths.storyboard("AI-20260101-001").write_text(json.dumps({"id": "AI-20260101-001", "title": "T", "script": script,
                                                                "scenes": []}))
    if voice:
        (paths.voiceovers / "AI-20260101-001.m4a").write_bytes(b"fake audio")
    for name in ("AI-20260101-001.mp4", "AI-20260101-001.caption.txt", "AI-20260101-001.contact.jpg"):
        (paths.drafts / name).write_bytes(b"x")
    with db.connect(paths.db) as con:
        db.upsert_idea(con, "AI-20260101-001", "T", status=status)


def test_inbox_rules(tmp_root):
    seed(tmp_root, status="selected")
    assert review.inbox(tmp_root)[0]["ready"] is True
    with db.connect(tmp_root.db) as con:      # same voice already rendered -> not ready again
        db.set_status(con, "AI-20260101-001", "failed", voice_sha1=review._sha1(tmp_root.voiceovers / "AI-20260101-001.m4a"))
    item = review.inbox(tmp_root)[0]
    assert item["ready"] is False and "already rendered" in item["reason"]
    seed(tmp_root, status="selected", script="WRITE THE SPOKEN SCRIPT HERE")
    assert "skeleton" in review.inbox(tmp_root)[0]["reason"]


def test_review_lifecycle(tmp_root):
    seed(tmp_root)
    r = api.run_command(tmp_root, "/approve AI-20260101-001 nice")
    assert r["ok"] and (tmp_root.root / "output/approved/AI-20260101-001/AI-20260101-001.mp4").exists()
    assert api.run_command(tmp_root, "/reject AI-20260101-001")["ok"] is False          # locked now
    bad = api.run_command(tmp_root, "/published AI-20260101-001 https://evil.example/x")
    assert bad["ok"] is False
    ok = api.run_command(tmp_root, "/published AI-20260101-001 https://www.instagram.com/reel/abc/")
    assert ok["ok"] and "publish-log.csv" in ok["log"]
    with db.connect(tmp_root.db) as con:
        assert db.get(con, "AI-20260101-001")["status"] == "published"
    assert "approved/published" not in api.run_command(tmp_root, "/status")["reply"]


def test_render_refuses_locked_video(tmp_root):
    seed(tmp_root, status="approved")
    r = api.run_command(tmp_root, "/render AI-20260101-001")
    assert r["ok"] is False and "protected" in r["reply"]


def test_only_owner_chat_is_obeyed(tmp_root):
    assert api.run_command(tmp_root, "/status", chat_id="999", owner="123")["ignored"] is True
    assert api.run_command(tmp_root, "/status", chat_id="123", owner="")["ignored"] is True   # unset -> ignore all
    assert api.run_command(tmp_root, "/help", chat_id="123", owner="123")["reply"].startswith("<b>Reel Factory")
    assert api.run_command(tmp_root, "", chat_id="123", owner="123")["idle"] is True


def test_file_allow_list(tmp_root):
    seed(tmp_root)
    assert api.file_for(tmp_root, "AI-20260101-001", "video")[1] == "video/mp4"
    assert api.file_for(tmp_root, "../../etc/passwd", "video") is None
    assert api.file_for(tmp_root, "AI-20260101-001", "anything") is None


def test_http_auth_and_routes(tmp_root):
    srv = api.make_server(tmp_root, "t" * 32, port=0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert json.load(urllib.request.urlopen(base + "/health"))["ok"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/status")
        assert e.value.code == 401
        req = urllib.request.Request(base + "/command", data=json.dumps({"text": "/help"}).encode(),
                                     headers={"X-Reel-Token": "t" * 32, "Content-Type": "application/json"})
        assert "Reel Factory commands" in json.load(urllib.request.urlopen(req))["reply"]
        req = urllib.request.Request(base + "/watch", data=b"{}", headers={"X-Reel-Token": "t" * 32})
        assert json.load(urllib.request.urlopen(req))["idle"] is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_server_refuses_weak_token_or_public_bind(tmp_root):
    with pytest.raises(ValueError):
        api.make_server(tmp_root, "short", port=0)
    with pytest.raises(ValueError):
        api.make_server(tmp_root, "t" * 32, host="0.0.0.0", port=0)


def test_commands_run_in_order(tmp_root):
    seed(tmp_root)
    out = api.run_commands(tmp_root, [
        {"text": "/approve AI-20260101-001", "chat_id": "7"},
        {"text": "/published AI-20260101-001 https://www.instagram.com/reel/x/", "chat_id": "7"},
        {"text": "/status", "chat_id": "666"},                       # stranger: dropped
    ], owner="7")
    assert [r["ok"] for r in out["results"]] == [True, True]
    assert "published" in out["results"][1]["reply"]


# ---------------------------------------------------------------- dashboard: sessions, CSRF, page

import http.client
import re
from contextlib import contextmanager

TOKEN = "t" * 32
ID = "AI-20260101-001"


@contextmanager
def running(paths):
    srv = api.make_server(paths, TOKEN, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def call(port, method, path, body=None, headers=None, host=None):
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    if isinstance(body, dict):
        body, h["Content-Type"] = json.dumps(body), "application/json"
    con.request(method, path, body=body, headers=h)
    r = con.getresponse()
    data = r.read()
    con.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def login(port):
    status, h, _ = call(port, "POST", "/login", body=f"token={TOKEN}",
                        headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://127.0.0.1:{port}"})
    assert status == 303 and h["location"] == "/"
    cookie = h["set-cookie"].split(";")[0]
    return cookie, h["set-cookie"]


def csrf_of(port, cookie):
    status, _, page = call(port, "GET", "/", headers={"Cookie": cookie})
    assert status == 200
    return re.search(r'<meta name="csrf" content="([0-9a-f]+)"', page.decode()).group(1)


def seed_shortlist(paths, title="Phones <b>listen</b> & learn"):
    with db.connect(paths.db) as con:
        db.upsert_idea(con, "RSS-1", title, source_url="https://example.com/a?x=1&y=2", source_name="Verge",
                       score=81.4, status="discovered")
    (paths.scripts / "shortlist-2026-01-01.json").write_text(json.dumps(["RSS-1"]))


def test_session_cookie_is_signed_and_expires():
    v = api.new_session(TOKEN, now=1000)
    assert TOKEN not in v
    sess = api.check_session(TOKEN, v, now=1001)
    assert sess and v.startswith(sess)
    assert api.check_session(TOKEN, v[:-1] + ("0" if v[-1] != "0" else "1"), now=1001) is None   # tampered
    assert api.check_session("u" * 32, v, now=1001) is None                                       # token rotated
    assert api.check_session(TOKEN, v, now=1000 + api.SESSION_MAX_AGE) is None                    # expired
    assert api.check_session(TOKEN, "garbage", now=1001) is None
    assert api.csrf_for(TOKEN, sess) != api.csrf_for(TOKEN, api.check_session(TOKEN, api.new_session(TOKEN, 1000), 1001))


def test_parse_range():
    assert api.parse_range("bytes=0-", 100) == (0, 99)
    assert api.parse_range("bytes=10-19", 100) == (10, 19)
    assert api.parse_range("bytes=-10", 100) == (90, 99)
    assert api.parse_range("bytes=50-500", 100) == (50, 99)
    assert api.parse_range("bytes=200-", 100) is None
    assert api.parse_range("bytes=1-2,5-6", 100) is None


def test_dashboard_login_sets_strict_httponly_cookie(tmp_root):
    with running(tmp_root) as port:
        status, h, _ = call(port, "GET", "/")
        assert status == 303 and h["location"] == "/login"
        status, h, page = call(port, "GET", "/login")
        assert status == 200 and b'name="token"' in page and TOKEN.encode() not in page
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["referrer-policy"] == "same-origin"         # 'no-referrer' would make the form POST send Origin: null
        status, h, page = call(port, "POST", "/login", body="token=wrong",
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert status == 401 and "set-cookie" not in h and b"doesn" in page
        cookie, raw = login(port)
        assert "HttpOnly" in raw and "SameSite=Strict" in raw and TOKEN not in raw
        status, _, _ = call(port, "GET", "/login", headers={"Cookie": cookie})
        assert status == 303                                     # already signed in
        status, _, body = call(port, "GET", "/status", headers={"Cookie": cookie})
        assert status == 200 and json.loads(body)["ok"]
        status, _, _ = call(port, "GET", "/status", headers={"Cookie": "rf_session=1.2.3"})
        assert status == 401
        # a DNS-rebinding page reaches 127.0.0.1 under its own Host name: the cookie is not honoured there
        status, _, _ = call(port, "GET", "/status", headers={"Cookie": cookie}, host="evil.example:80")
        assert status == 401
        status, _, _ = call(port, "POST", "/login", body=f"token={TOKEN}",
                            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"})
        assert status == 403


def test_dashboard_posts_need_csrf(tmp_root):
    seed(tmp_root)
    with running(tmp_root) as port:
        cookie, _ = login(port)
        csrf = csrf_of(port, cookie)
        cmd = {"text": f"/approve {ID} looks right"}
        assert call(port, "POST", "/ui/command", cmd, {"Cookie": cookie})[0] == 403
        assert call(port, "POST", "/ui/command", cmd, {"Cookie": cookie, "X-CSRF-Token": "0" * 64})[0] == 403
        assert call(port, "POST", "/ui/command", cmd, {"Cookie": cookie, "X-CSRF-Token": csrf,
                                                        "Origin": "https://evil.example"})[0] == 403
        assert call(port, "POST", "/command", {"text": "/status"}, {"Cookie": cookie})[0] == 403   # all POSTs
        with db.connect(tmp_root.db) as con:
            assert db.get(con, ID)["status"] == "rendered"
        status, _, body = call(port, "POST", "/ui/command", cmd, {"Cookie": cookie, "X-CSRF-Token": csrf,
                                                                   "Origin": f"http://127.0.0.1:{port}"})
        r = json.loads(body)
        assert status == 200 and r["ok"] and r["status"] == "approved"
        with db.connect(tmp_root.db) as con:
            assert db.get(con, ID)["status"] == "approved" and db.get(con, ID)["review_note"] == "looks right"
        # n8n keeps using the header token, no CSRF needed
        status, _, body = call(port, "POST", "/ui/command", {"text": "/status"}, {"X-Reel-Token": TOKEN})
        assert status == 200 and "Recent jobs" in json.loads(body)["reply"]
        status, h, _ = call(port, "POST", "/logout", {}, {"Cookie": cookie, "X-CSRF-Token": csrf})
        assert status == 200 and "Max-Age=0" in h["set-cookie"]


def test_dashboard_page_renders_sections(tmp_root):
    seed(tmp_root)
    seed_shortlist(tmp_root)
    with db.connect(tmp_root.db) as con:
        db.upsert_idea(con, "AI-20260101-002", "<script>alert(1)</script>", status="approved")
    with running(tmp_root) as port:
        cookie, _ = login(port)
        status, h, raw = call(port, "GET", "/", headers={"Cookie": cookie})
    page = raw.decode()
    assert status == 200 and h["content-type"].startswith("text/html")
    assert "script-src 'nonce-" in h["content-security-policy"] and h["cache-control"] == "no-store"
    assert TOKEN not in page
    # shortlist with a Pick button, HTML in titles escaped
    assert 'data-cmd="/pick 1"' in page and "Phones &lt;b&gt;listen&lt;/b&gt; &amp; learn" in page
    assert 'href="https://example.com/a?x=1&amp;y=2"' in page
    # inbox lists the voiceover; the rendered job has player, contact sheet and review buttons
    assert 'id="inbox"' in page and "AI-20260101-001.m4a" in page
    assert f'<video controls playsinline preload="metadata" src="/file?id={ID}&amp;kind=video">' in page
    assert f'src="/file?id={ID}&amp;kind=contact"' in page
    assert f'data-cmd="/approve {ID}"' in page and f'data-cmd="/reject {ID}"' in page
    # approved job offers "Mark published"; its hostile title is inert
    assert 'data-cmd="/published AI-20260101-002"' in page
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "https://fonts" not in page and "cdn" not in page.lower()
    assert ' style="' not in page                       # CSP allows only the nonce'd <style>, no style attributes


def test_header_token_still_sees_page_and_files(tmp_root):
    seed(tmp_root)
    (tmp_root.drafts / f"{ID}.mp4").write_bytes(bytes(range(100)))
    with running(tmp_root) as port:
        assert call(port, "GET", "/", headers={"X-Reel-Token": TOKEN})[0] == 200
        status, h, body = call(port, "GET", f"/file?id={ID}&kind=video", headers={"X-Reel-Token": TOKEN,
                                                                                 "Range": "bytes=10-19"})
        assert status == 206 and body == bytes(range(10, 20)) and h["content-range"] == "bytes 10-19/100"
        assert h["accept-ranges"] == "bytes"
        status, h, body = call(port, "GET", f"/file?id={ID}&kind=video", headers={"X-Reel-Token": TOKEN})
        assert status == 200 and len(body) == 100 and h["content-disposition"].startswith("attachment")
        assert call(port, "GET", f"/file?id={ID}&kind=video", headers={"X-Reel-Token": TOKEN,
                                                                       "Range": "bytes=500-"})[0] == 416
        status, h, _ = call(port, "GET", f"/file?id={ID}&kind=video&inline=1", headers={"X-Reel-Token": TOKEN})
        assert h["content-disposition"].startswith("inline")
        status, h, body = call(port, "GET", "/fonts/Inter-Medium.ttf")
        assert status == 200 and h["content-type"] == "font/ttf" and len(body) > 1000
        assert call(port, "GET", "/fonts/..%2Fconfig.ttf")[0] == 404
