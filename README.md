# video_editor

A five-step video editor for **engagement and marriage films**, driven from the
command line. You hand it raw footage; it walks you through choosing clips,
ordering them, cutting them to the beat of a song, sorting them by emotion, and
rendering the finished film.

Every step writes into its own numbered folder, so you can stop after any step,
inspect the files yourself, and pick up later.

```
raw footage  ->  1 SELECT  ->  2 ARRANGE  ->  3 MUSIC  ->  4 EMOTIONS  ->  5 RENDER  ->  final film
                 what to      what order     cut to the    sort by         merge
                 keep                        beat          feeling
```

- **No Python packages to install.** Standard library only.
- **One external tool:** ffmpeg (which ships ffprobe).
- Beat detection, frame matching and mood analysis are all implemented here.

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [The five steps](#the-five-steps)
- [The folders it makes](#the-folders-it-makes)
- [Every command](#every-command)
- [How the clever bits work](#how-the-clever-bits-work)
- [Honest limits](#honest-limits)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)

---

## Install

**1. Python 3.10 or newer**

```bash
python --version
```

**2. ffmpeg** — the only dependency.

| System | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` (or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)) |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |

Check it:

```bash
ffmpeg -version
ffprobe -version
```

**3. This repo**

```bash
git clone https://github.com/<your-username>/video_editor.git
cd video_editor
python -m video_editor --help
```

Nothing to `pip install`. If you would rather install it as a command:

```bash
pip install -e .
video-editor --help        # same thing as python -m video_editor
```

---

## Quick start

One long recording, a five minute film, cut to a song:

```bash
python -m video_editor run "D:/wedding/full_day.mp4" --minutes 5 --song "D:/music/song.mp3"
```

Or step by step, which is what you normally want:

```bash
python -m video_editor select  "D:/wedding/clips"      # step 1
python -m video_editor arrange my-wedding              # step 2
python -m video_editor music   my-wedding --song "song.mp3"
python -m video_editor emotions my-wedding             # step 4
python -m video_editor render  my-wedding              # step 5
```

At any point:

```bash
python -m video_editor status my-wedding    # where am I?
python -m video_editor list                 # all my projects
```

### No footage to try it on?

Build some synthetic footage and a 120 BPM click track, then run the whole
pipeline on it:

```bash
bash tools/make_sample_footage.sh
```

---

## The five steps

### Step 1 — `select`: choose what to keep

Point it at **either one long recording or a folder of clips** — it works out
which you gave it.

```bash
python -m video_editor select "D:/wedding/full_day.mp4"
python -m video_editor select "D:/wedding/clips/"
```

It reads every file, prints an inventory, then asks the question the whole edit
hangs on:

```
How many minutes should the finished video be? [5]:
```

Then you type in/out points, and after each one it shows how much of your
target you have filled:

```
select [2 clips]: 12:40 12:58 #varmala "garland moment"
  [ok] c003: full_day.mp4 00:12:40.000 -> 00:12:58.000 (18s)  #varmala
  [##########..................] 1m 51s of 5m 00s  (37%)
  . 3m 09s still to fill
```

**What you can type:**

| Input | Meaning |
|---|---|
| `1:30 1:48` | take that range out of the source |
| `3 1:30 1:48` | from file #3 (when you gave a folder) |
| `3` | take the whole of file #3 |
| `1:30 1:48 #haldi` | file it under the haldi segment |
| `1:30 1:48 "ring close-up"` | give it a label |
| `list` `files` `segments` `undo` `drop c003` `help` `done` `quit` | commands |

Timestamps accept `90`, `1:30`, `00:01:30.5` or `1h2m3s`.

When you type `done`, ffmpeg cuts the real clips into
`02_selected/<segment>/` and every in/out point is saved to `project.json`.

**Options:** `--name`, `--preset {engagement,marriage,general}`, `--minutes N`,
`--stream-copy` (much faster, but cuts snap to keyframes and can drift a second
or two).

---

### Step 2 — `arrange`: which clip comes after which

```bash
python -m video_editor arrange my-wedding --mode story
```

Four ways to answer "what goes next?":

| Mode | What it does |
|---|---|
| **`story`** | Preset segment order (mehndi → haldi → baraat → varmala → pheras → vidaai → reception), then frame-matched inside each segment. **Use this for a wedding.** |
| **`match`** | Pure frame matching: compares the **last frame of every clip** against the **first frame of every other clip** and chains them so each cut lands on the most similar-looking frame. This is what stops an edit feeling jumpy. |
| **`emotion`** | Builds an arc: calm → happy → fun → romantic → ritual → emotional. Run step 4 first. |
| **`manual`** | You type the order: `c003 c001 c004`. |

It then shows you how good each cut is, measured in bits of difference out of 64:

```
  #  id    length  segment  emotion  cut into it   what it is
  1  c001  6s      haldi    happy    -             haldi.mp4
  2  c004  8s      pheras   ritual   11/64 smooth  full_day.mp4
  3  c003  6s      vidaai   emotional 16/64 ok     vidaai.mp4
  4  c002  6s      dance    fun      54/64 JUMP    dance.mp4
  . 3 cuts: 1 smooth, 1 visible jumps, average distance 27.0/64
```

Output goes to `03_arranged/` as numbered files, plus `concat.txt` (feeds
ffmpeg directly) and `edl.csv` (opens in Excel or any editor).

---

### Step 3 — `music`: find the beat, cut to it

```bash
python -m video_editor music my-wedding --song "D:/music/song.mp3" --snap bar
```

It asks for the song if you do not pass one, copies it into `04_music/` so the
project travels on its own, detects the tempo, and rounds **every clip's length
to a whole number of beats** so cut 1 ends exactly as a beat lands and cut 2
starts there.

```
  [ok] 128.0 BPM  (beat every 0.469s, first beat at 0.212s, 512 beats, strong pulse)
  . one bar = 4 beat(s) = 1.875s at 128.0 BPM

  #  id    was   now   change  holds     starts at
  1  c001  6s    5s    -0.63s  12 beats  00:00:00.000
  2  c004  8s    7s    -0.50s  16 beats  00:00:05.625
```

**`--snap` choices:**

| Value | Cut lands every | Good for |
|---|---|---|
| `beat` | 1 beat | fast dance montages |
| `half-bar` | 2 beats | general |
| `bar` | 4 beats (the "one") | calm, most wedding films — **default** |
| `two-bar` | 8 beats | slow romantic holds |

Lengthening a clip pulls extra frames from the original source when they exist,
so snapping does not cost you footage you chose.

**`--fit song|target|both`** trims whole beats off the longest clips until the
film fits inside the song, or your target length, or both.

Writes `04_music/beat_sheet.csv` (which beat each clip starts on) and
`04_music/beats.txt` (the whole grid).

---

### Step 4 — `emotions`: sort clips by feeling

```bash
python -m video_editor emotions my-wedding
```

Scores each clip and hard-links it into the folder it belongs to:

```
05_emotion/
  happy/      c004_cake.mp4  c011_dance-floor.mp4
  emotional/  c019_vidaai.mp4
  romantic/   c007_couple-walk.mp4
  fun/        c012_baraat.mp4
  ritual/     c015_pheras.mp4
  calm/       c002_decor.mp4
  index.csv   every clip, every score
```

So when you want "all the emotional moments", you open one folder instead of
scrubbing the whole wedding again.

It flags close calls and offers to let you correct them by hand:

```
review: c007 romantic
  [ok] c007 -> romantic
```

**Two backends:**

| Backend | How | Quality |
|---|---|---|
| `heuristic` (default) | brightness, colour warmth, motion, audio loudness and dynamics | good at sorting **energy**, poor at reading **faces** |
| `face` | a real facial-expression model | much better — needs `pip install fer` |

```bash
pip install fer                                      # optional
python -m video_editor emotions my-wedding --backend face
```

---

### Step 5 — `render`: merge the film

```bash
python -m video_editor render my-wedding --audio mix
```

Cuts every clip **from the original source** (not from the already-encoded
clip), so the film is encoded once and loses nothing. Normalises everything to
one size and frame rate, joins it, lays the song underneath, fades in and out.

```
06_final/
  my-wedding_final.mp4
  render_plan.csv
```

By default the song is started on its **first beat**, which is what makes the
cuts land on the music rather than near it.

**Options:** `--audio {music,mix,original,silent}`, `--size 1920x1080`,
`--fps 30`, `--crf 19` (18 best … 28 small), `--x264-preset veryslow`,
`--music-volume 0.9`, `--original-volume 0.25`, `--fade 1.5`,
`--no-align-music`, `--dry-run`.

---

## The folders it makes

```
projects/priya-rahul-marriage/
  project.json          every decision you have made, the single source of truth
  01_source/            room for copies of originals (optional)
  02_selected/          STEP 1: the clips you kept, in segment folders
    mehndi/  haldi/  baraat/  varmala/  pheras/  vidaai/  reception/ ...
  03_arranged/          STEP 2: the same clips, numbered in running order
    001_c001_haldi.mp4  002_c004_pheras.mp4 ...
    concat.txt          ready for ffmpeg
    edl.csv             opens in Excel or any NLE
  04_music/             STEP 3
    song.mp3            your song, copied in
    beats.txt           every beat time in the song
    beat_sheet.csv      which beat each clip starts on
  05_emotion/           STEP 4
    happy/ emotional/ romantic/ fun/ ritual/ calm/
    index.csv           every clip with all six scores
  06_final/             STEP 5
    priya-rahul-marriage_final.mp4
    render_plan.csv
```

Clips are **hard-linked** between folders where the filesystem allows it, so
appearing in three folders costs the disk space of one file.

### Segment presets

| `--preset marriage` | `--preset engagement` | `--preset general` |
|---|---|---|
| mehndi, haldi, baraat, welcome, varmala, pheras, rituals, couple_portraits, family, vidaai, reception, dance, candid | arrival, ring_exchange, couple_portraits, family, speeches, cake_and_toast, dance, candid | opening, main, people, detail, closing |

---

## Every command

```
python -m video_editor select   <footage>   [--name N] [--preset P] [--minutes M] [--stream-copy]
python -m video_editor arrange  [project]   [--mode story|match|emotion|manual] [--first ID] [--rehash]
python -m video_editor music    [project]   [--song S] [--snap beat|half-bar|bar|two-bar]
                                            [--fit song|target|both] [--beats-per-bar 4]
python -m video_editor emotions [project]   [--backend heuristic|face] [--force] [--no-review]
python -m video_editor render   [project]   [--audio music|mix|original|silent] [--size WxH]
                                            [--fps N] [--crf N] [--fade S] [--dry-run] ...
python -m video_editor run      <footage>   all five steps back to back
python -m video_editor status   [project]
python -m video_editor list
```

`[project]` accepts a folder path **or** just the project's name. Leave it out
entirely and it uses the only project you have, or asks which one.

`--projects-dir` moves where projects live (default `./projects`).

---

## How the clever bits work

### Beat detection (`video_editor/beats.py`)

1. ffmpeg resamples the song to mono 22050 Hz, chops it into 512-sample frames
   (~23 ms) and prints each frame's RMS level — a loudness envelope.
2. Differencing that envelope and keeping the rises gives **onset strength**:
   loudness climbing fast means something was struck.
3. **Autocorrelating** the onset signal finds the lag at which the music repeats
   — the beat period. Parabolic interpolation around the peak gets sub-frame
   precision, and octave errors are folded back into 70–180 BPM.
4. A **comb filter** slid across one period finds the phase — where beat one is.

Verified against generated click tracks: 120 BPM reads as 120.9, 100 as 99.7.

### Frame matching (`video_editor/probe.py`, `steps/arrange.py`)

Each clip's first and last frame are scaled to 9×8 greyscale and turned into a
64-bit **difference hash** (each bit: is this pixel brighter than the one to its
right?). The cost of cutting from clip A to clip B is the Hamming distance
between A's tail hash and B's head hash. Arranging is then a greedy
nearest-neighbour walk over those costs.

### Mood scoring (`video_editor/emotion.py`)

ffmpeg's `signalstats` gives average brightness, saturation, hue and
frame-to-frame difference; the audio envelope gives loudness and how much it
swings. Those six numbers are weighted into the six emotion buckets — a loud,
fast, saturated clip scores `fun`; a still, dim, dynamic-audio clip scores
`emotional`.

---

## Honest limits

- **The heuristic emotion backend does not read faces.** It reads energy,
  light and sound. It will put a sad moment shot in bright sunshine in the
  wrong folder sometimes. Use `--backend face` with `pip install fer` for real
  expression reading, and use the review pass either way.
- **Beat detection needs a beat.** A free-tempo song, a solo instrument or a
  speech will produce a weak pulse; the tool says so (`weak pulse`) instead of
  pretending.
- **`--stream-copy` drifts.** Stream copying can only cut on keyframes, so
  in-points can move by a second or two. It is off by default for that reason.
- **Rendering re-encodes.** Expect roughly real-time encoding on a normal
  laptop at the default `veryfast` preset.
- **Hard links need one filesystem.** Across drives it silently falls back to
  copying, which uses more disk.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found on PATH` | Install ffmpeg, then open a **new** terminal |
| `no video files in <folder>` | Check the extension is one of mp4, mov, mkv, avi, m4v, webm, mpg, wmv, flv, mts, m2ts, 3gp, ts |
| `could not read the duration` | The file is damaged or not really video. Try `ffprobe <file>` |
| Cuts feel slightly off the beat | The song's tempo drifts (live recording). Try `--snap beat` |
| `weak pulse` warning | Free-tempo song. Check `beat_sheet.csv` before trusting the cuts |
| Emotions all land in one folder | Normal for footage shot in one room at one brightness. Use `--backend face`, or correct them in the review pass |
| Render is slow | `--x264-preset ultrafast --crf 23`, or render a `--dry-run` first |
| `this step needs an open input` | You are piping from a script. Pass the values as options instead |

---

## Tests

54 tests, standard library only, no network, no checked-in media (the audio
tests build their own click tracks with ffmpeg and skip if it is missing):

```bash
python -m unittest discover -s tests -t . -v
```

---

## Licence

MIT — see [LICENSE](LICENSE).
