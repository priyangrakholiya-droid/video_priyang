# The project folder

A project is a folder of **definitions**, not a folder of video. That is the
central design decision, so it is worth being explicit about what it buys you:

| Because a clip is a reference… | you get |
|---|---|
| nothing is copied | a 24-clip wedding project is ~700 KB, nearly all of it the song |
| nothing is encoded until the end | every step finishes in seconds |
| the plan is just data | you can read it, diff it, edit it, mail it, or hand it to an agent |
| the render reads the originals | the film is encoded exactly once, losing nothing |
| your footage is only ever read | the tool cannot damage your source material |

```
projects/priya-rahul-marriage/
  project.json          every decision — the single source of truth
  edit.json             the portable edit plan
  01_selection/         selection.json
  02_arrangement/       order.json, cuts.csv
  03_music/             song.mp3, beats.txt, beat_sheet.csv
  04_emotion/           scores.json, groups.json, emotions.csv
  05_output/            the finished film, render_plan.csv
```

Projects live in `./projects` by default:

```bash
python -m video_editor --projects-dir "D:/edits" list
```

---

## `project.json` — the single source of truth

Everything else in the folder can be rebuilt from this file. It is schema 2,
plain JSON, and **meant to be edited by hand**.

```json
{
  "schema": 2,
  "name": "Priya & Rahul Marriage",
  "slug": "priya-rahul-marriage",
  "preset": "marriage",
  "segments": ["mehndi", "haldi", "baraat", "..."],
  "created": "2026-11-27T14:30:00",
  "updated": "2026-11-27T15:04:11",
  "input_path": "D:/wedding/full_day.mp4",
  "target_duration": 360.0,
  "sources": ["D:/wedding/full_day.mp4"],
  "clips": [
    {
      "id": "c001",
      "source": "D:/wedding/full_day.mp4",
      "source_name": "full_day.mp4",
      "source_in": 260.0,
      "source_out": 278.0,
      "label": "groom arriving",
      "order": 1,
      "segment": "baraat",
      "emotion": "fun",
      "emotion_scores": {"fun": 0.38, "happy": 0.27, "calm": 0.14},
      "beat_duration": 17.156,
      "head_hash": 1284908234,
      "tail_hash": 9823749823,
      "score": 0.76,
      "origin": "auto",
      "notes": "scene 0.74, loudness 0.79 -> score 0.76"
    }
  ],
  "candidates": [],
  "music": {"bpm": 128.0, "period": 0.469, "offset": 0.212, "...": 0},
  "output": {},
  "steps_done": ["select", "arrange", "music", "emotions"],
  "settings": {
    "pacing": {"min_clip_seconds": 2.0, "max_clip_seconds": 14.0, "snap": "bar"},
    "audio": {"mode": "mix", "music_volume": 0.9, "original_volume": 0.25},
    "autodetect": {"scene_threshold": 0.32, "min_gap_seconds": 5.0, "prefer_loud": true}
  }
}
```

### Clip fields

| Field | Meaning | Written by |
|---|---|---|
| `id` | `c001`, `c002`… how you refer to the clip everywhere | step 1 |
| `source` | absolute path of the **original** footage | step 1 |
| `source_in` / `source_out` | the in/out points inside that file, in seconds | step 1 |
| `label` | your description, used in reports | step 1 |
| `segment` | which part of the event, e.g. `varmala` | step 1 |
| `origin` | `auto` (a detector proposed it) or `manual` (you typed it) | step 1 |
| `score` | the detector's confidence, 0–1; 0 when you chose it yourself | step 1 |
| `notes` | why it was proposed, or `set by hand` | steps 1, 4 |
| `order` | position in the running order, 1-based; `null` = not arranged | step 2 |
| `head_hash` / `tail_hash` | 64-bit fingerprints of the edge frames | step 2 |
| `beat_duration` | the beat-snapped length — **this is what gets rendered** | step 3 |
| `emotion` | the winning bucket | step 4 |
| `emotion_scores` | all six scores, so you can see how close it was | step 4 |

