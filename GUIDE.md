# Guide

A local-first tool that turns **one AI/tech idea** into a finished **1080×1920 Instagram Reel**: animated character story scenes, your ElevenLabs voice clone (or your own recording), kinetic word-synced captions, music and sound effects, a Follow end card, a designed cover, a caption draft, a source manifest and a validation report.

The only paid service is ElevenLabs Starter (voice + a one-off music library). There are no other paid APIs and no hosted services, Claude is never called from scripts (you use it interactively), and nothing is ever auto-posted.

```
RSS feeds ─► discover ─► rank ─► shortlist.md ─► (you + Claude chat) storyboard JSON
                                                         │
                     your voiceover  inbox/voiceovers/<ID>.m4a
                                                         ▼
         whisper.cpp word timing ─► timeline ─► SVG frames ─► rsvg-convert ─► FFmpeg ─► MP4
                                                                                      └► validate ─► review.md
```

## Story scenes (animated, character-driven)

New storyboards use `"theme": "story"`: each beat is a `story` scene where characters (bean people and AI-agent
bots with moods, poses, speech bubbles) act the idea out in a set (island, stage, office, lab, city, cyber,
night, room), with swarms, counters, grids, a moving camera, scene transitions, kinetic word-by-word captions
and automatic sound effects. The brief from `new-idea` asks Claude for exactly this; the full reference is
[docs/story-scenes.md](docs/story-scenes.md). Older `card` storyboards still render in the light editorial style.

## One-time setup (macOS, Apple Silicon)

The steps for a fresh Mac:

```bash
brew install ffmpeg librsvg whisper-cpp uv
```

```bash
cd faceless-reels-factory
```

```bash
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
```

Fonts (both SIL OFL): from `Inter-4.1.zip` (https://github.com/rsms/inter/releases), copy `Inter-SemiBold.ttf` and `Inter-Medium.ttf` into `assets/fonts/`. From `UnderCaseType_Fraunces_1.000.zip` (https://github.com/undercasetype/Fraunces/releases), copy `Fraunces72ptSoft-Bold.ttf` and `Fraunces9ptSoft-Regular.ttf`. `doctor` checks that every font really renders.

Whisper model (about 148 MB, for word-accurate captions):

```bash
curl -L -o models/ggml-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

Check everything:

```bash
.venv/bin/python -m reelfactory doctor
```

> Tip: run `source .venv/bin/activate` once per terminal, and then `python -m reelfactory …` works without the `.venv/bin/` prefix.

## Daily workflow

The fast path is **`/reel` in Claude Code**, opened in this folder. It runs on your Claude plan, interactively, so no API is involved. It picks or creates the idea, reads and fact-checks the source, writes the storyboard, checks it, shows you preview stills *before any voice credits are spent*, and once you say yes hands it to the watcher. The skill lives in [.claude/skills/reel/SKILL.md](.claude/skills/reel/SKILL.md).

```
 idea ──► /reel in Claude Code ──► check ──► preview --dry ──► you: OK? ──► ready ──► voice + render ──► Telegram ──► approve ──► post by hand
 (shortlist #, your .md,          (cues,      (stills + cover,               (watcher, or        (video, cover,
  or pasted text)                  layout)     no credits)                   voice/render)       caption)
```

The same steps by hand:

1. **Find ideas.** Either the RSS shortlist or your own notes:
   ```bash
   .venv/bin/python -m reelfactory daily
   ```
   That fetches the feeds, ranks them and writes `data/scripts/shortlist-YYYY-MM-DD.md`. Your own ideas are `.md` files in `inbox/ideas/` (first `# heading` = title, any links = sources); `ideas` lists them.
2. **Pick one.** A shortlist rank, or one of your notes. This creates `data/scripts/AI-YYYYMMDD-NNN.json` (the storyboard skeleton) and a `.brief.md`:
   ```bash
   .venv/bin/python -m reelfactory new-idea 1
   ```
   ```bash
   .venv/bin/python -m reelfactory new-idea agent-passports.md
   ```
