# Usage — a full walkthrough

The long version of the README's quick start: one real event, from a card full
of footage to a finished film. Follow it top to bottom the first time.

For driving the tool from an agent instead, see [../CLAUDE.md](../CLAUDE.md)
and [AGENT_GUIDE.md](AGENT_GUIDE.md).

---

## Before you start

```bash
export PYTHONPATH=src            # PowerShell: $env:PYTHONPATH="src"
python -m video_editor doctor
```

That must say `ready`. If ffmpeg is missing, install it and open a **new**
terminal.

You need room for the finished film — 400–700 MB for a six minute 1080p film,
plus a few GB of headroom while rendering. You do **not** need room for the
footage a second time: nothing is copied.

---

## Step 1 — select

Point it at **one long recording or a folder of clips**. It works out which.

```bash
python -m video_editor select "D:/wedding/full_day.mp4"
python -m video_editor select "D:/wedding/cards/cam-a/"
```

```
Reading 1 file(s)
  [1/1] full_day.mp4

Source footage
  #  file          length   size       fps  audio
  1  full_day.mp4  2h 14m   1920x1080  30   yes
  . 1 file(s), 2h 14m of footage in total
```

### The three questions

```
Project name [Full Day]: Priya & Rahul Marriage

What kind of event is this?
  1. anniversary
  2. baby_shower
  3. birthday
  4. engagement
  5. general
  6. marriage (default)
  7. party
Choice [marriage]: marriage
  . preset: Marriage / wedding film - A full wedding, ceremony order from
    mehndi through to the reception.

Target length
  . you have 2h 14m of footage
How many minutes should the finished video be? [6]: 6
```

The preset decides the segments, the pacing, the default beat snapping and the
audio mix. The minutes answer is what everything else is measured against.

Skip the questions with flags:

```bash
python -m video_editor select "D:/wedding/full_day.mp4" \
  --name "Priya & Rahul Marriage" --preset marriage --minutes 6
```

### Then: auto or manual

```
How should the clips be chosen?
  1. auto (default)
  2. manual
```

#### auto — let it find the moments

```
Scanning the footage for moments
  . looking for shot changes and loud moments - no footage is written, this only reads
  [1/1] full_day.mp4

What the scan found
  file          candidate moments
  full_day.mp4  214

  [ok] proposed 23 clip(s)
  id    source        in            length  segment  score  why
  c001  full_day.mp4  00:04:20.000  12s     baraat   0.76   scene 0.74, loudness 0.79 -> score 0.76
  c002  full_day.mp4  00:12:40.000  14s     varmala  0.93   scene 1.00, loudness 0.79 -> score 0.93
  ...
  [###########################.] 5m 48s of 6m 00s  (97%)

Adjust this selection by hand? [y/N]:
```

The `why` column is the detector showing its working. Answer `y` and you drop
into the manual editor with those clips already loaded, so you can remove the
wrong ones and add what it missed.

If the first scan is wrong, it costs seconds to redo. Delete the project
folder and run again with:

| Symptom | Fix |
|---|---|
| Too few moments | `--threshold 0.15` |
| Too many, all alike | `--threshold 0.45 --min-gap 10` |
| Everything from one hour of the day | raise `--min-gap` |
| `no moments found` | one static shot — `--threshold 0.1`, or go manual |

#### manual — type the moments

```
select [0 clips]: 4:20 4:38 #baraat "groom arriving"
  [ok] c001: full_day.mp4 00:04:20.000 -> 00:04:38.000 (18s)  #baraat
  [...........................] 18s of 6m 00s  (5%)
  . 5m 42s still to fill
```

With a folder, start the line with the file number:

```
select [1 clips]: 3 1:05 1:23 #varmala "garland"
select [2 clips]: 7
  [ok] c003: MVI_0027.mp4 00:00:00.000 -> 00:00:42.000 (42s)
```

| Input | Meaning |
|---|---|
| `1:30 1:48` | that range out of the single source |
| `3 1:30 1:48` | that range out of file #3 |
| `3` | the whole of file #3 |
| `1:30 1:48 #haldi` | file it under the haldi segment |
| `1:30 1:48 "ring close-up"` | label it |
| `list` | the clips so far, with the progress bar |
| `files` | the source inventory again |
| `segments` | the segment names for this preset |
| `undo` / `drop c003` | remove one |
| `done` / `quit` | finish / leave without saving |

Timestamps: `90`, `1:30`, `00:01:30.5`, `1h2m3s`. `90:00` means ninety minutes.