There is deliberately **no field pointing at a piece of extracted video**. A
schema 1 project had one (`file`); opening such a project here upgrades it and
drops that field, keeping the in/out points, which are what mattered.

### Editing it by hand

| You want to | Edit | Then re-run |
|---|---|---|
| Nudge an in-point | `source_in` | `music` (to re-snap), then `render` |
| Fix a label | `label` | nothing — reports pick it up |
| Move a clip to another segment | `segment` | `arrange` |
| Correct a mood | `emotion` | `arrange --mode emotion`, if you use that mode |
| Force re-fingerprinting | delete `head_hash`/`tail_hash` | `arrange` (or pass `--rehash`) |
| Re-snap to the beat | delete `beat_duration` | `music` |
| Drop a clip | remove the object | `arrange`, then `render` |
| Point at moved footage | `source` and `sources` | `render` |

Rules: keep `source_out` above `source_in`; `segment` must be one of the
preset's (see `video_editor presets --verbose`); `emotion` must be one of
happy, emotional, romantic, fun, ritual, calm.

The file is written atomically — to a temp file, then moved — so an interrupted
save cannot leave you with half a manifest.

---

## `edit.json` — the portable plan

Rewritten every time the project is saved. It holds everything needed to
rebuild the film and nothing machine-specific — no fingerprints, no detector
scores — so it reads and diffs cleanly.

```json
{
  "schema": 2,
  "name": "Priya & Rahul Marriage",
  "preset": "marriage",
  "target_duration": 360.0,
  "runtime": 336.4,
  "music": {"file": "03_music/song.mp3", "bpm": 128.0, "period": 0.469,
            "offset": 0.212, "snap": "bar"},
  "audio": {"mode": "mix", "music_volume": 0.9, "original_volume": 0.25},
  "clips": [
    {"position": 1, "id": "c001", "source": "D:/wedding/full_day.mp4",
     "source_in": 260.0, "source_out": 277.156, "duration": 17.156,
     "starts_at": 0.0, "segment": "baraat", "emotion": "fun",
     "label": "groom arriving"}
  ]
}
```

`starts_at` is the position in the finished film; `source_in`/`source_out` are
where to find those frames in the original. That is a complete EDL: any editor
or script can rebuild this film from it.

```bash
python -m video_editor plan my-wedding --json      # the same thing on stdout
```

---

## `01_selection/selection.json`

What step 1 decided, and what it was looking at.

```json
{
  "schema": 2,
  "target_duration": 360.0,
  "selected_duration": 331.0,
  "sources": [
    {"path": "D:/wedding/full_day.mp4", "name": "full_day.mp4",
     "duration": 8040.3, "size": "1920x1080", "fps": 30.0, "has_audio": true}
  ],
  "clips": [
    {"id": "c001", "source": "D:/wedding/full_day.mp4",
     "source_in": 260.0, "source_out": 278.0, "duration": 18.0,
     "segment": "baraat", "label": "", "origin": "auto", "score": 0.76,
     "notes": "scene 0.74, loudness 0.79 -> score 0.76"}
  ]
}
```

The `notes` on an auto-selected clip is the detector showing its working: the
scene-change strength and the loudness that made it pick that moment.

---

## `02_arrangement/`

### `order.json`

```json
{
  "schema": 2,
  "mode": "story",
  "statistics": {"cuts": 23, "smooth": 14, "jumps": 3,
                 "average": 18.2, "runtime": 336.4},
  "thresholds": {"smooth_below": 14, "jump_above": 26},
  "order": [
    {"position": 1, "id": "c001", "at": 0.0, "duration": 17.156,
     "source": "D:/wedding/full_day.mp4", "source_in": 260.0,
     "source_out": 277.156, "segment": "baraat", "emotion": "fun",
     "join_cost": ""}
  ]
}
```

