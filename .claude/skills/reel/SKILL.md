---
name: reel
description: Make one Instagram Reel for your account (handle and niche in config/style.json) end to end, from a shortlist number, an idea .md file, an existing AI-… ID or a pasted idea. It fact-checks the source, writes the script and the animated story storyboard, runs the pre-flight check, previews stills without spending credits, then hands off to voice + render once the user approves. Use for "/reel", "make a reel about…", "next reel", "today's reels".
---

# /reel: one Reel, from idea to rendered draft

Work in the project folder. `RF` below means `.venv/bin/python -m reelfactory`, run from that folder.

## 1. Find the idea

| The user gave | Do |
|---|---|
| nothing | Show `RF ideas` plus the top 5 of the newest `data/scripts/shortlist-*.md`, and ask which one |
| a number `N` | `RF new-idea N` (rank in the latest shortlist) |
| a `.md` path, or a file name in `inbox/ideas/` | `RF new-idea <file>` (the note is filed under `inbox/ideas/used/`) |
| pasted text / a topic | Write it to `inbox/ideas/<short-slug>.md` (first line `# <title>`, keep their words and links), then `RF new-idea <slug>.md` |
| an ID like `AI-20261020-004` | Carry on with that storyboard |

`new-idea` prints the new ID, the storyboard path `data/scripts/<ID>.json` and the brief `data/scripts/<ID>.brief.md`.

## 2. Read before writing

- The brief `data/scripts/<ID>.brief.md` is the spec: word count, scene rules, vocabulary, layout limits.
- `docs/story-scenes.md` is the full element reference.
- Use one recently rendered storyboard as a pattern (`RF status`, pick the newest `rendered` AI-… ID, then read its JSON).

## 3. Research

- Fetch every source URL. Write down 3–5 facts, each with the exact supporting quote.
- If the note has no source, search for a reliable one. If you can't find one, tell the user and stop.
- Anything you can't tie to a quote is `uncertain`. Don't hype, and use only verified facts in the script.

## 4. Write the storyboard

- Write 3 hook options (under 10 words each). Pick the strongest and say why in one line.
- Write the script: 55–75 words, made of a hook, 2–3 beats and a one-line takeaway. Never end it with "follow": the spoken CTA and end card are added automatically.
- Fill the skeleton completely, following the brief: `cast`, 5–7 `story` scenes, `thumbnail`, `claims`, `sources`, and `caption` (hook, body, 3–5 hashtags). Keep `id` as it is.
- Add `"draft": true` at the top level. While it's there the watcher won't voice the storyboard, so no credits are spent.
- Show the idea instead of printing it: characters act each beat, props appear when they're mentioned, and the camera pushes in on the key moment. Keep on-screen text to short labels, counters, stamps or one title. Visuals must not imply numbers the source doesn't give.
- Save the storyboard with the Write tool to `data/scripts/<ID>.json`.

## 5. Check, then look

1. `RF check <ID>`: fix every FAIL. Fix WARNs too when it's cheap to do so (layout, cue timing, thumbnail). Repeat until it prints `READY TO VOICE`.
2. `RF preview <ID> --dry`: open `output/drafts/<ID>.preview.jpg` and `output/.work/<ID>/preview/cover.jpg` with Read, and review them critically:
   - Does every beat show something happening?
   - Is there any empty or crowded scene, or overlapping actors and props?
   - Is anything sitting under the caption band at the top?
   - Is the text readable, and the cover readable at grid size?
   Fix the storyboard, re-check and re-preview. Stop after about 3 rounds.

## 6. Show the user and wait

Send the preview sheet with SendUserFile. Then give, briefly:
- the chosen hook (and the other two)
- the script
- the facts with their status, with uncertain claims marked
- the estimated length and ElevenLabs characters (from `RF check`)

Ask whether it's approved or what to change. Don't voice it until the user says yes.

## 7. Hand off

1. On a yes, run `RF ready <ID>`. It re-checks the storyboard and removes `draft`.
2. If the stack is running (`lsof -iTCP:8765 -sTCP:LISTEN` shows a listener), the watcher voices it, renders it (about 100 s) and sends it to Telegram within a minute. Tell the user that and stop.
3. If the stack isn't running, run `RF voice <ID>`, then `RF render <ID>` in the background. Then read `output/drafts/<ID>.contact.jpg` and `<ID>.review.md` and report the validation result and the claims to verify.

## Rules

- **Credits:** every ElevenLabs voiceover spends about 450 characters of your plan. Never run `RF voice --force`, and never re-voice after a script edit, without asking first.
- **Publishing:** never publish or post anything, and never call any other paid service. The user posts by hand and then logs it with `RF published <ID> <instagram url>`.
- **Voice:** only use a voice the user owns or has the rights to (their clone, or their own recording).
- **Daily batch:** when asked for several reels, make them one at a time, each through steps 1–7.