Tagging with `#` is optional but worth it: it is what makes step 2's `story`
mode work. Prefixes are enough — `#var` finds `varmala` — and keywords work
too: `#garland` also finds `varmala`.

### What you end up with

```
STEP 1 DONE
  [ok] 23 clip(s) selected, 5m 48s
  . written to 01_selection\selection.json (references, no video)
```

No footage was touched. You can close the terminal safely.

---

## Step 2 — arrange

```bash
python -m video_editor arrange priya-rahul-marriage
```

```
How should the clips be ordered?
  1. story (default)
  2. match
  3. emotion
  4. manual
```

**Use `story` for any event.** It walks the preset's segments in order —
mehndi, haldi, baraat, varmala, pheras, vidaai, reception — and frame-matches
inside each one.

```
Reading the edge frames of 23 clip(s)
  . two frames per clip, read in place from the original footage

The running order
  #  id    at            length  segment  emotion  cut into it   what it is
  1  c001  00:00:00.000  18s     baraat   -        -             groom arriving
  2  c005  00:00:18.000  12s     baraat   -        9/64 smooth   dhol players
  3  c009  00:00:30.000  22s     varmala  -        31/64 JUMP    garland
  . 22 cuts: 14 smooth, 3 visible jumps, average 18.2/64
  . total runtime: 5m 48s

Keep this order? [Y/n]:
```

`cut into it` is how many of 64 fingerprint bits differ between the previous
clip's last frame and this clip's first frame. Under 14 reads as smooth, over
26 as a visible jump. A few jumps between segments are normal and often
desirable.

Not happy? Answer `n` and run again with another mode — nothing is written
until you say yes.

| Mode | When |
|---|---|
| `story` | any event; chronology plus smooth joins |
| `match` | chronology does not matter, you want the smoothest cuts |
| `emotion` | you want the preset's emotional arc; run step 4 first |
| `manual` | you know the exact order: `order: c001 c005 c012 c009` |

Open the opening shot you want with `--mode match --first c014`.

---

## Step 3 — music

```bash
python -m video_editor music priya-rahul-marriage --song "D:/music/song.mp3"
```

Leave `--song` off and it asks — you can drag the file onto the terminal.

```
  [ok] song copied to 03_music\song.mp3

Listening for the beat
  . this reads the whole song once; a few seconds for a normal track
  [ok] 128.0 BPM  (beat every 0.469s, first beat at 0.212s, 512 beats, strong pulse)

Snap cuts to...
  1. beat
  2. half-bar
  3. bar (default)
  4. two-bar
```

The default comes from the preset: `bar` for a wedding, `half-bar` for a party,
`two-bar` for an anniversary.

| Choice | Cut lands every | Use for |
|---|---|---|
| `beat` | 0.47s at 128 BPM | fast dance montage, sangeet |
| `half-bar` | 0.94s | general |
| `bar` | 1.88s | most event films — lands on the "one" |
| `two-bar` | 3.75s | slow romantic holds, vidaai |

Then every clip is rounded to a whole number of those units:

```
Cuts snapped to the beat
  #  id    was   now   change  holds     starts at
  1  c001  18s   17s   -0.75s  36 beats  00:00:00.000
  2  c005  12s   13s   +0.88s  28 beats  00:00:16.875
  . runtime 5m 48s -> 5m 52s
  [ok] fits inside the song with 18s to spare
  . 8s over your 6m 00s target
```

A clip that needs to grow pulls extra frames from the original source, so
snapping never costs you footage you chose — another thing the reference-only
design makes free.

**Making it fit:**

```bash
python -m video_editor music priya-rahul-marriage --song song.mp3 --fit both
```

`--fit song` keeps it inside the song, `--fit target` inside your target
length, `--fit both` inside whichever is shorter. It shaves whole beats off the
longest clips first, so the rhythm survives.

**A weak pulse** gets a warning rather than a confident wrong answer:

```
  [!] the pulse is weak - a soft or free-tempo song. Check the beat sheet
      before you trust the cuts.
```

Check `03_music/beat_sheet.csv`. It has two time columns —
`starts_at` (in the film) and `song_time` (in the song file) — which differ by
the song's lead-in. Step 5 shifts the song by that amount so beat one lands at
00:00:00 of the film.

---

## Step 4 — emotions

```bash
python -m video_editor emotions priya-rahul-marriage
```

```
Reading 23 clip(s) with the heuristic backend
  . each clip is measured in place, inside the original footage
  [1/23] c001 groom arriving
  .    fun  (fun 38%, happy 27%, calm 14%)
  [2/23] c005 dhol players
  [!]     happy  (close call: happy 24%, fun 23%, ritual 19%)
```

