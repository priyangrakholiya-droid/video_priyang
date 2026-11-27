# Agent guide — the machine interface

[CLAUDE.md](../CLAUDE.md) is the brief: what to run, in what order, and the
rules. This file is the reference: the exact shape of everything the tool
reads and writes.

---

## Why this tool is agent-friendly

Three properties, each a deliberate choice:

1. **Every command takes `--json`.** Human output is suppressed, one JSON
   document goes to stdout, warnings go to stderr. stdout is always parseable.
2. **`--json` never asks a question.** Any step that would need an answer
   fails with a clear error instead of hanging on a prompt nobody can answer.
3. **The state is a document.** `project.json` holds every decision, is
   readable, and is meant to be edited. There is no hidden database and no
   binary state.

A fourth falls out of the reference-only design: **every step is cheap to
re-run**, so the correct response to a bad result is another command, not a
workaround.

---

## Invocation

```bash
# From a clone
PYTHONPATH=src python -m video_editor <command> [options] --json

# After `pip install -e .`
video-editor <command> [options] --json
```

Global options, accepted by every command:

| Option | Meaning |
|---|---|
| `--json` | one JSON document on stdout, no questions |
| `--projects-dir PATH` | where projects live (default `./projects`) |
| `--presets-dir PATH` | where event presets live (default `./config/presets`) |

---

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | continue |
| 1 | a step failed | read `.error`; usually a render or source problem |
| 2 | bad input | read `.error`; fix the arguments |
| 3 | ffmpeg is missing | stop; ask the user to install ffmpeg |
| 130 | cancelled, or a question could not be asked | pass the value as a flag |

Every non-zero exit under `--json` still prints a document:

```json
{"error": "no project at wedding-2", "error_type": "ProjectError"}
```

`error_type` is one of `ProjectError`, `ProbeError`, `PresetError`,
`BeatError`, `DetectError`, `EmotionError`, `TimecodeError`, `FFmpegMissing`,
`RenderError`, `RuntimeError`.

---

## Commands and their JSON

### `doctor --json`

Run this first, once.

```json
{
  "ready": true,
  "checks": [
    {"check": "ffmpeg", "ok": true, "detail": "/usr/bin/ffmpeg"},
    {"check": "ffprobe", "ok": true, "detail": "/usr/bin/ffprobe"},
    {"check": "python", "ok": true, "detail": "3.13.5"},
    {"check": "presets", "ok": true, "detail": "7 loaded: anniversary, ..."},
    {"check": "face backend (optional)", "ok": true,
     "detail": "not installed - `pip install fer` to enable"},
    {"check": "projects dir", "ok": true, "detail": "/work/projects"}
  ]
}
```

Exits 2 when `ready` is false.

### `presets --json`

Every event type, with its full definition — segments, moods, arc, pacing,
audio and detector settings. Use it to discover valid `--preset` values and
valid `segment` names before writing any into `project.json`.

### The five steps

`select`, `arrange`, `music`, `emotions` and `render` all return the **project
summary** (below). `render` adds `"rendered"`.

### `status --json` — the project summary

The shape returned by every step, and the one to poll between steps:

```json
{
  "project": "priya-rahul-marriage",
  "path": "/work/projects/priya-rahul-marriage",
  "name": "Priya & Rahul Marriage",
  "preset": "marriage",
  "target_duration": 360.0,
  "clips": 24,
  "candidates": 0,
  "selected_duration": 331.0,
  "render_duration": 336.4,
  "arranged": true,
  "music": {"file": "03_music/song.mp3", "bpm": 128.0, "snap": "bar"},
  "by_segment": {"baraat": 4, "varmala": 2, "pheras": 3},
  "by_emotion": {"fun": 7, "happy": 5, "emotional": 3},
  "steps_done": ["select", "arrange", "music", "emotions"],
  "next_step": "render",
  "output": {},
  "updated": "2026-11-27T15:04:11"
}
```

| Field | Use it to |
|---|---|
| `next_step` | decide what to run next; `null` means finished |
| `steps_done` | check a step actually completed |
| `render_duration` vs `target_duration` | tell the user how close the film is to what they asked for |
| `arranged` | whether every clip has a position yet |
| `music` | `null` until step 3 runs; `bpm` is worth reporting |
| `by_emotion` / `by_segment` | describe the film without reading every clip |
| `output.file` | the finished film, relative to `path` |