3. **Write it with Claude.** Use `/reel <ID>` in Claude Code, or paste the `.brief.md` into the Claude app and save the JSON it returns over the skeleton. Add `"draft": true` while you're still working on it: the watcher won't voice a draft.
4. **Check and preview, for free.** `check` catches cue phrases that aren't in the script, unknown poses/props/sets, leftover skeleton text, captions outside the safe zone and an over-long script, and estimates the length and ElevenLabs characters. `preview --dry` renders one still per scene plus the cover, with no voiceover, into `output/drafts/<ID>.preview.jpg`:
   ```bash
   .venv/bin/python -m reelfactory check AI-20261020-004
   ```
   ```bash
   .venv/bin/python -m reelfactory preview AI-20261020-004 --dry
   ```
5. **Mark it ready.** This re-runs the check and removes `draft`:
   ```bash
   .venv/bin/python -m reelfactory ready AI-20261020-004
   ```
6. **Voiceover.** With the stack running, the watcher voices the storyboard within a minute and renders it. By hand:
   ```bash
   .venv/bin/python -m reelfactory voice AI-20261020-004
   ```
   This writes `inbox/voiceovers/<ID>.mp3`. A storyboard that fails `check` is refused before ElevenLabs is called, so no credits are spent on it. Use `--force` after editing the script, but note that it spends credits again: the CLI says how many characters it will spend and what's left this month, and asks before going ahead (`--yes` skips the question). In Telegram or the dashboard, `/voice <ID> force` only quotes the cost; `/voice <ID> force yes` spends it. Without ElevenLabs, record it yourself (QuickTime → New Audio Recording) and save it as `inbox/voiceovers/<ID>.m4a`.
7. **Render.** This takes about 100 seconds for a 30-second story Reel:
   ```bash
   .venv/bin/python -m reelfactory render AI-20261020-004
   ```
8. **Review the output and publish it manually**, then log it with `approve` and `published <ID> <url>`.
   - `output/drafts/<ID>.mp4`: the Reel
   - `output/covers/<ID>.jpg`: the designed thumbnail (big headline, safe for the 3:4 profile grid). In Instagram: **Edit cover → Add from camera roll**
   - `output/drafts/<ID>.caption.txt`: the Instagram caption draft with sources
   - `output/drafts/<ID>.review.md`: validation results plus the claims to check before posting
   - `output/manifests/<ID>.json`: assets, licences, sources, tool versions and timing

### Other commands

| Command | What it does |
|---|---|
| `python -m reelfactory status` | Today's reels and their stage (draft → ready → voiced → rendered → approved → published), the ElevenLabs budget, then earlier jobs |
| `python -m reelfactory music-library` | Generates the Eleven Music background tracks once (`--count`, `--seconds`, `--force`) |
| `python -m reelfactory retry <ID>` | Re-runs a failed render (the error is in `logs/<ID>.log`) |
| `python -m reelfactory validate <ID>` | Re-checks an existing MP4 |
| `python -m reelfactory preview <ID> [--t 1.5,6.2] [--dry]` | Renders still frames plus a sheet; `--dry` estimates the timing, so no voiceover is needed |
| `python -m reelfactory check <ID>` | Pre-flight check of a storyboard (run before spending voice credits) |
| `python -m reelfactory ready <ID>` | Checks a draft storyboard and marks it final for the watcher |
| `python -m reelfactory ideas` | Your idea notes waiting in `inbox/ideas/` |
| `python -m reelfactory discover` / `rank` / `shortlist` | Runs the steps of `daily` one at a time |
| `.venv/bin/python -m pytest -q` | Runs the test suite |

## ElevenLabs voice clone (optional, paid plan)

Each voiceover uses about one credit per character of script (a 70-word script is roughly 400 characters), so the Starter plan covers a daily Reel. Only the API is needed; no MCP server.

