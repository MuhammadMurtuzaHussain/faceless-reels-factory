# Story scenes: authoring reference

Story scenes make the Reel *show* the idea: characters act out each beat in a little world, objects appear
as the voice mentions them and the camera pushes in on the key moment. The spoken words appear as big kinetic
captions at the top of the frame, so on-screen text stays short (labels, counters, stamps, one punchline title).

The code lives in `src/reelfactory/story.py` (sets, camera, elements) and `src/reelfactory/cast.py`
(characters and props). A storyboard opts in with `"theme": "story"` and `"type": "story"` scenes; old
`card` storyboards still render exactly as before.

## Layout

```
y    0 ┌──────────────┐
       │  IG top bar  │
  330  │  CAPTIONS    │  kinetic words (keep the stage clear above ~480)
  480  ├──────────────┤
       │    STAGE     │  x 0–1080; slots: far-left 150, left 270, left-third 360,
       │              │  center 540, right-third 720, right 810, far-right 930
 1340  │ ── ground ── │  actors and grounded props stand here by default
 1440  │  labels      │  short tags sit here
 1540  ├──────────────┤  Instagram's UI covers the rest
```

`y` also accepts `top` 600, `sky` 640, `high` 760, `mid` 920, `low` 1120 or `ground`.

## Storyboard shape

```json
{
  "theme": "story",
  "cast": {
    "eko": {"kind": "bot", "color": "accent", "name": "Eko"},
    "researcher": {"kind": "person", "color": "slate", "outfit": ["labcoat", "glasses"]}
  },
  "scenes": [
    {"type": "story", "at": "first words", "params": {
      "set": "island", "transition": "zoom",
      "camera": {"moves": [{"at": "cue", "zoom": 1.25, "focus": "eko", "dur": 0.8}], "shake": [{"at": "cue"}]},
      "title": {"text": "Playing, or *pretending?*", "at": "cue", "out_at": "cue"},
      "elements": [ ... ]
    }}
  ],
  "thumbnail": {"label": "AI experiment", "headline": "Left alone, it *started to play*.",
                "set": "island", "actor": {"who": "eko", "mood": "grin", "pose": "juggle"}}
}
```

Colours can be palette names (`accent`, `slate`, `sage`, `mustard`, `plum`, `sand`, `danger`, `ink`, `muted`)
or hex.

## Timing