### `plan --json` — the film as data

The portable edit plan: `starts_at` in the finished film, `source_in` /
`source_out` in the original footage. A complete EDL. Also written to
`<project>/edit.json` on every save.

### `list --json`

```json
{"projects_dir": "/work/projects", "projects": [ <summary>, ... ]}
```

---

## A full session

```bash
set -e
V="python -m video_editor"
export PYTHONPATH=src

$V doctor --json                                        # 1. check the machine

$V select "/footage/wedding" \
   --name "Priya Marriage" --preset marriage --minutes 6 \
   --mode auto --json > state.json                      # 2. find the moments

$V arrange "priya-marriage" --mode story --json         # 3. order them
$V music   "priya-marriage" --song "/music/song.mp3" \
   --snap bar --fit both --json                         # 4. cut to the beat
$V emotions "priya-marriage" --json                     # 5. read the moods
$V render  "priya-marriage" --dry-run --json            # 6. show the plan
# ... confirm with the user here ...
$V render  "priya-marriage" --audio mix --json          # 7. make the film
```

Between any two steps, `status --json` tells you where you are. Nothing is
lost if the session ends — pick up at `next_step`.

---

## Changing a decision

The flags cover the common cases. For anything else, edit `project.json` and
re-run the affected step. The table in
[FOLDERS.md](FOLDERS.md#editing-it-by-hand) says which step to re-run for each
field.

Constraints a write must respect, or the next step will reject it:

- `source_out` > `source_in`, both inside the file's duration
- `segment` ∈ the preset's segment ids (`presets --json`)
- `emotion` ∈ `happy, emotional, romantic, fun, ritual, calm`
- `order` unique across clips, 1-based and contiguous
- `id` unique; `cNNN` by convention
- `source` an absolute path to a readable file

After writing, `status --json` re-reads and validates the manifest. If it
errors, you broke something — the message says what.

---

## Tuning the detector

When the automatic selection is wrong, re-run step 1 with different settings
rather than hand-editing twenty clips. It costs seconds.

| Observation in the result | Change |
|---|---|
| `clips` far below what fills `target_duration` | `--threshold 0.15` |
| Many clips, `by_segment` concentrated in one place | `--min-gap 10` |
| `DetectError: no moments found` | `--threshold 0.1`; then tell the user it needs manual selection |
| Clips too short or too long | set `min_clip_seconds`/`max_clip_seconds` in the preset |

The detector's reasoning is in `01_selection/selection.json` as `notes` and
`score` per clip: `"scene 0.74, loudness 0.79 -> score 0.76"`. Read it before
concluding the tool is wrong.

---

## What the numbers mean

Report these honestly; do not round them into confidence the tool has not got.

| Number | Where | Reading it |
|---|---|---|
| `score` (clip) | selection.json | detector confidence, 0–1. Below ~0.3 is a weak guess |
| `join_cost` | order.json | 0–64 bits of difference. ≤14 smooth, ≥27 a visible jump |
| `statistics.jumps` | order.json | how many cuts will read as jumps |
| `bpm` | beatmap.json | detected tempo |
| `confidence` | beatmap.json | how periodic the song is. Below 0.35 = weak pulse, say so |
| `scores` (emotion) | scores.json | six values summing to 1. Top two within ~15% = a coin toss |

---

## Things that will trip you up

1. **`--mode manual` cannot work under `--json`.** It needs typed timecodes.
   Use `--mode auto`, or write the clips into `project.json` yourself.
2. **The music step is optional and needs a song.** No `--song`, skip it. Do
   not substitute a song of your own choosing.
3. **`render` overwrites its own output.** It is the only destructive thing in
   the tool. `--dry-run` first.
4. **`beat_duration` overrides the clip's own length.** After editing
   `source_out`, delete `beat_duration` and re-run `music`, or the old snapped
   length will be rendered.
5. **Sources are absolute paths.** Moving the footage breaks the render with
   `original source is gone`. Fix the path; never move the user's files.
6. **A preset is cached per presets directory.** Writing a new preset file is
   picked up by the next process, not the current one.
7. **Several projects, no name given** → the command errors under `--json`
   rather than guessing. Pass the project name.
