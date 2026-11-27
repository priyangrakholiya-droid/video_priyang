# CLAUDE.md — how to drive this video editor

You are reading this because you have been asked to edit an event video with
this repo. Everything you need is a shell command. Read this file first, then
start at **Quick recipe**.

---

## What this tool is

A five-step editor for event films — marriage, engagement, party, baby shower,
birthday, anniversary. It turns raw footage into one finished film.

**Its central rule, which shapes everything you do with it:**

> A clip is a **reference** — a file path plus an in and out point. No footage
> is ever copied, cut or duplicated into the project. Only one video file is
> ever written: the finished film.

That is why you can run every step in seconds, change your mind for free, and
read the entire state of an edit as JSON.

## What you can and cannot do

| You can | You cannot |
|---|---|
| Scan footage and have moments proposed automatically | Watch the footage — you never see the pictures |
| Read and write every decision as JSON | Judge whether a face looks happy |
| Re-run any step with different settings, for free | Know who the people are |
| Edit `project.json` directly and re-run a step | Undo a render (it overwrites) |

**Be honest with the user about the second column.** The emotion step measures
brightness, motion and loudness, not faces. Say so rather than implying the
tool understood the moment.

---

## Before anything else

```bash
python -m video_editor doctor --json
```

`{"ready": true, ...}` means go. If `ffmpeg` or `ffprobe` is missing, stop and
tell the user to install ffmpeg — nothing works without it, and you cannot
install it for them without their say-so.

Set `PYTHONPATH=src` when running from a clone (or `pip install -e .` once).

---

## Quick recipe

The whole job, unattended, for a six minute wedding film:

```bash
PYTHONPATH=src python -m video_editor run "D:/wedding/full_day.mp4" \
  --name "Priya & Rahul Marriage" \
  --preset marriage \
  --minutes 6 \
  --song "D:/music/song.mp3" \
  --json
```

One JSON document comes back on stdout. The film's path is in `.rendered`.

Prefer running the five steps one at a time when the user is watching, so they
can change their mind between steps. Each step prints the same summary shape.

---

## The five steps

Always pass `--json`. It silences the human output, prints one document, and
— importantly — **never asks a question**, so a step can never hang waiting
for input you cannot give.

### 1. select — what the film is made of

```bash
python -m video_editor select <footage> --preset marriage --minutes 6 \
  --mode auto --json
```

`<footage>` is one long file **or** a folder of clips. The tool detects which.

`--mode auto` scans for shot changes and loud moments and proposes enough
clips to fill the target. **This is the mode you use.** `--mode manual` needs
a human typing timecodes and will refuse under `--json`.

Tuning, when the first scan is wrong:

| Symptom | Fix |
|---|---|
| Too few moments found | `--threshold 0.15` (more sensitive) |
| Too many, all similar | `--threshold 0.45` and/or `--min-gap 10` |
| Clips all from one part of the day | raise `--min-gap` |
| "no moments found" | the footage is one static shot — `--threshold 0.1`, or tell the user it needs manual selection |

### 2. arrange — what order

```bash
python -m video_editor arrange <project> --mode story --json
```

| `--mode` | Use when |
|---|---|
| `story` | **default for any event** — the preset's ceremony order, frame-matched inside each part |
| `match` | chronology does not matter; you want the smoothest possible cuts |
| `emotion` | you want an emotional arc — run step 4 first |
| `manual` | the user named an exact order |

Read `02_arrangement/order.json` afterwards. `statistics.jumps` counts visible
jumps; if it is high relative to `statistics.cuts`, try `--mode match`.

### 3. music — cut to the beat

```bash
python -m video_editor music <project> --song "song.mp3" --snap bar --json
```

Detects the tempo, then rounds every clip to a whole number of beats.

| `--snap` | Lands every | Good for |
|---|---|---|
| `beat` | 1 beat | fast dance montage |
| `half-bar` | 2 beats | general |
| `bar` | 4 beats | most event films — the preset's default |
| `two-bar` | 8 beats | slow, romantic |

`--fit both` trims whole beats off the longest clips until the film fits
inside both the song and the target length.

Check `music.bpm` in the result. If the returned `confidence` in
`03_music/beatmap.json` is under 0.35, the song has a weak pulse — tell the
user the cuts may not feel locked.

**Skip this step entirely if the user gave no song.** Do not invent one.

### 4. emotions — read the mood

```bash
python -m video_editor emotions <project> --json
```

Writes a mood per clip plus all six scores. `--backend face` is much better
but needs `pip install fer` — **ask before installing anything**.

Under `--json` the correction pass is skipped. If the user wants a clip moved,
edit `project.json` (see below) or tell them to run it without `--json`.

### 5. render — make the film

```bash
python -m video_editor render <project> --audio mix --json
```

| `--audio` | Result |
|---|---|
| `music` | song only — clean montage |
| `mix` | song over the original sound — vows, laughter, dhol underneath |
| `original` | no song |
| `silent` | no audio |

Leave `--audio` off and the preset chooses (a party gets `music`, a wedding
gets `mix`).

**Always `--dry-run` first on a long film**, show the user the plan, and only
then render. Rendering takes roughly real time and overwrites the previous
output.

---

## Reading state

```bash
python -m video_editor status <project> --json    # where am I
python -m video_editor plan <project> --json      # the film as data
python -m video_editor list --json                # every project
python -m video_editor presets --json             # every kind of event
```

`status --json` returns:

```json
{
  "project": "priya-rahul-marriage",
  "preset": "marriage",
  "target_duration": 360.0,
  "clips": 24,
  "selected_duration": 331.0,
  "render_duration": 336.4,
  "arranged": true,
  "music": {"file": "03_music/song.mp3", "bpm": 128.0, "snap": "bar"},
  "by_segment": {"baraat": 4, "pheras": 3},
  "by_emotion": {"fun": 7, "emotional": 3},
  "steps_done": ["select", "arrange", "music"],
  "next_step": "emotions",
  "output": {}
}
```

