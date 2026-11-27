# How it works

The four parts of this tool that are not just file shuffling: moment finding,
beat detection, frame matching, and mood scoring. None of them needs a
third-party library, and all four are small enough to read in an afternoon.

---

## 1. Moment finding

`video_editor/detect.py`

The goal: given hours of unedited footage, propose the stretches worth keeping,
so nobody has to type timecodes.

The assumption is the same one highlight detectors use on game streams: **the
interesting moments are where the picture changes and where the sound peaks.**
Neither signal is "interest" — they are proxies, and the limits section below
is honest about that — but together they find shot boundaries and energy, which
is most of what an event film is cut from.

### Shot boundaries

ffmpeg's `select` filter computes a scene score for every frame: roughly, how
different this frame is from the one before it. Frames above a threshold are
printed with their timestamp.

```
scale=320:-2,select='gt(scene,0.3)',metadata=print:file=-
```

Scaling to 320 pixels wide first is what makes this usable on long footage. The
scene score barely changes between 320 and 1920 pixels; the decode cost changes
enormously.

### Energy

The audio goes through the same reduction the beat detector uses, but with much
coarser frames — 4096 samples, about 190 ms — because finding a cheer does not
need 23 ms resolution. Cheering, music, a dhol, laughter and speech all read as
loudness. Each dB value is mapped onto 0–1 across a −55 to −12 dB window.

### Scoring and spreading

Every shot boundary becomes a candidate clip, running until the next boundary,
clamped to the preset's `min_clip_seconds` and `max_clip_seconds`. Each is
scored:

```python
score = 0.6 * energy + 0.4 * scene_score      # prefer_loud (default)
score = 0.35 * energy + 0.65 * scene_score    # prefer_loud: false
```

A baby shower sets `prefer_loud: false`, because the quiet moments matter; a
party leaves it on.

Then candidates are thinned, best first, vetoing anything within
`min_gap_seconds` of something already kept:

```python
for moment in sorted(moments, key=lambda m: -m.score):
    if not any(abs(other.start - moment.start) < min_gap for other in kept):
        kept.append(moment)
```

That is what stops a film taking six clips from the same thirty seconds just
because the dance floor was loud. Finally the best are taken until the target
length is filled, and handed back in footage order.

### Where it struggles

- **One long static shot** — a tripod on the mandap for an hour — produces no
  scene changes at all, and the tool says so rather than inventing moments.
  `--threshold 0.1` helps; otherwise it needs manual selection.
- **It does not know what is in the frame.** A loud shot of the catering van
  scores as well as a loud shot of the vows.
- **A constantly moving camera** reads as constant change, so the thresholds
  need raising.

Every proposal carries its reasoning into `01_selection/selection.json`, so you
can see why a clip was chosen before deciding the tool was wrong.

---

## 2. Beat detection

`video_editor/beats.py`

The goal: given an mp3, produce a list of times in seconds where the beats are,
so clip lengths can be rounded to whole beats.

The whole thing rests on one idea: **a beat is a moment when the music gets
suddenly louder.** Find the sudden-louder moments, work out how regularly they
repeat, and you have the tempo.

### Stage 1 — a loudness envelope, computed by ffmpeg

Pulling millions of raw audio samples into Python would be slow, so ffmpeg is
asked to do the reduction:

```
aresample=22050,
aformat=channel_layouts=mono,
asetnsamples=n=512:p=0,
astats=metadata=1:reset=1,
ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-
```

Read that as: resample to 22050 Hz, flatten to mono, chop into 512-sample
frames (23.2 ms each), measure the RMS level of every frame, print it.

A four minute song becomes about 10,000 numbers in dB. That is the *envelope*.

### Stage 2 — onset strength

A beat is a *rise* in loudness, not loudness itself. So we difference the
envelope and keep only the rises:

```python
raw[i] = max(levels[i] - levels[i - 1], 0.0)
```

Then a 3-frame moving average removes single-frame jitter, and the mean is
subtracted so a quiet passage does not drag the next stage around:

```python
onsets[i] = max(smooth[i] - mean, 0.0)
```

Now we have a signal that spikes on every drum hit and chord change.

### Stage 3 — tempo, by autocorrelation

If the music has a beat every 0.47 seconds, then the onset signal looks like
itself when shifted by 0.47 seconds. So: correlate the signal with a shifted
copy of itself, at every shift from 60 BPM to 190 BPM, and see which shift
scores highest.

