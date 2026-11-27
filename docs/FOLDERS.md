# The folder layout

Every project is one folder, and every step of the pipeline owns one numbered
sub-folder inside it. Nothing is hidden: at any point you can open these
folders in Explorer or Finder and see exactly what the tool has decided.

```
projects/
  priya-rahul-marriage/
    project.json
    01_source/
    02_selected/
    03_arranged/
    04_music/
    05_emotion/
    06_final/
```

Projects live in `./projects` by default. Move that with `--projects-dir`:

```bash
python -m video_editor --projects-dir "D:/edits" select "D:/wedding/full_day.mp4"
```

---

## `project.json` — the single source of truth

Plain, readable JSON. Every other folder can be rebuilt from it.

```json
{
  "schema": 1,
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
      "file": "02_selected/baraat/c001_groom-arriving.mp4",
      "label": "groom arriving",
      "order": 1,
      "segment": "baraat",
      "emotion": "fun",
      "emotion_scores": { "fun": 0.38, "happy": 0.27, "...": 0.0 },
      "beat_duration": 17.156,
      "head_hash": 1284908234,
      "tail_hash": 9823749823,
      "notes": ""
    }
  ],
  "music": { "bpm": 128.0, "period": 0.469, "offset": 0.212, "...": 0 },
  "steps_done": ["select", "arrange", "music", "emotions"]
}
```

### The fields worth knowing

| Field | Meaning |
|---|---|
| `target_duration` | your answer to "how many minutes?", in seconds |
| `source_in` / `source_out` | the in/out points **in the original footage** |
| `file` | the extracted clip, relative to the project folder |
| `order` | the running order from step 2 (1-based; `null` = not arranged) |
| `segment` | which part of the wedding, e.g. `varmala` |
| `emotion` | which folder it was filed under in step 4 |
| `beat_duration` | the beat-snapped length from step 3 — **this is what gets rendered** |
| `head_hash` / `tail_hash` | the edge-frame fingerprints step 2 matches on |
| `steps_done` | drives `status` and the "next:" hints |

**Editing it by hand is supported.** Fix a label, nudge an in-point by a few
frames, move a clip to another segment — then re-run the step that cares. It is
written atomically (to a temp file, then moved), so a crash cannot leave you
with a half-written manifest.

---

## `01_source/` — originals

Empty by default. The tool never copies your footage here; it reads from
wherever you pointed it and stores absolute paths. The folder exists for when
you want the project to be self-contained — drop copies of the originals in and
nothing outside the project folder is needed any more.

> Note: step 5 renders from the paths in `sources`, so if you move or rename
> your footage after step 1, the render will fail with
> `original source is gone`. Put copies here and fix the paths in
> `project.json` if that happens.

---

## `02_selected/` — step 1's output

The clips you kept, in segment folders:

```
02_selected/
  mehndi/
  haldi/        c002_haldi-hands.mp4
  baraat/       c001_groom-arriving.mp4  c005_dhol-players.mp4
  varmala/      c009_garland.mp4
  pheras/       c015_pheras-wide.mp4
  vidaai/       c019_mother.mp4
  reception/
  dance/        c011_dance-floor.mp4
  candid/
  unsorted/     c022_clip.mp4
```

Every segment folder for your preset is created up front, even the ones you do
not use, so you can see at a glance what you have not shot yet. Clips you did
not tag with `#` land in `unsorted/`.

File names are `<clip id>_<label>.mp4`. The clip id is what you refer to in
every later step.

These are **re-encoded** cuts (H.264, CRF 20) unless you passed
`--stream-copy`. They are preview-quality working files — the final render goes
back to the originals.

---

## `03_arranged/` — step 2's output

The same clips, numbered in running order:

```
03_arranged/
  001_c001_groom-arriving.mp4
  002_c005_dhol-players.mp4
  003_c009_garland.mp4
  concat.txt
  edl.csv
```

These are **hard links**, not copies — on one filesystem they cost no extra
disk space. Across drives the tool falls back to copying.

### `concat.txt`

ffmpeg's concat format. You can render the cut yourself with no further help:

```bash
ffmpeg -f concat -safe 0 -i 03_arranged/concat.txt -c copy rough_cut.mp4
```

### `edl.csv`

```csv
position,clip_id,file,source,source_in,source_out,duration,segment,emotion
1,c001,001_c001_groom-arriving.mp4,full_day.mp4,260.000,278.000,17.156,baraat,fun
```

Opens in Excel, and gives you the real source timecodes if you want to rebuild
the edit in Premiere, Resolve or Final Cut instead.

---

## `04_music/` — step 3's output

```
04_music/
  tum-hi-ho.mp3      your song, copied in
  beats.txt          every beat time in the song, one per line
  beat_sheet.csv     which beat each clip starts on
```

The song is copied so the project folder is self-contained — you can archive it
or move it to another machine and still render.

### `beats.txt`

```
0.2120
0.6810
1.1500
```

Seconds from the start of the song file. 512 lines for a four minute track at
128 BPM.

### `beat_sheet.csv`

```csv
position,clip_id,starts_at,song_time,start_beat,beats_held,length,segment,label
1,c001,00:00:00.000,00:00:00.212,1,36,17.156,baraat,groom arriving
```

- `starts_at` — where the cut sits in the **finished film**
- `song_time` — the same moment inside the **song file**

They differ by the song's lead-in (its first beat is not at 0.000). Step 5
starts the song at that offset, so beat one lands at 00:00:00 of the film.

---

## `05_emotion/` — step 4's output

```
05_emotion/
  happy/      c004_cake.mp4  c011_dance-floor.mp4
  emotional/  c019_mother.mp4
  romantic/   c007_couple-walk.mp4
  fun/        c001_groom-arriving.mp4  c005_dhol-players.mp4
  ritual/     c015_pheras-wide.mp4
  calm/       c002_decor.mp4
  index.csv
```

Hard links again, so a clip appearing in `02_selected`, `03_arranged` and
`05_emotion` still occupies the disk space of one file.

This folder is rebuilt from scratch every time step 4 runs, so correcting an
emotion and re-running moves the file.

### `index.csv`

Every clip with all six scores, so you can sort by any of them yourself:

```csv
clip_id,emotion,file,length,segment,label,happy,emotional,romantic,fun,ritual,calm
c001,fun,c001_groom-arriving.mp4,17.156,baraat,groom arriving,0.2700,0.0900,0.1100,0.3800,0.0900,0.0600
```

---

## `06_final/` — step 5's output

```
06_final/
  priya-rahul-marriage_final.mp4
  render_plan.csv
```

`render_plan.csv` records exactly what went into the film and in what order,
with the original source timecodes — your paper trail if a client asks for a
change six months later.

Temporary per-clip encodes are written to a `ve_render_*` folder inside
`06_final/` and deleted when the render finishes. `--keep-temp` keeps them.

---

## Disk space

For a 6 minute film cut from 2 hours of 1080p footage, expect roughly:

| Folder | Size |
|---|---|
| `02_selected/` | 300–600 MB (re-encoded working clips) |
| `03_arranged/` | 0 (hard links) |
| `04_music/` | the size of your song |
| `05_emotion/` | 0 (hard links) |
| `06_final/` | 400–700 MB at CRF 19 |

Add a few GB of headroom for the temporary render files.
