# Usage — a full walkthrough

This is the long version of the README's quick start: one real wedding, from a
card full of footage to a finished film. Follow it top to bottom the first time.

---

## Before you start

```bash
ffmpeg -version      # must print a version
python --version     # 3.10 or newer
```

Copy your footage somewhere with room to spare. Rendering a five minute film
needs roughly 2–3 GB of working space.

---

## Step 1 — select

You have two situations. The tool handles both; it looks at what you gave it.

### A. One long recording

```bash
python -m video_editor select "D:/wedding/full_day.mp4"
```

```
Reading the footage
-------------------
  [1/1] full_day.mp4

Source footage
--------------
  #  file          length    size       fps  audio
  -  ------------  --------  ---------  ---  -----
  1  full_day.mp4  2h 14m    1920x1080  30   yes
  . 1 file(s), 2h 14m of footage in total
```

### B. A folder of clips

```bash
python -m video_editor select "D:/wedding/cards/cam-a/"
```

```
  #  file           length  size       fps  audio
  1  MVI_0021.mp4   4m 10s  1920x1080  30   yes
  2  MVI_0022.mp4   2m 55s  1920x1080  30   yes
  3  MVI_0023.mp4   8m 02s  1920x1080  30   yes
  ...
```

### The questions

```
Project name [Full Day]: Priya & Rahul Marriage

What kind of film is this?
  1. engagement
  2. general
  3. marriage (default)
Choice [marriage]: marriage

Target length
-------------
  . you have 2h 14m of footage
How many minutes should the finished video be? [5]: 6
```

That last answer is the number everything else is measured against.

### Picking the clips

With **one long file** you give in and out points:

```
select [0 clips]: 4:20 4:38 #baraat "groom arriving"
  [ok] c001: full_day.mp4 00:04:20.000 -> 00:04:38.000 (18s)  #baraat
  [...........................] 18s of 6m 00s  (5%)
  . 5m 42s still to fill
```

With **a folder** you start the line with the file number:

```
select [1 clips]: 3 1:05 1:23 #varmala "garland"
select [2 clips]: 7
  [ok] c003: MVI_0027.mp4 00:00:00.000 -> 00:00:42.000 (42s)
```

A bare file number takes that whole file.

### Everything you can type

| Input | Meaning |
|---|---|
| `1:30 1:48` | that range out of the (single) source |
| `3 1:30 1:48` | that range out of file #3 |
| `3` | the whole of file #3 |
| `1:30 1:48 #haldi` | file it under the haldi segment |
| `1:30 1:48 "ring close-up"` | label it |
| `1:30 1:48 #haldi "ring close-up"` | both |
| `list` | the clips so far, with the progress bar |
| `files` | the source inventory again |
| `segments` | the segment names for this preset |
| `undo` | drop the last one |
| `drop c003` | drop one by id |
| `help` | the cheat sheet |
| `done` | finish and cut |
| `quit` | leave without cutting |

Timestamps: `90`, `1:30`, `00:01:30.5`, `1h2m3s`. `90:00` means ninety minutes.

### Segment names

Tagging with `#` is optional, but it is what makes step 2's `story` mode work,
and it files the clip into a readable folder. For `--preset marriage`:

```
mehndi  haldi  baraat  welcome  varmala  pheras  rituals
couple_portraits  family  vidaai  reception  dance  candid
```

Prefixes are enough: `#var` finds `varmala`.

### When you type `done`

```
Cutting 4 clip(s) with ffmpeg
-----------------------------
  [1/4] c001 -> 02_selected/baraat/c001_groom-arriving.mp4
  ...
========================================================
STEP 1 DONE
========================================================
  [ok] 24 clip(s) in projects/priya-rahul-marriage/02_selected
  [#########################...] 5m 31s of 6m 00s  (92%)
```

Everything is now in `project.json`. You can close the terminal safely.

> **Tip:** `--stream-copy` cuts without re-encoding and is several times
> faster, but it can only cut on keyframes, so your in-points may drift by a
> second or two. Fine for a rough pass, not for final work.