Every `at` / `*_at` value is an exact phrase from the script (resolved to the moment it's spoken) or a
number of seconds after the scene starts. Each element:

| key | meaning |
|---|---|
| `at` | when it appears (default: a quick stagger at the start of the scene) |
| `enter` | `pop` · `drop` · `rise` · `grow` · `slam` · `fade` · `walk-left` · `walk-right` · `fly-left` · `fly-right` · `none` |
| `out_at`, `exit` | when it leaves, and how: `pop` · `fade` · `drop` · `walk-left` · `walk-right` |
| `do` | list of changes on cues (below) |
| `id` | name it so swarms, links, confetti and the camera can target it |

A `do` entry is `{"at": cue, ...}` with any of:

- `move`: `[x, y]` (or `{"x":…}`); people walk there, `arc` (px) makes it a jump/throw, `dur` overrides speed
- `pose`, `mood`, `look` (`left` `right` `up` `down` `center`), `say` (speech bubble, ≤ 6 words), `emote`
- `state` (props: `hacked`, `open`, `broken`, `on`, `off`; counters: `struck`)
- numbers that tween: `value` (counters), `level` (meter), `grow` (chart/tower), `size`, `speed`
- `label`, `title`, `text`, `lines`, `color` swap instantly

## Characters (`el: "actor"`, with `who` from `cast`)

- **person**: bean body, face that carries the emotion. Outfits: `hoodie` `glasses` `labcoat` `tie` `suit` `cap` `headset`.
- **bot**: AI agent with a screen face, antenna and hover.
- `size` (person 1.0 ≈ 325 px tall, bot 0.9 ≈ 220 px), `label: true` shows the cast name (or a string).
- `hold`: a prop name drawn in the right hand (e.g. `magnifier`, `phone`, `ball`).
- **Moods**: neutral happy grin smirk sly shock sad worried focused sleepy proud curious angry love
- **Poses**: idle wave cheer point present type hold think shrug relax panic cross juggle throw catch hips sad
  (`point-left`, `wave-left`… mirror them). Poses blend smoothly; `type`, `wave`, `panic`, `juggle` keep moving.
- **Emotes**: `!` `!!` `?` `sparkle` `heart` `zzz` `sweat` `idea` `check` `cross` `music`

## Other elements

| `el` | what it does | key params |
|---|---|---|
| `prop` | an object (list below) | `kind`, `x`, `y`, `size`, `label`, `title`, `lines`, `state`, `glow` |
| `swarm` | agent bots fly from `from` to `to` and get busy there (hopping between grid cells) | `who`, `count` ≤ 40, `from` (id or `[x,y]`), `to` (grid id, element id(s) or points), `stagger`, `size` |
| `grid` | many small icons that turn `fill` colour between `fill_at` and `end_at`, with a live count | `count`, `cols`, `w`, `icon` (site/dot/person), `label`, `fill_to` 0..1 |
| `counter` | big number counting `from`→`to` between `at` and `end_at`; `do` `value` re-sets it | `prefix`, `suffix`, `label`, `font` |
| `label` | short tag (`variant`: tag · plain · big) | `text`, `color`, `arrow` |
| `stamp` | text that slams on with an impact | `text`, `rotate`, `color` |
| `link` | dotted connection with travelling dots | `from`, `to`, `bend`, `color` |
| `crowd` | a row of identical characters popping in | `who`, `count`, `x0`, `x1`, `pose`, `moods` |
| `confetti` | celebration burst | `on` (id) or `x`/`y` |

**Props**: grounded (anchored at their bottom): palm, desk (with laptop), hoop, building, server, mountain,
sign, flag, lamp, block, tower, lava, plant, rock, podium. Floating (anchored at their centre): ball, clock,
note, window, terminal, laptop, bulb, magnifier, lock, shield, trophy, chart, meter, star, phone.

Prop extras: `window`/`terminal` type their `lines` between `at` and `end_at`; `note` highlights line `mark`
at `mark_at`; `chart` takes `bars` [{label, value 0..1}]; `meter` takes `level`; `tower` takes `count`;
`building` shows `label` and flashes red on `state: "hacked"`; `clock` spins at `speed` with a `label`;
`hoop` swishes at `swish_at`.

## Sets, camera, transitions, title

- **Sets**: `stage` (spotlight), `island` (`sky` day/sunset/night, `cycle_at` sweeps day→night, `virtual`, `palm`),
  `night` (stars + soil cross-section), `office`, `lab`, `city`, `cyber`, `room`.
- **Camera**: `zoom`, `focus` (id or `[x,y]`), `drift` (slow push-in, default 0.045), `moves` (keyframes), `shake`.
  Avoid zoom below 1.0 (the set's edges would show).
- **Transition into the scene**: `zoom` (default) · `whip` · `iris` · `fade` · `cut`.
- **Title**: one punchline per Reel at most; while it is on screen the captions step aside.

## Sound

Sound effects follow the action automatically: whoosh on scene changes, swarms, throws and jumps; pop when
things appear; blip for bubbles and emotes; impact for stamps, drops and camera shakes; alert when something
gets hacked. They stay sparse (never two within 0.12 s).

## Checklist

- Each beat has a character doing something that *means* the sentence (not just standing there).
- Something moves on every key phrase; the camera moves at least once per scene.
- On-screen text is at most a few words; numbers come from the source.
- Preview stills: `python -m reelfactory preview <ID>` (or `--t 1.5,6.2`).