**Budget meter.** `status`, `check`, Telegram `/status` and the dashboard show the characters voiced this calendar month against `voice.monthly_characters` in style.json (set it to your plan's monthly character allowance, which you'll find at elevenlabs.io → your profile → **Subscription**; `null` shows usage without a limit). If your API key also has the **User → Read** permission (elevenlabs.io → Developers → API keys → edit the key), the meter reads ElevenLabs' own count and limit for the billing cycle instead (a free call, cached for 10 minutes); without it, the local count below is used. It is counted from the `inbox/voiceovers/*.voice.json` sidecars, including takes a `--force` re-voice replaced. ElevenLabs resets on your billing date, not the 1st, so treat it as a close guide and check the ElevenLabs usage page near the end of a cycle.

1. On elevenlabs.io, go to **Developers → API Keys** and create a key with **Text to Speech** access.
2. Go to **Voices**, open your clone and copy its **Voice ID**.
3. Put both in `.env` as `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`, then restart the stack. `doctor` shows `elevenlabs configured`.

The model and voice settings live in `voice` in style.json (default `eleven_v4`, the most expressive model; `stability`, `similarity_boost`, `style`, `speed`). Starter allows `mp3_44100_128` at most; 192 kbps needs Creator and 44.1 kHz WAV needs Pro.

Generated voices skip the microphone clean-up EQ (they're already clean), but still get pause tightening and loudness normalisation. A voice is generated only once per idea; a failed call parks the idea as `failed` instead of retrying, so you aren't billed again by accident.

## Control panel: n8n + Telegram (optional, €0)

Python does the work; a local **n8n** orchestrates it and talks to you on **Telegram**.

```
                 ┌──────────────── n8n (localhost:5678) ────────────────┐
  08:00 daily ──►│ 1 Daily shortlist ──POST /daily────┐                 │
  every minute ─►│ 2 Voiceover watcher ─POST /watch───┼─► send reply ──►│──► Telegram (you)
  every 10 s ───►│ 3 Telegram commands ─POST /commands┘   + files       │◄── /pick /approve …
                 └──────────────────────┬───────────────────────────────┘
                                        │ X-Reel-Token, 127.0.0.1 only
                         Python API (reelfactory serve, :8765)
                 discover · rank · shortlist · render · validate · review
                 SQLite · storyboards · inbox/voiceovers · output/
```

- **Daily shortlist** (08:00): fetches feeds, ranks them, and sends you the top 10 with the best 3 starred.
- **Voiceover watcher** (every minute): when `inbox/voiceovers/<ID>.m4a` appears and its storyboard is filled in, it renders the Reel and sends you a summary, contact sheet, video and review report. Each recording is rendered only once (tracked by its fingerprint), so a failed render doesn't loop; re-record or send `/render <ID>`.
- **Telegram commands** (polled every 10 s, no public URL needed): `/shortlist`, `/daily`, `/pick N` (creates the idea and sends you its Claude brief), `/inbox`, `/voice ID [force [yes]]`, `/render ID [force]`, `/approve ID [note]`, `/reject ID [note]`, `/published ID <instagram url>`, `/status`, `/help`. Messages are processed strictly in order.

**Safety:** the API only listens on 127.0.0.1 and requires a random token. The bot only obeys your `TELEGRAM_CHAT_ID`; anyone else is ignored. Approved and published videos can't be re-rendered without `force`. Secrets stay in the git-ignored `.env` (n8n reads them via `$env`, so they aren't stored in the workflow files). Nothing is ever posted to Instagram automatically.

### Setup (once)

1. Create the secrets file (it generates the API token for you):
   ```bash
   sh scripts/setup-env.sh
   ```
2. In Telegram, message **@BotFather** → `/newbot` and copy the token. Message **@userinfobot** to get your numeric ID. Press **Start** in your new bot.
3. Open `.env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`:
   ```bash
   open -e .env
   ```
4. Install n8n (local, one time) and import the workflows:
   ```bash
   cd n8n && npm install && cd ..
   ```
   ```bash
   sh scripts/n8n-import.sh
   ```

### Every day

