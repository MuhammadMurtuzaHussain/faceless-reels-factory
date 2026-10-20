# Faceless Reels Factory

A local-first tool that turns an idea into a finished 1080×1920 vertical video: animated character story scenes,
a voiceover (recorded, or an optional ElevenLabs clone), kinetic captions, music, a CTA end card and a cover.
[GUIDE.md](GUIDE.md) is the full guide, and `docs/story-scenes.md` is the storyboard reference. The account details
(handle, niche, profile, CTA) live in `config/style.json`.

## Making a video

Use the `/reel` skill (`.claude/skills/reel/SKILL.md`). In short:
`new-idea` → write `data/scripts/<ID>.json` with `"draft": true` → `check` → `preview --dry` → the user's OK →
`ready` → the watcher (or `voice` + `render`) → review → the user posts it by hand.

`RF` = `.venv/bin/python -m reelfactory`. Useful commands: `ideas`, `new-idea`, `check`, `preview --dry`, `ready`,
`voice`, `render`, `status`, `inbox`, `approve`, `published`, `doctor`. Tests: `.venv/bin/python -m pytest -q`.

## Ground rules

- **Publishing:** never post anything automatically. The user reviews and posts every video themselves.
- **Voice credits:** each ElevenLabs voiceover costs money. Never re-voice (`--force`) without asking, and keep an eye on `RF status`.
- **Claude:** don't add calls to paid APIs (Claude included) from scripts. Claude is used interactively.
- **Visual style:** show the idea with characters and props instead of printing it. Keep on-screen text short, and leave "follow me" out of the script (the CTA is added automatically).
- **Facts:** every fact needs a source quote. Anything unverified is marked `uncertain` in `claims`.
- **Network:** everything stays on 127.0.0.1. Secrets stay in the git-ignored `.env`.