`[!]` means the top two scores were within 15% — the tool is guessing, and
says so. It offers a correction pass:

```
Correct any of these by hand? [y/N]: y
review: c005 fun
  [ok] c005 -> fun
review: done
```

Results:

```
Totals per emotion
  emotion    clips  runtime  clip ids
  fun        7      1m 44s   c001 c005 c011 c012 c015 c018 c023
  happy      5      1m 12s   c003 c004 c008 c013 c020
  emotional  3      48s      c019 c021 c022
  romantic   4      1m 03s   c007 c009 c010 c016
  ritual     3      39s      c014 c017 c006
  calm       1      18s      c002
```

Those are clip ids, and `04_emotion/groups.json` holds the same thing as data.
To watch all the emotional moments, look up those ids in `project.json` and you
have the file and the timecode. **Nothing was copied to make this** — which is
why the step takes seconds and costs no disk.

`04_emotion/emotions.csv` has every score for every clip, so you can sort by
`emotional` descending in a spreadsheet and get your montage order.

### A segment nudges the mood

A clip tagged `#vidaai` leans emotional, `#dance` leans fun, because the preset
says that is what those parts of a wedding feel like. It is a 15% nudge, not an
override — bright happy footage in the vidaai can still score happy. Turn it
off with `--no-prior`.

### A better backend

The default reads energy, not faces:

```bash
pip install fer
python -m video_editor emotions priya-rahul-marriage --backend face --force
```

Much better, considerably slower (six frames per clip through a model), and a
large install — opencv and tensorflow.

---

## Step 5 — render

```bash
python -m video_editor render priya-rahul-marriage --dry-run
```

Always look at the plan first:

```
Render plan
  clips            23
  runtime          5m 52s
  size             1920x1080
  frame rate       30 fps
  audio            mix
  song             song.mp3
  music starts at  0.212s (first beat)
  quality          crf 19, preset veryfast
  fades            1.5s in and out
```

Then render:

```bash
python -m video_editor render priya-rahul-marriage --audio mix
```

| `--audio` | What you hear |
|---|---|
| `music` | the song only — clean montage |
| `mix` | the song over the original sound — vows, laughter, dhol underneath |
| `original` | no song |
| `silent` | no audio track |

Leave it off and the preset decides. Every clip is cut **from the original
source**, so the film is encoded exactly once.

```
DONE - YOUR FILM IS READY
  [ok] projects\priya-rahul-marriage\05_output\priya-rahul-marriage_final.mp4
  . 5m 52s, 1920x1080, 30 fps, 487.2 MB
  . you asked for 6m 00s and got 5m 52s (-8s)
```

Smaller and faster: `--size 1280x720 --crf 23 --x264-preset ultrafast`.
Best quality: `--crf 17 --x264-preset slow`.

---

## Keeping track

```bash
python -m video_editor status priya-rahul-marriage
python -m video_editor plan   priya-rahul-marriage
python -m video_editor list
```

```
  step      state
  select    done
  arrange   done
  music     done
  emotions  done
  render    -
  . next:  python -m video_editor render "projects/priya-rahul-marriage"
```

---

## Changing your mind

Every step is re-runnable and only rewrites its own folder. Because nothing is
encoded until step 5, re-running any of steps 1–4 costs seconds.

| You want to | Do this |
|---|---|
| Different order | `arrange --mode match` |
| Different song | `music --song other.mp3` — every clip is re-snapped |
| Re-score emotions | `emotions --force` |
| Nudge one clip's in-point | edit `source_in` in `project.json`, delete its `beat_duration`, re-run `music` |
| Move a clip to another segment | edit `segment`, re-run `arrange` |
| Drop a clip | delete it from `clips` in `project.json`, re-run `arrange` |
| Add more clips | run `select` again as a new project, or add entries to `clips` by hand |
| Re-render | `render` — it overwrites the output |

`project.json` is plain, readable JSON and editing it by hand is a supported
way to work. [FOLDERS.md](FOLDERS.md) documents every field and which step to
re-run after changing it.

---

## Running it unattended

Every question has a flag, so the whole job fits in one command:

```bash
python -m video_editor run "D:/wedding/full_day.mp4" \
  --name "Priya Marriage" --preset marriage --minutes 6 \
  --mode auto --arrange-mode story \
  --song "D:/music/song.mp3" --snap bar --fit both \
  --audio mix
```

Add `--json` and it prints one JSON document instead of all the tables, and
never asks anything. `scripts/run_sample_pipeline.sh` is exactly that, against
generated footage.