```python
def _autocorrelate(signal, lag):
    n = len(signal) - lag
    return sum(signal[i] * signal[i + lag] for i in range(n)) / n
```

The winning `lag` times 23.2 ms is the beat period.

Two refinements matter:

**Parabolic interpolation.** The true period rarely lands exactly on a frame
boundary. Fitting a parabola through the winning score and its two neighbours
and taking the vertex recovers sub-frame precision:

```python
shift = 0.5 * (left - right) / (left - 2 * best + right)
```

**Octave folding.** Autocorrelation is just as happy locking onto half or
double the real tempo — a 128 BPM track correlates beautifully at 64 BPM. So
anything outside 70–180 BPM is doubled or halved until it lands inside:

```python
while 60.0 / period < 70.0:  period /= 2.0
while 60.0 / period > 180.0: period *= 2.0
```

### Stage 4 — phase, by comb filter

Knowing beats are 0.47 s apart does not say *where* they are. So we slide a
comb — a set of spikes 0.47 s apart — across one period's worth of offsets, and
keep the offset where the comb collects the most onset energy.

```python
for s in range(steps):
    offset = s * lag / steps
    score = sum(onsets[round(offset + k * lag)] for k in ...)
```

The winner is the time of beat one. Beats are then simply
`offset, offset + period, offset + 2*period, ...`.

### Confidence

The strongest autocorrelation score is compared against the mean of all scores.
A sharp, isolated peak means a strongly periodic song; a flat landscape means
there is no real pulse and the tool says `weak pulse` rather than pretending.

### Accuracy

Measured against ffmpeg-generated click tracks (`tests/test_beats.py`):

| True tempo | Detected |
|---|---|
| 100 BPM | 99.7 |
| 120 BPM | 120.9 |
| 140 BPM | ~140 |

Within about 1%, which is well inside what the ear notices over a 6 minute
film. Phase lands within a quarter of a beat of the real clicks.

### Where it struggles

- Free-tempo music, solo instruments, speech — no periodic onsets to find.
- Live recordings that drift in tempo: the grid is rigid, so cuts late in the
  film drift off the beat. Use `--snap beat` so each cut has less distance to
  drift over.
- Half-time and double-time feels (a lot of Bollywood) can read an octave off.
  `--snap half-bar` or `--snap two-bar` compensates without re-detecting.

---

## 3. Frame matching

`video_editor/probe.py` (the hashing), `video_editor/steps/arrange.py` (the chaining)

The goal: order clips so each cut lands between frames that look alike, because
that is what makes an edit feel continuous rather than jumpy.

### The difference hash

For each clip we extract two frames — just inside the start, and just inside
the end (the very first and last frames are often mid-fade):

```
ffmpeg -ss <t> -i clip.mp4 -frames:v 1 -vf scale=9:8,format=gray -c:v pgm -
```

That is a 9×8 greyscale image, 72 pixels, which Python reads straight off the
pipe with a 30-line binary PGM parser. Then, for each of the 8 rows, compare
each pixel with the one to its right:

```python
bits = (bits << 1) | (1 if left > right else 0)
```

8 rows × 8 comparisons = **64 bits**. This is a *difference hash* (dHash). What
it captures is the layout of light and dark in the frame — the shape of the
composition. What it ignores is overall brightness, small shifts, compression
noise and resolution, because only the *relative* brightness of neighbouring
regions matters.

### The cost of a cut

```python
def join_cost(a, b):
    return bin(a.tail_hash ^ b.head_hash).count("1")
```

The Hamming distance: how many of the 64 bits differ. Empirically:

| Distance | Means |
|---|---|
| 0–14 | the frames look alike — a smooth join |
| 15–26 | a normal cut |
| 27+ | a visible jump |

### Ordering

With a cost for every possible pair, ordering clips is the travelling-salesman
problem. The tool uses the obvious greedy approximation: start somewhere, then
repeatedly take whichever unused clip opens most like the frame we are leaving.

```python
while remaining:
    nxt = min(remaining, key=lambda c: join_cost(chain[-1], c))
```

Greedy is not optimal, but it is `O(n²)`, runs instantly on a few hundred
clips, and — crucially — it is *explainable*: the report prints every join cost
so you can see which cut it got wrong and fix that one by hand.