`join_cost` is how many of the 64 fingerprint bits differ between the previous
clip's last frame and this clip's first frame. Under 14 reads as a smooth join,
over 26 as a visible jump. `statistics.jumps` is the number worth looking at —
if it is high, try `--mode match`.

### `cuts.csv`

The same thing for a spreadsheet, with real source timecodes, so you can
rebuild the edit in Premiere, Resolve or Final Cut if you would rather.

---

## `03_music/`

```
03_music/
  song.mp3          your song, copied in so the project travels on its own
  beats.txt         every beat time in the song, one per line
  beat_sheet.csv    which beat each clip starts on
```

The song is the one thing the tool does copy — it is small, and it makes the
project self-contained and archivable.

### `beat_sheet.csv`

```csv
# beat grid: 128.00 BPM, period 0.46875s, first beat at 0.2120s in song.mp3
# the render step shifts the song by that offset so beat 1 = 00:00:00
position,clip_id,starts_at,song_time,start_beat,beats_held,length,segment,label
1,c001,00:00:00.000,00:00:00.212,1,36,17.156,baraat,groom arriving
```

Two time columns, because they are not the same thing:

- `starts_at` — where the cut sits in the **finished film**
- `song_time` — the same moment inside the **song file**

They differ by the song's lead-in. Step 5 starts the song at that offset, which
puts beat one at 00:00:00 of the film. That is what makes cuts land *on* the
music rather than near it.

---

## `04_emotion/`

No folders of duplicated video — the groups are a document.

### `scores.json`

Every clip with all six scores and the reason:

```json
{
  "backend": "heuristic",
  "segment_prior": 0.15,
  "clips": [
    {"id": "c001", "emotion": "fun",
     "scores": {"fun": 0.38, "happy": 0.27, "emotional": 0.09,
                "romantic": 0.11, "ritual": 0.09, "calm": 0.06},
     "segment": "baraat", "source": "D:/wedding/full_day.mp4",
     "source_in": 260.0, "duration": 17.156, "notes": ""}
  ]
}
```

`segment_prior` records how much the clip's segment was allowed to nudge the
score — a `#vidaai` clip leans emotional, a `#dance` clip leans fun, but the
picture and sound still decide. `--no-prior` turns it off.

### `groups.json`

The answer to "show me all the emotional moments":

```json
{
  "arc": ["calm", "happy", "fun", "romantic", "ritual", "emotional"],
  "groups": {
    "fun":       {"clips": ["c001", "c005", "c011"], "count": 3, "runtime": 44.2},
    "emotional": {"clips": ["c019", "c021"],         "count": 2, "runtime": 28.0}
  }
}
```

Those are clip ids, and every id is resolvable to a file and a timecode through
`project.json`. Nothing was copied to produce this.

### `emotions.csv`

Every clip, every score, for a spreadsheet — sort by `emotional` descending and
you have your montage order.

---

## `05_output/`

```
05_output/
  priya-rahul-marriage_final.mp4      the only video in the whole project
  render_plan.csv                     what went in, in order
```

`render_plan.csv` records every clip with its original source timecode — the
paper trail when a client asks for a change six months later.

While rendering, per-clip encodes go into a temporary `ve_render_*` folder in
here and are deleted when it finishes. `--keep-temp` keeps them.

---

## Disk space

For a 6 minute film cut from 2 hours of 1080p footage:

| Folder | Size |
|---|---|
| `project.json` + `edit.json` | ~50 KB |
| `01_selection/` … `04_emotion/` | ~30 KB of JSON and CSV |
| `03_music/` | the size of your song (~5 MB) |
| `05_output/` | 400–700 MB at CRF 19 |

So: the film, the song, and a rounding error. Add a few GB of headroom while
the render is running.

Compare with the old schema 1 behaviour, which also wrote 300–600 MB of
re-encoded working clips into `02_selected/` and then hard-linked them into two
more folders. Those files are gone, and the final render is better for it —
it no longer goes through an intermediate encode.
