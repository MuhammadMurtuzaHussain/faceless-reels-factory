"""Command-line entry point: ``python -m reelfactory <command>``."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, audio, cta, db, elmusic, music, render, svg, timing, validate, voice as voicemod
from . import timeline as tlmod
from .paths import Paths, load_json, load_style, style_for

log = logging.getLogger("reelfactory")


def setup_logging(paths: Paths, idea_id: str | None = None, verbose: bool = False) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    paths.logs.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(paths.logs / f"{idea_id or 'reelfactory'}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)


class JobError(Exception):
    """A failure with a message meant for the user."""


# ---------------------------------------------------------------- helpers


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tool_version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return "unavailable"


def caption_text(sb: dict) -> str:
    c = sb.get("caption", {})
    parts = [c.get("hook", sb["title"]), "", c.get("body", ""), "", c.get("cta", "")]
    if sb.get("sources"):
        parts += ["", "Sources:"] + [f"• {s.get('title', '')} {s['url']}".strip() for s in sb["sources"]]
    parts += ["", " ".join(c.get("hashtags", []))]
    return "\n".join(parts).strip() + "\n"


def timeline_json(tl: tlmod.Timeline) -> dict:
    return {
        "duration": tl.duration, "voice_duration": tl.voice_duration,
        "scenes": [{"type": s.type, "start": round(s.start, 3), "end": round(s.end, 3), "params": s.params}
                   for s in tl.scenes],
        "captions": [{"text": " ".join(c.display), "start": round(c.start, 3), "end": round(c.end, 3)} for c in tl.chunks],
        "sfx": [{"t": round(t, 3), "kind": k} for t, k in tl.sfx],
        "warnings": tl.warnings,
    }


def with_cta(sb: dict, style: dict, voice: Path) -> tuple[str, dict]:
    """(script the voice speaks, storyboard with the CTA end card appended)."""
    spoken = voicemod.spoke_cta(voice)
    end = cta.scene(sb, style, spoken)
    if end is None:
        return sb["script"], sb
    script = cta.spoken_script(sb, style) if spoken else sb["script"]
    return script, {**sb, "scenes": [*sb["scenes"], end]}


def required_assets(paths: Paths, style: dict) -> list[Path]:
    return [paths.fonts / f["file"] for f in style["fonts"].values()] + [paths.fontconfig]


# ---------------------------------------------------------------- render job


def prepare_voice(voice: Path, work: Path, style: dict) -> tuple[Path, dict | None]:
    """Optionally trim dead air / long pauses, then improve clarity; returns the voice file to use."""
    edit: dict = {}
    cur = voice
    tcfg = style["audio"].get("tighten", {})
    if tcfg.get("enabled"):
        cur_out = work / "voice_tight.wav"
        edit["tighten"] = audio.tighten_voice(cur, cur_out, tcfg)
        cur = cur_out
        log.info("voice tightened %.2fs -> %.2fs (%d cuts)", edit["tighten"]["original_duration"],
                 edit["tighten"]["tightened_duration"], len(edit["tighten"]["removed"]))
    ecfg = style["audio"].get("enhance", {})
    if ecfg.get("enabled") and not voicemod.is_synthetic(voice):   # studio-clean TTS needs no denoise/EQ
        cur_out = work / "voice_clear.wav"
        edit["enhance"] = audio.enhance_voice(cur, cur_out, ecfg)
        cur = cur_out
        b, a = edit["enhance"]["before"], edit["enhance"]["after"]
        log.info("voice clarity (%s): 2-4 kHz %.1f -> %.1f dB, high-band SNR %.1f -> %.1f dB", edit["enhance"]["preset"],
                 b["clarity_2k_4k"], a["clarity_2k_4k"], b["hi_snr_db"], a["hi_snr_db"])
    return cur, (edit or None)


def prepare_music(paths: Paths, idea_id: str, style: dict, duration: float, work: Path) -> tuple[Path | None, dict | None]:
    """Background music: an original generated bed (default), a licensed file you supply, or none."""
    mcfg = style["audio"].get("music") or {}
    source = mcfg.get("source", "off")
    if source == "elevenlabs":
        track = elmusic.pick(paths, idea_id)
        if track:
            log.info("music: Eleven Music track %s", track.name)
            return track, elmusic.info(paths, track)
        log.warning("music: Eleven Music library is empty (run `music-library`); using the generated bed")
        source = "generated"
    if source == "generated":
        sig, info = music.generate_bed(duration, key=idea_id, mood=mcfg.get("mood"), bpm=mcfg.get("bpm"),
                                       drums=mcfg.get("drums", True))
        out = work / "music.wav"
        audio.write_wav(out, sig)
        log.info("music: generated %s bed at %.0f bpm", info["mood"], info["bpm"])
        return out, {**info, "license": "Original, synthesized locally by reelfactory/music.py"}
    if source == "file":
        f = paths.music / (mcfg.get("file") or "")
        if not mcfg.get("file") or not f.exists():
            raise JobError(f"music source is 'file' but {f} is missing")
        return f, {"file": str(f), "license": "USER MUST CONFIRM LICENSE (e.g. Pixabay Content License)"}
    return None, None


def render_idea(paths: Paths, idea_id: str, voice: Path | None = None, workers: int | None = None,
                keep_frames: bool = False, force: bool = False) -> bool:
    paths.ensure_dirs()
    style = load_style(paths)
    svg.set_font_dir(paths.fonts)
    sb_path = paths.storyboard(idea_id)
    if not sb_path.exists():
        raise JobError(f"storyboard not found: {sb_path}")
    sb = load_json(sb_path)
    style = style_for(style, sb)
    voice = voice or paths.find_voiceover(idea_id)
    if voice is None:
        raise JobError(f"no voiceover found. Record it and save as {paths.voiceovers / (idea_id + '.m4a')} "
                       f"(or .wav/.mp3/.aiff)")
    missing = [p for p in required_assets(paths, style) if not p.exists()]
    if missing:
        raise JobError(f"missing assets: {', '.join(map(str, missing))}")
    bad_fonts = [role for role, ok in render.font_check(paths, style).items() if not ok]
    if bad_fonts:
        raise JobError(f"fonts not picked up by rsvg-convert (would silently fall back): {', '.join(bad_fonts)}")
    if sb["script"].startswith("WRITE THE SPOKEN SCRIPT"):
        raise JobError(f"storyboard {sb_path.name} is still the skeleton; fill in the script and scenes first")

    voice_sha = sha1(voice)
    with db.connect(paths.db) as con:
        row = db.get(con, idea_id)
        if row and row["status"] in db.LOCKED and not force:
            raise JobError(f"{idea_id} is {row['status']}; its video is protected (use --force to re-render anyway)")
        db.upsert_idea(con, idea_id, sb["title"], script_path=str(sb_path), voiceover_path=str(voice),
                       voice_sha1=voice_sha)
        db.set_status(con, idea_id, "rendering", bump_attempt=True)

    t0 = time.time()
    work = paths.work / idea_id
    work.mkdir(parents=True, exist_ok=True)
    try:
        voice_used, edit = prepare_voice(voice, work, style)
        log.info("timing words for %s (%s)", idea_id, voice.name)
        spoken, sb_tl = with_cta(sb, style, voice)
        words, tinfo = timing.time_words(spoken, voice_used, paths.whisper_model)
        log.info("timing via %s, match ratio %s, voice %.2fs", tinfo["method"], tinfo.get("match_ratio"), tinfo["duration"])
        tl = tlmod.build(sb_tl, words, tinfo["duration"], style)
        (work / "timeline.json").write_text(json.dumps(timeline_json(tl), indent=2))
        (work / "words.json").write_text(json.dumps([w.to_dict() for w in words], indent=1))

        log.info("mixing audio")
        sfx = audio.ensure_sfx(paths.sfx)
        sfx_track = audio.build_sfx_track(tl.sfx, tl.duration, sfx, work / "sfx.wav")
        music_path, music_info = prepare_music(paths, idea_id, style, tl.duration, work)
        mix = audio.mix(voice_used, sfx_track, work / "mix.wav", tl.duration, style["audio"], music_path)

        log.info("rendering %.2fs at %d fps", tl.duration, style["fps"])
        frames = work / "frames"
        render.render_frames(tl, style, paths, frames, workers)
        mp4 = render.encode(frames, mix, paths.drafts / f"{idea_id}.mp4", style["fps"], tl.duration)
        cover = render.thumbnail(render.thumbnail_params(sb), style, paths, paths.covers / f"{idea_id}.jpg")
        cap_path = paths.drafts / f"{idea_id}.caption.txt"
        cap_path.write_text(caption_text(sb), encoding="utf-8")
        contact = render.contact_sheet(mp4, [s.start + s.dur * 0.6 for s in tl.scenes],
                                       paths.drafts / f"{idea_id}.contact.jpg")

        log.info("validating")
        checks = validate.validate_video(mp4, style, tl.duration, tl, required_assets(paths, style))
        ok = validate.passed(checks)
        report = paths.drafts / f"{idea_id}.review.md"
        report.write_text(validate.report_md(idea_id, checks, {**tinfo, "claims": sb.get("claims", []),
                                                                "sources": sb.get("sources", [])}), encoding="utf-8")
        manifest = {
            "id": idea_id, "title": sb["title"], "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "render_seconds": round(time.time() - t0, 1), "validation": "PASS" if ok else "FAIL",
            "duration": round(tl.duration, 3),
            "outputs": {"video": str(mp4), "cover": str(cover), "caption": str(cap_path), "review": str(report),
                        "contact_sheet": str(contact)},
            "voiceover": {"path": str(voice), "sha1": voice_sha, "duration": tinfo["duration"], "edit": edit},
            "timing": {k: v for k, v in tinfo.items() if k != "duration"},
            "claims": sb.get("claims", []), "sources": sb.get("sources", []),
            "assets": {
                "graphics": "Original SVG motion graphics generated by reelfactory/scenes.py",
                "sfx": "Original, synthesized locally by reelfactory/audio.py",
                "fonts": [{"file": f["file"], "license": "SIL Open Font License 1.1"} for f in style["fonts"].values()],
                "music": music_info,
                "third_party_footage": None,
            },
            "tools": {"reelfactory": __version__, "ffmpeg": tool_version(["ffmpeg", "-version"]),
                      "rsvg-convert": tool_version(["rsvg-convert", "--version"]),
                      "whisper_model": paths.whisper_model.name if paths.whisper_model.exists() else None},
            "style": style["name"] + (f" / {sb.get('theme') or 'story'}" if style is not None and any(
                x.get("type") == "story" for x in sb.get("scenes", [])) else ""),
            "checks": [{"name": c.name, "ok": c.ok, "severity": c.severity, "detail": c.detail} for c in checks],
        }
        (paths.manifests / f"{idea_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if not keep_frames:
            shutil.rmtree(frames, ignore_errors=True)
        with db.connect(paths.db) as con:
            if ok:
                db.set_status(con, idea_id, "rendered", output_path=str(mp4))
            else:
                bad = "; ".join(c.name for c in checks if not c.ok and c.severity != "warn")
                db.set_status(con, idea_id, "failed", error=f"validation failed: {bad}", output_path=str(mp4))
        for c in checks:
            (log.info if c.ok else log.warning)("%s", c.line())
        log.info("%s in %.1fs -> %s", "DONE" if ok else "VALIDATION FAILED", time.time() - t0, mp4)
        return ok
    except Exception as e:
        log.exception("render failed")
        with db.connect(paths.db) as con:
            db.set_status(con, idea_id, "failed", error=f"{type(e).__name__}: {e}")
        if isinstance(e, subprocess.CalledProcessError):
            log.error("command stderr: %s", (e.stderr or "")[-2000:])
        return False


# ---------------------------------------------------------------- CLI commands


def cmd_render(a, paths: Paths) -> int:
    setup_logging(paths, a.id, a.verbose)
    try:
        ok = render_idea(paths, a.id, Path(a.voice) if a.voice else None, a.workers, a.keep_frames,
                         getattr(a, "force", False))
    except JobError as e:
        log.error("%s", e)
        with db.connect(paths.db) as con:
            row = db.get(con, a.id)
            if row and row["status"] not in db.LOCKED:
                db.set_status(con, a.id, "failed", error=str(e))
        return 2
    return 0 if ok else 1


def cmd_retry(a, paths: Paths) -> int:
    with db.connect(paths.db) as con:
        row = db.get(con, a.id)
    if row is None:
        print(f"{a.id} has never been rendered; use `render`.")
        return 2
    print(f"retrying {a.id} (status={row['status']}, attempts={row['attempts']}, last error={row['error']})")
    return cmd_render(a, paths)


def cmd_validate(a, paths: Paths) -> int:
    style = load_style(paths)
    mp4 = paths.drafts / f"{a.id}.mp4"
    man = paths.manifests / f"{a.id}.json"
    expected = None
    if man.exists():
        m = load_json(man)
        expected = m.get("duration") or m["voiceover"]["duration"] + style.get("tail_seconds", 0.8)
    checks = validate.validate_video(mp4, style, expected, None, required_assets(paths, style))
    for c in checks:
        print(c.line())
    ok = validate.passed(checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_voice(a, paths: Paths) -> int:
    from . import budget
    setup_logging(paths, a.id, a.verbose)
    if a.force and paths.find_voiceover(a.id) and paths.storyboard(a.id).exists():
        print(f"Re-voicing {a.id} replaces its voiceover. {budget.spend_note(paths, a.id)}")
        if not a.yes:
            try:
                answer = input("Spend these ElevenLabs credits? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("not re-voiced")
                return 1
    try:
        out = voicemod.synthesize(paths, a.id, a.force)
    except voicemod.VoiceError as e:
        log.error("%s", e)
        return 2
    print(out)
    print(budget.line(budget.summary(paths)))
    return 0


def cmd_music_library(a, paths: Paths) -> int:
    setup_logging(paths, None, a.verbose)
    try:
        made = elmusic.make_library(paths, a.count, a.seconds, a.force)
    except voicemod.VoiceError as e:
        log.error("%s", e)
        return 2
    for p in made:
        print(p)
    print(f"{len(elmusic.tracks(paths))} tracks in {elmusic.library_dir(paths)}")
    return 0


def cmd_status(a, paths: Paths) -> int:
    from datetime import date
    from . import budget, review
    todays = review.today(paths)
    print(f"Today {date.today().isoformat()}: {len(todays)} of {review.DAILY_SLOTS} reels")
    for r in todays:
        flag = f"  ({r['status']})" if r["status"] in ("failed", "rejected", "rendering") else ""
        err = f"  ! {r['error']}" if r["error"] and r["status"] == "failed" else ""
        print(f"  {r['id']:<18} {r['stage']:<10} {(r['title'] or '')[:56]}{flag}{err}")
    for _ in range(review.DAILY_SLOTS - len(todays)):
        print("  (open slot)")
    print(budget.line(budget.summary(paths)))
    with db.connect(paths.db) as con:
        rows = con.execute("SELECT id, status, attempts, score, title, error FROM ideas "
                           "WHERE status != 'discovered' AND id NOT LIKE 'RSS-%' AND id NOT LIKE ? ORDER BY updated_at DESC LIMIT 30",
                           (f"AI-{date.today():%Y%m%d}-%",)).fetchall()
    print("\nEarlier")
    if not rows:
        print("  no jobs yet")
    for r in rows:
        err = f"  ! {r['error']}" if r["error"] else ""
        print(f"  {r['id']:<18} {r['status']:<10} tries={r['attempts']}  {r['title'][:60]}{err}")
    return 0


def cmd_preview(a, paths: Paths) -> int:
    """Render single frames (no video) for fast design iteration.

    With ``--dry`` (or when there is no voiceover yet) the timing is estimated from the script, so a
    storyboard can be looked at before any ElevenLabs credits are spent."""
    setup_logging(paths, None, a.verbose)
    style = load_style(paths)
    svg.set_font_dir(paths.fonts)
    sb = load_json(paths.storyboard(a.id))
    style = style_for(style, sb)
    voice = None if a.dry else Path(a.voice) if a.voice else paths.find_voiceover(a.id)
    (paths.work / a.id).mkdir(parents=True, exist_ok=True)
    if voice is None:
        from . import check
        spoken = cta.spoken_script(sb, style)
        end = cta.scene(sb, style, True)
        sb = {**sb, "scenes": [*sb["scenes"], end]} if end else sb
        words, duration = check.estimate_words(spoken)
        log.info("no voiceover used: timing estimated from the script (~%.1fs)", duration)
    else:
        spoken, sb = with_cta(sb, style, voice)
        voice, _ = prepare_voice(voice, paths.work / a.id, style)
        words, tinfo = timing.time_words(spoken, voice, paths.whisper_model)
        duration = tinfo["duration"]
    tl = tlmod.build(sb, words, duration, style)
    out = paths.work / a.id / "preview"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    times = [float(x) for x in a.t.split(",")] if a.t else \
        [s.start + min(s.dur * 0.7, s.dur - 0.1) for s in tl.scenes]
    stills = []
    for t in times:
        p = out / f"t{t:06.2f}.png"
        render.rasterize(render.frame_svg(t, tl, style), p, render.rsvg_env(paths))
        stills.append(p)
        print(p)
    sheet = render.still_grid(stills, [f"{k + 1}  {t:.1f}s" for k, t in enumerate(times)],
                              paths.drafts / f"{a.id}.preview.jpg")
    cover = render.thumbnail(render.thumbnail_params(sb), style, paths, out / "cover.jpg")
    print(f"preview sheet: {sheet}\ncover: {cover}")
    return 0


def cmd_check(a, paths: Paths) -> int:
    """Pre-flight check of a storyboard: run it before spending voice credits."""
    from . import check
    style = load_style(paths)
    svg.set_font_dir(paths.fonts)
    sb = load_json(paths.storyboard(a.id))
    checks = check.check_storyboard(sb, style_for(style, sb))
    for c in checks:
        print(c.line())
    bad = check.errors(checks)
    print("READY TO VOICE" if not bad else f"{len(bad)} problem(s) to fix")
    from . import budget
    b = budget.summary(paths, style)
    n = budget.cost(paths, a.id, style)
    print(budget.line(b) + f"\nvoicing {a.id} costs {n:,} characters"
          + ("" if b["left"] is None else f" ({b['left'] - n:,} left after)"))
    if sb.get("draft"):
        print(f"(draft: run `reelfactory ready {a.id}` when you're happy with the preview)")
    return 0 if not bad else 1


def cmd_ready(a, paths: Paths) -> int:
    """Mark a draft storyboard as final, so the watcher voices and renders it."""
    from . import check
    path = paths.storyboard(a.id)
    sb = load_json(path)
    style = load_style(paths)
    svg.set_font_dir(paths.fonts)
    bad = check.errors(check.check_storyboard(sb, style_for(style, sb)))
    if bad:
        for c in bad:
            print(c.line())
        print(f"not marked ready: fix the problems above (`reelfactory check {a.id}`)")
        return 1
    sb.pop("draft", None)
    path.write_text(json.dumps(sb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with db.connect(paths.db) as con:
        row = db.get(con, a.id)
        if row is None:
            db.upsert_idea(con, a.id, sb.get("title", a.id), status="selected", script_path=str(path))
        elif row["status"] == "failed" and not paths.find_voiceover(a.id):
            db.set_status(con, a.id, "selected")     # a parked voice failure gets another go
    print(f"{a.id} is ready. With the stack running the watcher voices + renders it within a minute;\n"
          f"otherwise run `reelfactory voice {a.id}` then `reelfactory render {a.id}`.")
    return 0


def cmd_inbox(a, paths: Paths) -> int:
    from . import review
    items = review.inbox(paths)
    if not items:
        print("inbox is empty")
    for it in items:
        print(f"{it['id']:<18} {'READY' if it['ready'] else 'wait '}  {it['reason']}")
    return 0


def cmd_review(a, paths: Paths) -> int:
    from . import review
    try:
        if a.action == "approve":
            r = review.approve(paths, a.id, a.note)
        elif a.action == "reject":
            r = review.reject(paths, a.id, a.note)
        else:
            r = review.published(paths, a.id, a.url)
    except ValueError as e:
        print(f"error: {e}")
        return 2
    print(json.dumps(r, indent=2))
    return 0


def cmd_serve(a, paths: Paths) -> int:
    from . import api
    setup_logging(paths, "api", a.verbose)
    api.serve(paths, a.port)
    return 0


def cmd_doctor(a, paths: Paths) -> int:
    style = load_style(paths)
    rows = [
        ("python", sys.version.split()[0], sys.version_info >= (3, 11)),
        ("ffmpeg", tool_version(["ffmpeg", "-version"]), shutil.which("ffmpeg") is not None),
        ("ffprobe", "found" if shutil.which("ffprobe") else "missing", shutil.which("ffprobe") is not None),
        ("rsvg-convert", tool_version(["rsvg-convert", "--version"]), shutil.which("rsvg-convert") is not None),
        ("whisper-cli", "found" if shutil.which("whisper-cli") else "missing (captions use fallback timing)", True),
        ("whisper model", str(paths.whisper_model) if paths.whisper_model.exists() else "missing (fallback timing)", True),
        ("elevenlabs", "configured" if voicemod.configured(paths) else "not set (record voiceovers by hand)", True),
        ("eleven music library", f"{len(elmusic.tracks(paths))} tracks", True),
    ]
    rows += [(f"asset {p.name}", "ok" if p.exists() else "MISSING", p.exists()) for p in required_assets(paths, style)]
    svg.set_font_dir(paths.fonts)
    rows += [(f"font {role}", style["fonts"][role]["family"] + (" renders" if good else " FALLS BACK"), good)
             for role, good in render.font_check(paths, style).items()]
    ok = True
    for name, detail, good in rows:
        ok &= good
        print(f"[{'OK ' if good else 'BAD'}] {name:<28} {detail}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelfactory", description="Local-first AI Reel Factory")
    ap.add_argument("--root", help="project root (default: auto)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render", help="render an idea's Reel from its storyboard + voiceover")
    p.add_argument("id")
    p.add_argument("--voice", help="voiceover path (default: inbox/voiceovers/<id>.*)")
    p.add_argument("--workers", type=int)
    p.add_argument("--keep-frames", action="store_true")
    p.add_argument("--force", action="store_true", help="re-render even if approved/published")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("retry", help="re-run a failed or previous render")
    p.add_argument("id")
    p.add_argument("--voice")
    p.add_argument("--workers", type=int)
    p.add_argument("--keep-frames", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_retry)

    p = sub.add_parser("voice", help="speak the storyboard script with your ElevenLabs voice clone")
    p.add_argument("id")
    p.add_argument("--force", action="store_true", help="replace an existing voiceover")
    p.add_argument("--yes", action="store_true", help="don't ask before spending credits on a re-voice")
    p.set_defaults(fn=cmd_voice)

    p = sub.add_parser("music-library", help="generate the Eleven Music background tracks (once)")
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--seconds", type=int, default=45)
    p.add_argument("--force", action="store_true", help="regenerate existing tracks")
    p.set_defaults(fn=cmd_music_library)

    p = sub.add_parser("validate", help="re-check an already rendered MP4")
    p.add_argument("id")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("preview", help="render still frames for quick design checks")
    p.add_argument("id")
    p.add_argument("--voice")
    p.add_argument("--t", help="comma-separated times in seconds (default: one per scene)")
    p.add_argument("--dry", action="store_true", help="estimate timing from the script (no voiceover needed)")
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("check", help="pre-flight check of a storyboard (before spending voice credits)")
    p.add_argument("id")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("ready", help="mark a draft storyboard final so the watcher voices + renders it")
    p.add_argument("id")
    p.set_defaults(fn=cmd_ready)

    sub.add_parser("status", help="today's reels, the ElevenLabs budget and recent jobs").set_defaults(fn=cmd_status)
    sub.add_parser("inbox", help="voiceovers waiting and whether they will render").set_defaults(fn=cmd_inbox)
    for name, helptext in (("approve", "approve a rendered video (protects it, copies to output/approved/)"),
                           ("reject", "reject a rendered video with a note")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("id")
        p.add_argument("note", nargs="?")
        p.set_defaults(fn=cmd_review, action=name)
    p = sub.add_parser("published", help="log the Instagram post URL of an approved video")
    p.add_argument("id")
    p.add_argument("url")
    p.set_defaults(fn=cmd_review, action="published")
    p = sub.add_parser("serve", help="run the local API for n8n (127.0.0.1 only)")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("doctor", help="check tools and assets").set_defaults(fn=cmd_doctor)

    from . import discover  # phase 2 commands
    discover.add_commands(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    paths = Paths(Path(a.root).resolve()) if a.root else Paths.default()
    return a.fn(a, paths)