Nothing to do: the stack runs in the background from login (see [Running in the background](#running-in-the-background)). Open http://localhost:5678 to see the workflows and their runs, and send `/help` to your bot.

- The Mac must be awake for schedules to run (closing the lid sleeps it).
- To change the 08:00 time, edit `daily(hour=8)` in [n8n/build_workflows.py](n8n/build_workflows.py), stop the stack (`sh scripts/install-launchd.sh uninstall`), run `scripts/n8n-import.sh`, then start it again (`sh scripts/install-launchd.sh`).
- Without n8n, everything still works from the CLI: `inbox`, `approve`, `reject`, `published`, `status`.

## Dashboard

The API also serves a small web page for the same review loop, in the Reel's own cream-and-terracotta style. It runs whenever the API does (the background stack, or on its own):

```bash
.venv/bin/python -m reelfactory serve
```

Open http://127.0.0.1:8765 and sign in once with `REELFACTORY_API_TOKEN` from `.env` (`grep REELFACTORY_API_TOKEN .env` shows it).

- **Today**: three slots for today's reels (IDs `AI-<today>-NNN`), each showing its stage from draft to published, with **Approve**/**Reject** and **Mark published** where they apply, plus the ElevenLabs budget meter.
- **Today's shortlist**: the ranked ideas with a **Pick** button (same as `/pick N`), plus **Fetch fresh ideas** (`/daily`).
- **Voiceover inbox**: each recording in `inbox/voiceovers/` and whether it will render; ready ones get a **Render** button.
- **Recent jobs**: the draft video (plays and seeks in the page), its contact sheet, the review report and caption draft. **Approve** and **Reject** take an optional note; approved jobs get a field for the Instagram URL and **Mark published**.

Every button sends the matching chat command through the same code path as Telegram, in the same queue, so the rules are identical (approved videos stay locked, only `instagram.com` URLs are accepted, and so on). The reply appears at the top of the page.

**Safety:** it's still 127.0.0.1 only. Signing in checks the token once and sets an HttpOnly, SameSite=Strict session cookie for 30 days; the token never appears in the page or in a URL. Every button press also carries a per-session CSRF token, and requests that don't address the server by a localhost name are refused. To sign every browser out, change `REELFACTORY_API_TOKEN` in `.env` and restart the API (then update n8n too, since it uses the same token). n8n keeps working unchanged with the `X-Reel-Token` header.

## Call to action and thumbnail

- **CTA:** `cta` in style.json. Every Reel ends on a "Before you go" page laid out like your Instagram profile header: your photo, username, name and bio from `profile` in style.json (photo at `assets/brand/avatar.jpg`; replace it when you change your profile picture), and a Follow button that gets tapped. When ElevenLabs voices the Reel it also speaks `cta.spoken` at the end (in your clone's voice); a hand-recorded voiceover gets the same card silently for `hold_seconds`. A storyboard can override any field with its own `"cta": {…}`, or drop it with `"cta": false`. Don't write "follow me" into the script itself.
- **Thumbnail:** the storyboard's `thumbnail` (`label`, `headline` with one `*accent*`, optional `sub`); without it, the first card's label and headline are used.
- **Telegram:** each finished render now sends the contact sheet, the video, the full-resolution thumbnail (as a file), the caption file, and the caption text in a copyable block.

## Storyboard format

`data/scripts/<ID>.json` holds:

- `script`: exactly what you will say.
- `emphasis`: subtitle words drawn in the accent colour.
- `scenes`: each one is a `card` with an `at` (the script phrase where it starts) and `params`:
  - `label`: a small uppercase tag.
  - `headline`: the on-screen line. Wrap one phrase in `*asterisks*` to colour it terracotta.
  - `sub` (optional): a one-line subheading.
  - `headline2` + `swap_at` (optional): crossfade to a second headline on a cue.
  - `visual`: one of `apps`, `rows`, `connect`, `feed`, `consent` (see [scenes.py](src/reelfactory/scenes.py)).

  Any key named `at` or ending in `_at` is a phrase from the script, so the animation follows your real voice.

`claims` and `sources` flow into the review report, the manifest and the caption.

## Configuration

- [config/style.json](config/style.json): colours, fonts, caption size and position, Instagram safe zone, handle, fps, audio levels.
- **Music:** `audio.music` in style.json. The default `"source": "elevenlabs"` picks one track per idea (by its ID) from `assets/music/elevenlabs/`, made once with `python -m reelfactory music-library` (6 × 45 s ≈ 4.5 of Starter's ~40 music minutes a month); `lufs` evens out their loudness before ducking. Prompts and dates are in `library.json`. If the library is empty it falls back to the generated bed. `"source": "generated"` synthesizes an original lo-fi bed (pad, arpeggio, bass, soft percussion) with a variation seeded by the idea ID, so there is no licence to worry about. Pin `mood` (`warm`, `float`, `soft`, `dawn`) or `bpm`, or turn `drums` off. To use your own licensed track (e.g. from Pixabay Music), put it in `assets/music/` and set `"source": "file", "file": "track.mp3"`. `"source": "off"` disables music. Music is ducked under your voice (`gain`, `duck_threshold`, `duck_ratio`).
- [config/feeds.json](config/feeds.json): RSS feeds, freshness window and ranking weights and terms. Every score is broken down per factor in the shortlist, so you can see why something ranked.

## How it works

- Homebrew's FFmpeg has no `drawtext` or SVG support, so **every frame is an SVG** built in Python ([scenes.py](src/reelfactory/scenes.py), [captions.py](src/reelfactory/captions.py)). Frames are rasterised in parallel by `rsvg-convert`, which is forced onto Pango's fontconfig backend so the bundled fonts are used ([config/fonts.conf](config/fonts.conf) gives Fraunces the simple aliases `Reel Display` / `Reel Text`). FFmpeg only encodes the frames and mixes the audio.
- **Caption timing:** whisper.cpp transcribes your recording with word timestamps, and those times are aligned to the script, so captions always use the script's spelling. If whisper is missing, timing falls back to spreading the words across the speech that `silencedetect` finds. The review report shows the method and the script match ratio.
- **Voice clarity:** `audio.enhance` in style.json (`light` / `balanced` / `strong`, or your own `filters`). It cuts boom, removes hiss, then lifts the 2–4 kHz clarity band, and the manifest records before/after measurements. Best results still come from recording 10–15 cm from the mic in a soft-furnished room.
- **Audio:** dead air at the start and end is trimmed, pauses longer than 0.42 s are shortened to 0.3 s (`audio.tighten` in style.json), and your voice is normalised to about −14 LUFS. A soft pop marks each new card and a quiet tick each cue. Both are synthesized from scratch in [audio.py](src/reelfactory/audio.py), and a limiter is applied last.
- **Validation:** resolution, codec, fps, duration, a full decode with no errors, audio present and not silent, no blank frames, caption timing and safe zone, and all assets present.
- **Jobs:** state is kept in SQLite (`data/ideas.db`). Failures record the error and keep the attempt count, so `retry` re-runs cleanly.

## Running in the background

The API and n8n run as a macOS LaunchAgent: they start at login, restart if they stop, and need no open terminal. Keep the project outside `~/Desktop`, `~/Documents` and `~/Downloads`, because macOS blocks background jobs from reading them.

Install it, or reinstall after moving the project or changing your Node version:

```bash
sh scripts/install-launchd.sh
```

Stop it and remove it (then `sh scripts/start-stack.sh` runs the stack in a terminal as before):

```bash
sh scripts/install-launchd.sh uninstall
```

Its output goes to `logs/stack.log`. To see whether it's running:

```bash
launchctl print gui/$(id -u)/com.reelfactory.stack | grep state
```

Code changes in `src/` take effect after a restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.reelfactory.stack
```

## Licences and ethics

- The graphics and sound effects are original and generated by this code.
- Inter and Fraunces are under the SIL Open Font License 1.1 (`assets/fonts/*-OFL-LICENSE.txt`).
- Never drop other creators' Reels or unlicensed media into `assets/`. The manifest lists every asset a render used.
- Claims marked `uncertain` or `general` are listed in the review report for you to verify before posting.