`next_step` tells you what to run next. When it is `null`, the film is done.

Errors also come back as JSON, so you never have to parse prose:

```json
{"error": "no project at wedding-2", "error_type": "ProjectError"}
```

Exit codes: `0` fine, `1` step failed, `2` bad input, `3` ffmpeg missing,
`130` cancelled.

---

## Editing by hand

`project.json` is the single source of truth and is meant to be edited. To
change something the CLI has no flag for — nudge an in-point, fix a label,
move a clip to another segment — edit the JSON and re-run the step that cares.

```jsonc
// projects/<slug>/project.json
"clips": [
  {
    "id": "c007",
    "source": "D:/wedding/full_day.mp4",
    "source_in": 764.2,          // ← nudge the in-point
    "source_out": 781.5,
    "segment": "varmala",        // ← re-file it; then re-run arrange
    "emotion": "romantic",       // ← correct the mood directly
    "label": "garland moment",
    "order": 9,
    "beat_duration": 17.156      // ← delete this and re-run music to re-snap
  }
]
```

Rules when you edit it:

- Keep `source_out` greater than `source_in`.
- `segment` must be one of the preset's segments (`presets --json` lists them).
- `emotion` must be one of: happy, emotional, romantic, fun, ritual, calm.
- Delete `head_hash`/`tail_hash` to force re-fingerprinting, or pass `--rehash`.
- After editing, re-run the affected step — the manifest alone changes nothing.

---

## Adding a new kind of event

Presets are data. A naming ceremony, a graduation, a product launch: write one
file, no code.

```bash
cat > config/presets/naming_ceremony.json <<'JSON'
{
  "name": "naming_ceremony",
  "title": "Naming ceremony",
  "description": "A namkaran: the prayer, the name, the family.",
  "target_minutes": 3.0,
  "segments": [
    {"id": "decor",   "mood": "calm",   "keywords": ["decor", "setup"]},
    {"id": "prayer",  "mood": "ritual", "keywords": ["prayer", "pooja"]},
    {"id": "naming",  "mood": "happy",  "keywords": ["name", "naming"], "required": true},
    {"id": "family",  "mood": "happy",  "keywords": ["family", "guests"]}
  ],
  "emotion_arc": ["calm", "ritual", "happy", "emotional"],
  "pacing": {"min_clip_seconds": 2.0, "max_clip_seconds": 10.0, "snap": "bar"},
  "audio": {"mode": "mix", "music_volume": 0.85, "original_volume": 0.3},
  "autodetect": {"scene_threshold": 0.3, "min_gap_seconds": 4.0, "prefer_loud": false}
}
JSON
python -m video_editor presets --json   # it is now a preset
```

Validate it that way before telling the user it worked — a bad file is skipped
with a warning on stderr, not loaded.

---

## Rules for you

1. **Never render without showing the plan first** on anything over a minute.
   `--dry-run`, show it, then ask.
2. **Never install packages** (`fer`, anything) without asking.
3. **Never delete or move the user's footage.** This tool only reads it. If a
   source path is wrong, fix the path in `project.json` — do not touch files.
4. **Never invent a song.** No `--song`, no music step.
5. **Do not claim the tool read faces or understood a moment.** It measured
   light, motion and sound. Say that.
6. **A low score is information, not a problem to hide.** If the detector is
   unsure or the beat is weak, tell the user.
7. **Re-running a step is free.** If a result looks wrong, change a flag and
   run it again rather than editing around it.
8. The only destructive operation in the whole tool is `render` overwriting
   its own output. Everything else can be re-run safely.

---

## When something is wrong

| Message | What to do |
|---|---|
| `ffmpeg not found on PATH` | Tell the user to install ffmpeg. Do not work around it |
| `no moments found` | Lower `--threshold`; if still nothing, the footage needs manual selection |
| `original source is gone` | The footage moved. Fix `source` in `project.json` |
| `the preset ... is not installed` | `config/presets` is missing. Check you are in the repo root |
| `needs an answer, but --json ... cannot ask` | You used an interactive-only mode. Pass the value as a flag |
| `a project already lives in ...` | Pick another `--name`, or work with the existing project |
| `weak pulse` warning | Say so; suggest `--snap beat` or another song |

---

## Repo map

```
src/video_editor/
  cli.py        every command, JSON output, exit codes
  project.py    the project folder and project.json (schema 2)
  presets.py    event types, loaded from config/presets/*.json
  detect.py     automatic moment finding (scene cuts + audio peaks)
  beats.py      tempo and beat grid
  emotion.py    mood scoring, both backends
  probe.py      ffmpeg/ffprobe wrappers, frame fingerprints
  timecode.py   timestamp parsing
  ui.py         prompts, tables, quiet mode
  steps/        select, arrange, music, emotions, render
config/presets/ one JSON file per kind of event
docs/           AGENT_GUIDE.md, USAGE.md, FOLDERS.md, HOW_IT_WORKS.md
scripts/        make_sample_footage.sh, run_sample_pipeline.sh
```

`docs/HOW_IT_WORKS.md` explains the algorithms if you need to reason about why
a result came out the way it did.

---

## Try it with no footage

```bash
bash scripts/make_sample_footage.sh
PYTHONPATH=src python -m video_editor run sample/footage \
  --name "Demo" --preset party --minutes 1 --song sample/song.m4a --json
```

That builds synthetic footage with ffmpeg and runs all five steps. Use it to
check your commands work before touching a user's real wedding footage.