The opening clip, if you do not name one with `--first`, is the clip that
nothing else matches *into* — it is the worst follower, so it earns the front.

### story mode

Pure matching will happily put the vidaai before the baraat, because it only
knows about pixels. So `story` mode buckets the clips by their `#segment` tag,
walks the buckets in the preset's ceremony order, and only matches *within* a
bucket. You get chronological sense and smooth joins.

---

## 4. Mood scoring

`video_editor/emotion.py`

The goal: file each clip under one of six feelings — happy, emotional,
romantic, fun, ritual, calm.

### What is actually measured

ffmpeg's `signalstats` filter, sampled at 4 fps on a 160-pixel-wide copy of
the clip's stretch of the original file (`-ss` and `-t` locate it):

| Signal | What it is |
|---|---|
| `YAVG` | average luma — brightness |
| `SATAVG` | average saturation — how colourful |
| `HUEAVG` | average hue in degrees — which way the colour leans |
| `YDIF` | frame-to-frame luma difference — **motion** |

Plus, from the same loudness envelope the beat detector uses:

| Signal | What it is |
|---|---|
| mean dB | how loud the clip is |
| dB standard deviation | how much the loudness swings |

Warmth is the distance around the colour wheel from 20° (candle and skin
tones), so firelight and sunset score high, blue shade scores low.

### The mapping

Six weighted sums, normalised to add up to 1:

```python
"fun":       0.55 * motion    + 0.30 * audio_energy + 0.15 * saturation
"happy":     0.35 * brightness+ 0.30 * saturation   + 0.20 * audio_energy + 0.15 * motion
"emotional": 0.40 * stillness + 0.30 * audio_swing  + 0.30 * darkness
"romantic":  0.40 * warmth    + 0.35 * stillness    + 0.25 * quiet
"ritual":    0.40 * stillness + 0.30 * warmth       + 0.30 * steady_audio
"calm":      0.45 * stillness + 0.35 * quiet        + 0.20 * steady_audio
```

The reasoning behind each: a dance floor moves and is loud (`fun`). A vidaai is
still, dim, and the audio swells and breaks (`emotional`). A couple's portrait
is warm, slow and soft (`romantic`). Pheras are static with firelight and even
sound (`ritual`).

### Why this is weaker than the rest of the tool

**It does not look at faces.** It cannot. Brightness, motion and loudness are
proxies for mood, and proxies fail: a tearful goodbye shot in bright midday sun
scores `happy`, and a static shot of empty chairs scores `ritual`.

What it *is* good at is sorting by **energy** — separating the dance floor from
the ceremony from the b-roll — and that is genuinely most of the sorting work.

The tool is honest about this in two ways. It prints the top three scores for
every clip, and when the top two are within 15% of each other it marks the clip
`close call` and offers a correction pass.

### The real backend

`--backend face` runs an actual facial-expression model (`fer`, or `deepface`
if that is what you have installed): six frames per clip, faces detected,
expression probabilities averaged, then mapped onto the six folders.

```
happy    -> happy          sad      -> emotional
surprise -> fun            fear     -> emotional
neutral  -> calm           angry    -> emotional
                           disgust  -> emotional
```

`romantic` has no facial equivalent, so it keeps the visual warmth-and-stillness
cue. If no faces are found in a clip at all, the backend falls back to the
heuristic rather than returning nothing.

This is much better at what the step claims to do. It costs a large pip install
(opencv + tensorflow) and is several seconds per clip, which is why it is not
the default.

---

## Why no numpy, scipy, librosa or OpenCV?

`librosa` would do the beat detection in one line and do it better. The reasons
not to:

1. **Installing it is the hard part.** `pip install librosa` pulls in numba,
   llvmlite and scipy. On Windows, for someone who just wants to cut their
   wedding video, that is where the project ends.
2. **ffmpeg is already required**, and ffmpeg's filters are written in C by
   people who do this for a living. Pushing the per-sample work into ffmpeg and
   keeping only the 10,000-value envelope in Python gets most of the
   performance for none of the dependency cost.
3. **It stays readable.** Every algorithm here is 30 lines of plain Python you
   can step through, which matters more for a tool you will want to tweak than
   peak accuracy does.

The trade is real, though: `librosa` handles tempo drift, octave ambiguity and
onset detection better than this does. If you already have a scientific Python
stack installed, swapping `beats.estimate_period` for a librosa call is a
twenty-line change.
