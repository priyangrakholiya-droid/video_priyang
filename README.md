# video_editor

A five-step editor for **event films** — marriage, engagement, party, baby
shower, birthday, anniversary. Point it at raw footage; it finds the moments,
puts them in order, cuts them to the beat of a song, reads the mood of each
one, and renders the film.

```
raw footage → 1 SELECT → 2 ARRANGE → 3 MUSIC → 4 EMOTIONS → 5 RENDER → your film
              find the    what order  cut to    sort by       merge
              moments                 the beat  feeling
```

### The rule that shapes everything

> A clip is a **reference** — a file path plus an in and out point. No footage
> is ever copied, cut or duplicated into a project. Only one video file is
> ever written: the finished film.

A project folder is therefore a few hundred kilobytes of JSON no matter how
much footage you give it, every step runs in seconds, changing your mind is
free, and the final render goes straight back to the original frames — losing
nothing to an intermediate encode.

- **Nothing to `pip install`.** Standard library only.
- **One external tool:** ffmpeg (which ships ffprobe).
- **Drivable by an agent:** `--json` on every command. See [CLAUDE.md](CLAUDE.md).
- **Event types are data:** a new kind of event is one JSON file, not code.

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [The five steps](#the-five-steps)
- [Event presets](#event-presets)
- [What a project looks like](#what-a-project-looks-like)
- [Every command](#every-command)
- [Driving it from an agent](#driving-it-from-an-agent)
- [How the clever bits work](#how-the-clever-bits-work)
- [Honest limits](#honest-limits)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)

---

## Install

**1. Python 3.10 or newer**

**2. ffmpeg** — the only dependency.

| System | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |

**3. This repo**

```bash
git clone https://github.com/priyangrakholiya-droid/video_priyang.git
cd video_priyang
export PYTHONPATH=src            # Windows PowerShell: $env:PYTHONPATH="src"
python -m video_editor doctor
```

`doctor` tells you whether this machine can actually cut a film:

```
  check                    state  detail
  ffmpeg                   ok     /usr/bin/ffmpeg
  ffprobe                  ok     /usr/bin/ffprobe
  python                   ok     3.13.5
  presets                  ok     7 loaded: anniversary, baby_shower, birthday, ...
  face backend (optional)  ok     not installed - `pip install fer` to enable
  [ok] ready
```

Prefer a real command instead of `PYTHONPATH`:

```bash
pip install -e .
video-editor doctor
```

---

## Quick start

### Try it with no footage at all

```bash
bash scripts/make_sample_footage.sh
bash scripts/run_sample_pipeline.sh
```

That generates synthetic footage and a 120 BPM track with ffmpeg, then runs all
five steps and checks a real film came out.

### A real wedding, hands-off

```bash
python -m video_editor run "D:/wedding/full_day.mp4" \
  --name "Priya & Rahul Marriage" --preset marriage --minutes 6 \
  --song "D:/music/song.mp3"
```

### A real wedding, step by step

```bash
python -m video_editor select  "D:/wedding/full_day.mp4" --preset marriage --minutes 6
python -m video_editor arrange priya-rahul-marriage --mode story
python -m video_editor music   priya-rahul-marriage --song "D:/music/song.mp3"
python -m video_editor emotions priya-rahul-marriage
python -m video_editor render  priya-rahul-marriage --audio mix
```

At any point:

```bash
python -m video_editor status priya-rahul-marriage    # where am I
python -m video_editor plan   priya-rahul-marriage    # the film as data
python -m video_editor list                           # every project
```

---

## The five steps

### Step 1 — `select`: find the moments

Point it at **one long recording or a folder of clips** — it detects which.

```bash
python -m video_editor select "D:/wedding/full_day.mp4" --preset marriage --minutes 6
```

**`--mode auto` (default) scans the footage for you.** It looks for shot
changes and loud moments, scores each candidate, spreads them out so the film
does not take six clips from the same minute, and proposes enough to fill your
target length:

```
Scanning the footage for moments
  . looking for shot changes and loud moments - no footage is written, this only reads
  [1/1] full_day.mp4

  id    source          in            length  segment  score  why
  c001  full_day.mp4    00:04:20.000  8s      baraat   0.76   scene 0.74, loudness 0.79 -> score 0.76
  c002  full_day.mp4    00:12:40.000  10s     varmala  0.93   scene 1.00, loudness 0.79 -> score 0.93
  [####################........] 4m 31s of 6m 00s  (75%)
```

Tuning:

| Symptom | Fix |
|---|---|
| Too few moments | `--threshold 0.15` (more sensitive) |
| Too many, too similar | `--threshold 0.45 --min-gap 10` |
| All from one part of the day | raise `--min-gap` |

**`--mode manual` takes typed in/out points** instead, with a progress bar
against your target:

| Input | Meaning |
|---|---|
| `1:30 1:48` | that range out of the source |
| `3 1:30 1:48` | from file #3 (when you gave a folder) |
| `3` | the whole of file #3 |
| `1:30 1:48 #haldi` | file it under the haldi segment |
| `1:30 1:48 "ring close-up"` | label it |
| `list` `files` `segments` `undo` `drop c003` `help` `done` | commands |

Timestamps accept `90`, `1:30`, `00:01:30.5` or `1h2m3s`.

Either way, the result is `01_selection/selection.json` — references, no video.

### Step 2 — `arrange`: which clip follows which

```bash
python -m video_editor arrange my-wedding --mode story
```

The edge frames are read straight out of the original footage and turned into
64-bit fingerprints, so the tool can tell you how each cut will look:

```
  #  id    at            length  segment  emotion    cut into it    what it is
  1  c001  00:00:00.000  18s     baraat   fun        -              groom arriving
  2  c005  00:00:18.000  12s     baraat   fun        9/64 smooth    dhol players
  3  c009  00:00:30.000  22s     varmala  romantic   31/64 JUMP     garland
  . 23 cuts: 14 smooth, 3 visible jumps, average 18.2/64
```

| Mode | What it does |
|---|---|
| **`story`** | the preset's ceremony order, frame-matched inside each part. **Use this.** |
| `match` | pure frame matching — smoothest possible cuts, ignores chronology |
| `emotion` | the preset's emotional arc; run step 4 first |
| `manual` | you type the order: `c003 c001 c004` |

### Step 3 — `music`: cut to the beat

```bash
python -m video_editor music my-wedding --song "song.mp3" --snap bar
```

It detects the tempo and rounds **every clip to a whole number of beats**, so
cut 1 ends exactly as a beat lands and cut 2 starts there:

```
  [ok] 128.0 BPM  (beat every 0.469s, first beat at 0.212s, 512 beats, strong pulse)
  . one bar = 4 beat(s) = 1.875s at 128.0 BPM

  #  id    was   now   change  holds     starts at
  1  c001  18s   17s   -0.75s  36 beats  00:00:00.000
  2  c005  12s   13s   +0.88s  28 beats  00:00:16.875
  [ok] fits inside the song with 24s to spare
```

| `--snap` | Cut lands every | Good for |
|---|---|---|
| `beat` | 1 beat | fast dance montage, sangeet |
| `half-bar` | 2 beats | general — party and birthday default |
| `bar` | 4 beats | most event films — wedding default |
| `two-bar` | 8 beats | slow romantic holds — anniversary default |

A clip that needs to grow pulls extra frames from the original source, so
snapping never costs you footage you chose. `--fit both` trims whole beats off
the longest clips until the film fits inside both the song and your target.

### Step 4 — `emotions`: read the mood

```bash
python -m video_editor emotions my-wedding
```

Scores each clip across six feelings and records all six, not just the winner:

```
  id    emotion    length  segment  top scores               what it is
  c001  fun        17s     baraat   fun 38%, happy 27%       groom arriving
  c019  emotional  14s     vidaai   emotional 41%, calm 19%  mother

  emotion    clips  runtime  clip ids
  fun        7      1m 44s   c001 c005 c011 ...
  emotional  3      48s      c019 c021 c022
```

Close calls are flagged, and the tool offers a correction pass. Results land in
`04_emotion/scores.json` (every score), `groups.json` (the clip ids per
feeling) and `emotions.csv`.

`--backend face` uses a real facial-expression model instead of the energy
heuristic — much better, needs `pip install fer`.

### Step 5 — `render`: make the film

```bash
python -m video_editor render my-wedding --audio mix
```

Cuts every clip **from the original source**, normalises to one size and frame
rate, joins, lays the song underneath starting on its **first beat**, fades in
and out.

```
  clips            24
  runtime          5m 36s
  size             1920x1080
  audio            mix
  music starts at  0.212s (first beat)

Render 5m 36s now? [Y/n]:
```

| `--audio` | What you hear |
|---|---|
| `music` | the song only — clean montage |
| `mix` | the song over the original sound — vows, laughter, dhol underneath |
| `original` | no song |
| `silent` | no audio track |

Leave `--audio` off and the preset decides. `--dry-run` shows the plan without
encoding.

---

## Event presets

```bash
python -m video_editor presets
```

```
  name         title                       target  segments  snap      audio
  anniversary  Anniversary                 4m      8         two-bar   mix
  baby_shower  Baby shower                 4m      9         bar       mix
  birthday     Birthday                    3m      8         half-bar  mix
  engagement   Engagement / ring ceremony  4m      8         bar       mix
  general      General purpose             5m      5         bar       mix
  marriage     Marriage / wedding film     6m      13        bar       mix
  party        Party / celebration         3m      8         half-bar  music
```

A preset sets the segments and their order, the emotional arc, how long a clip
may be, the beat snapping, the audio mix, and how hard the detector looks.

| Preset | Segments |
|---|---|
| `marriage` | mehndi, haldi, baraat, welcome, varmala, pheras, rituals, couple_portraits, family, vidaai, reception, dance, candid |
| `engagement` | arrival, ring_exchange, couple_portraits, family, speeches, cake_and_toast, dance, candid |
| `party` | setup, arrivals, toast, food, games, dance, crowd, goodbyes |
| `baby_shower` | decor, arrivals, mother_to_be, reveal, blessings, games, gifts, cake, guests |
| `birthday` | decor, arrivals, cake_cutting, song, gifts, games, family, candid |
| `anniversary` | opening, couple, memories, family, speeches, cake, dance, closing |

`python -m video_editor presets --verbose` shows each segment's mood and the
file-name keywords it matches — a file called `haldi_cam2.mp4` is filed under
haldi automatically.

### Adding your own event type

It is a data file, not code. Drop this in `config/presets/`:

```json
{
  "name": "naming_ceremony",
  "title": "Naming ceremony",
  "description": "A namkaran: the prayer, the name, the family.",
  "target_minutes": 3.0,
  "segments": [
    {"id": "prayer", "mood": "ritual", "keywords": ["prayer", "pooja"]},
    {"id": "naming", "mood": "happy", "keywords": ["name"], "required": true},
    {"id": "family", "mood": "happy", "keywords": ["family", "guests"]}
  ],
  "emotion_arc": ["calm", "ritual", "happy", "emotional"],
  "pacing": {"min_clip_seconds": 2.0, "max_clip_seconds": 10.0, "snap": "bar"},
  "audio": {"mode": "mix", "music_volume": 0.85, "original_volume": 0.3},
  "autodetect": {"scene_threshold": 0.3, "min_gap_seconds": 4.0, "prefer_loud": false}
}
```

```bash
python -m video_editor presets          # it is now listed
```

---

## What a project looks like

Definitions, not video:

```
projects/priya-rahul-marriage/
  project.json          every decision — the single source of truth
  edit.json             the portable edit plan (references + timings)
  01_selection/
    selection.json      which stretches of footage, and why each was chosen
  02_arrangement/
    order.json          the running order, with a join cost per cut
    cuts.csv            the same thing for a spreadsheet
  03_music/
    song.mp3            your song, copied in so the project travels alone
    beats.txt           every beat time
    beat_sheet.csv      which beat each clip starts on
  04_emotion/
    scores.json         all six scores per clip
    groups.json         the clip ids in each feeling
    emotions.csv        for a spreadsheet
  05_output/
    priya-rahul-marriage_final.mp4      ← the only video in the whole project
    render_plan.csv                     what went in, in order
```

A 24-clip wedding project is about 700 KB — nearly all of it the copied song.
`project.json` is meant to be edited by hand; see
[docs/FOLDERS.md](docs/FOLDERS.md) for every field.

---

## Every command

```
python -m video_editor select   <footage>  [--mode auto|manual] [--preset E] [--minutes M]
                                           [--threshold T] [--min-gap G] [--name N]
python -m video_editor arrange  [project]  [--mode story|match|emotion|manual]
                                           [--first ID] [--rehash] [--yes]
python -m video_editor music    [project]  [--song S] [--snap beat|half-bar|bar|two-bar]
                                           [--fit song|target|both]
python -m video_editor emotions [project]  [--backend heuristic|face] [--force]
                                           [--no-review] [--no-prior]
python -m video_editor render   [project]  [--audio music|mix|original|silent]
                                           [--size WxH] [--crf N] [--dry-run] [--yes]
python -m video_editor run      <footage>  all five steps, unattended
python -m video_editor status   [project]  where a project stands
python -m video_editor plan     [project]  the edit plan
python -m video_editor list                every project
python -m video_editor presets  [-v]       every kind of event
python -m video_editor doctor              is this machine ready?
```

`[project]` takes a path **or** just the name. Leave it out and it uses the
only project you have. Every command takes `--json`, `--projects-dir` and
`--presets-dir`.

---

## Driving it from an agent

Every command takes `--json`: human output is silenced, one JSON document is
printed, and **no question is ever asked** — so a step cannot hang waiting for
input an agent cannot give.

```bash
python -m video_editor run footage/ --preset party --minutes 3 --song song.mp3 --json
```

```json
{
  "project": "demo",
  "preset": "party",
  "clips": 5,
  "render_duration": 34.745,
  "music": {"file": "03_music/song.m4a", "bpm": 120.88, "snap": "half-bar"},
  "by_emotion": {"fun": 3, "calm": 2},
  "steps_done": ["select", "arrange", "music", "emotions", "render"],
  "next_step": null,
  "rendered": "projects/demo/05_output/demo_final.mp4"
}
```

Errors are JSON too, so nothing needs prose parsing:

```json
{"error": "no project at wedding-2", "error_type": "ProjectError"}
```

Exit codes: `0` fine, `1` step failed, `2` bad input, `3` ffmpeg missing,
`130` cancelled.

**[CLAUDE.md](CLAUDE.md) is the full agent brief** — the recipe, the tuning
table, what to edit by hand, and the rules (never render without showing the
plan, never install packages unasked, never claim it read faces).
[videoeditor.json](videoeditor.json) is the machine-readable manifest of the
pipeline, its settings and its limits.

---

## How the clever bits work

| Part | In one line |
|---|---|
| **Moment finding** | ffmpeg's `select` filter reports scene scores; the audio is reduced to a loudness curve; each shot boundary is scored on both, then spread out and ranked |
| **Beat detection** | ffmpeg reduces the song to a 23 ms loudness envelope; differencing gives onset strength; autocorrelation gives the tempo; a comb filter gives the phase |
| **Frame matching** | each edge frame becomes a 9×8 greyscale difference hash (64 bits); the cost of a cut is the Hamming distance; ordering is a greedy nearest-neighbour walk |
| **Mood scoring** | `signalstats` gives brightness, saturation, hue and inter-frame difference; the audio envelope gives loudness and its swing; six weighted sums produce the six scores |

Beat detection is verified against generated click tracks: 120 BPM reads as
120.9, 100 as 99.7. Scene detection is verified against footage with cuts at
known times.

[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) explains all four properly,
including why there is no librosa, numpy or OpenCV.

---

## Honest limits

- **The mood step does not read faces.** The default backend reads energy,
  light and sound. It sorts a dance floor from a ceremony from b-roll well, and
  it will misfile a tearful goodbye shot in bright sunshine. `--backend face`
  with `pip install fer` reads real expressions; the review pass exists for
  both.
- **Automatic moment finding uses proxies.** Picture change and loudness are
  not the same thing as "interesting". It does not know what is in the frame.
- **Beat detection needs a beat.** Free-tempo music, a solo instrument or
  speech produce a `weak pulse` warning rather than a confident wrong answer.
- **The beat grid is rigid.** A live recording that drifts in tempo will drift
  off the grid late in a long film. `--snap beat` reduces the drift per cut.
- **Rendering re-encodes once.** Expect roughly real-time encoding at the
  default `veryfast` preset.
- **Sources must stay put.** A project stores paths. Move your footage and the
  render fails with `original source is gone` — fix the path in `project.json`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found on PATH` | Install ffmpeg, then open a **new** terminal |
| `No module named video_editor` | `export PYTHONPATH=src`, or `pip install -e .` |
| `no moments found` | The footage is one static shot. `--threshold 0.1`, or use `--mode manual` |
| `no video files in <folder>` | Check the extension: mp4, mov, mkv, avi, m4v, webm, mpg, wmv, flv, mts, m2ts, 3gp, ts |
| `original source is gone` | The footage moved. Fix `source` in `project.json` |
| `the preset ... is not installed` | Run from the repo root, or pass `--presets-dir` |
| `needs an answer, but --json ... cannot ask` | An interactive-only mode under `--json`. Pass the value as a flag |
| Cuts feel slightly off the beat | The song drifts in tempo. Try `--snap beat` |
| Emotions all in one bucket | Normal for footage shot in one room at one brightness. `--backend face`, or correct them in the review pass |
| Render is slow | `--x264-preset ultrafast --crf 23`, or `--size 1280x720` |

---

## Tests

124 tests, standard library only, no network, **no media checked in** — the
tests that need audio or video build it with ffmpeg and clean up after
themselves.

```bash
export PYTHONPATH=src
python -m unittest discover -s tests -t . -v
bash scripts/run_sample_pipeline.sh      # end-to-end
```

CI runs both on Linux and Windows, on Python 3.10 and 3.13.

---

## Licence

MIT — see [LICENSE](LICENSE). ffmpeg is a separate work under its own licence
and is not bundled; see [NOTICE](NOTICE).