---

## Step 2 — arrange

```bash
python -m video_editor arrange priya-rahul-marriage
```

Pick a mode:

```
How should the clips be ordered?
  1. match
  2. story (default)
  3. emotion
  4. manual
```

**For a wedding film, use `story`.** It walks the segments in ceremony order and
frame-matches inside each one.

The report tells you how each cut looks:

```
  #  id    length  segment  emotion  cut into it    what it is
  1  c001  18s     baraat   -        -              groom arriving
  2  c005  12s     baraat   -        9/64 smooth    dhol players
  3  c009  22s     varmala  -        31/64 JUMP     garland
  . 23 cuts: 14 smooth, 3 visible jumps, average distance 18.2/64
```

`cut into it` is the Hamming distance between the previous clip's last frame
and this clip's first frame, out of 64 bits. Under 14 reads as smooth; over 26
is a visible jump. A few jumps are fine — they are often exactly what you want
between segments.

Not happy? Answer `n` and run it again with another mode. Nothing is written
until you say yes.

### Fixing one bad join by hand

```bash
python -m video_editor arrange priya-rahul-marriage --mode manual
```

```
order: c001 c005 c012 c009
  . appending 20 clip(s) you did not mention
```

### Choosing the opening shot

```bash
python -m video_editor arrange priya-rahul-marriage --mode match --first c014
```

---

## Step 3 — music

```bash
python -m video_editor music priya-rahul-marriage --song "D:/music/tum-hi-ho.mp3"
```

Leave `--song` off and it asks — you can drag the file onto the terminal.

```
Listening for the beat
----------------------
  [ok] 128.0 BPM  (beat every 0.469s, first beat at 0.212s, 512 beats, strong pulse)

Snap cuts to...
  1. beat
  2. half-bar
  3. bar (default)
  4. two-bar
```

| Choice | Cut lands every | Use it for |
|---|---|---|
| `beat` | 0.47s at 128 BPM | fast dance montage, sangeet |
| `half-bar` | 0.94s | general purpose |
| `bar` | 1.88s | most wedding films — lands on the "one" |
| `two-bar` | 3.75s | slow romantic holds, vidaai |

Then every clip is rounded to a whole number of those units:

```
  #  id    was   now   change  holds     starts at
  1  c001  18s   17s   -0.75s  36 beats  00:00:00.000
  2  c005  12s   13s   +0.88s  28 beats  00:00:16.875
  . runtime 5m 31s -> 5m 36s
  [ok] fits inside the song with 24s to spare
  . 24s under your 6m 00s target
```

A clip that needs to grow pulls extra frames from the original source when they
are there, so you do not lose anything you chose.

### Making it fit

```bash
python -m video_editor music priya-rahul-marriage --song song.mp3 --fit both
```

`--fit song` keeps it inside the song, `--fit target` inside your target
length, `--fit both` inside whichever is shorter. It shaves whole beats off the
longest clips first, so the rhythm survives.

### What it writes

`04_music/beat_sheet.csv`:

```
position,clip_id,starts_at,song_time,start_beat,beats_held,length,segment,label
1,c001,00:00:00.000,00:00:00.212,1,36,17.156,baraat,groom arriving
2,c005,00:00:17.156,00:00:17.368,37,28,13.125,baraat,dhol players
```

- `starts_at` — where the cut sits in the finished film
- `song_time` — the same moment inside the song file

They differ by the song's lead-in. The render step shifts the song by that
amount so beat one lands at 00:00:00 of the film — that is what puts the cuts
*on* the music rather than near it.

---

## Step 4 — emotions

```bash
python -m video_editor emotions priya-rahul-marriage
```

```
Reading 24 clip(s) with the heuristic backend
---------------------------------------------
  [1/24] c001 groom arriving
  .    fun  (fun 38%, happy 27%, calm 14%)
  [2/24] c005 dhol players
  [!]     happy  (close call: happy 24%, fun 23%, ritual 19%)
```

A `[!]` means the top two scores were close — the machine is guessing. It
offers a correction pass:

```
Correct any of these by hand? [y/N]: y
review: c005 fun
  [ok] c005 -> fun
review: done
```

Then it files everything:

```
05_emotion/
  happy/      05 clips  1m 12s
  emotional/  03 clips  48s
  romantic/   04 clips  1m 03s
  fun/        07 clips  1m 44s
  ritual/     03 clips  39s
  calm/       02 clips  18s
  index.csv
```

### A better backend

The default reads energy, not faces. For real expression reading:

```bash
pip install fer
python -m video_editor emotions priya-rahul-marriage --backend face --force
```

`fer` pulls in opencv and tensorflow, so it is a big install. It is also
noticeably slower — it samples six frames per clip and runs a model on each.

### Using the folders

The point of this step is that `05_emotion/emotional/` now holds every tearful
moment of the wedding in one place. Open it, watch it, and you have your
montage material without scrubbing anything.

---

## Step 5 — render

```bash
python -m video_editor render priya-rahul-marriage --audio mix
```

```
Render plan
-----------
  clips            24
  runtime          5m 36s
  size             1920x1080
  frame rate       30 fps
  audio            mix
  song             tum-hi-ho.mp3
  music starts at  0.212s (first beat)
  quality          crf 19, preset veryfast
  fades            1.5s in and out

Render 5m 36s now? [Y/n]:
```

| `--audio` | What you hear |
|---|---|
| `music` | the song only — clean montage |
| `mix` | the song over the original sound at 25% — vows, laughter, dhol underneath |
| `original` | no song at all |
| `silent` | no audio track |

Check the plan without encoding:

```bash
python -m video_editor render priya-rahul-marriage --dry-run
```

Smaller and faster:

```bash
python -m video_editor render priya-rahul-marriage --size 1280x720 --crf 23 --x264-preset ultrafast
```

Best quality, slow:

```bash
python -m video_editor render priya-rahul-marriage --crf 17 --x264-preset slow
```

Result:

```
========================================================
DONE - YOUR FILM IS READY
========================================================
  [ok] projects/priya-rahul-marriage/06_final/priya-rahul-marriage_final.mp4
  . 5m 36s, 1920x1080, 30 fps, 487.2 MB
  . you asked for 6m 00s and got 5m 36s (-24s)
```

---

## Keeping track

```bash
python -m video_editor status priya-rahul-marriage
```

```
  step      state
  --------  -----
  select    done
  arrange   done
  music     done
  emotions  done
  render    -
  . next:  python -m video_editor render "projects/priya-rahul-marriage"
```

```bash
python -m video_editor list
```

```
  folder                  preset    clips  runtime  steps  updated
  priya-rahul-marriage    marriage  24     5m 36s   4/5    2026-11-27T15:0
  anita-engagement        engagement 11    3m 00s   5/5    2026-11-20T11:2
```

---

## Changing your mind

Each step is re-runnable, and only overwrites its own folder.

| You want to | Do this |
|---|---|
| Add more clips | Run `select` again on a **new** project, or edit `project.json` by hand |
| Try a different order | `arrange --mode match` — nothing else is touched |
| Try a different song | `music --song other.mp3` — it re-snaps every clip |
| Re-score emotions | `emotions --force` |
| Re-render | `render` — it overwrites the final file |

`project.json` is plain, readable JSON. Editing it by hand is a supported way to
work: fix a label, nudge an in-point, change a segment, then re-run the step
that cares.

---

## Running it from a script

Every question can be answered with a flag, and the steps accept piped input:

```bash
printf '1:30 1:48 #haldi\n2:10 2:30 #varmala\ndone\n' \
  | python -m video_editor select footage.mp4 --name "Auto" --preset marriage --minutes 3
echo y | python -m video_editor arrange Auto --mode story
python -m video_editor music Auto --song song.mp3 --snap bar --fit both
python -m video_editor emotions Auto --no-review
echo y | python -m video_editor render Auto --audio mix
```

`tools/run_sample_pipeline.sh` is exactly this, against generated footage.
