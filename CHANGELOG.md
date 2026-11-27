# Changelog

All notable changes to this project. Dates are ISO. Versions follow
[semantic versioning](https://semver.org/).

---

## 0.2.0 — 2026-11-27

A restructure around one decision: **a clip is a reference, not a copy.** Plus
automatic moment finding, event presets as data, and a machine interface.

### Changed — the project is now definitions, not video

Schema 1 cut every selected clip out of the footage, re-encoded it into
`02_selected/`, then hard-linked it into `03_arranged/` and `05_emotion/`. A
wedding project was hundreds of megabytes of duplicated footage, and the final
render went through an intermediate encode.

Schema 2 stores a file path and an in/out point. **No footage is copied, cut or
duplicated. Only the finished film is written.**

| | schema 1 | schema 2 |
|---|---|---|
| Project size (24 clips) | 300–600 MB | ~700 KB (mostly the song) |
| Select step | re-encodes every clip | writes JSON |
| Encodes before the final film | 1 | 0 |
| Clip can be re-cut | re-run and re-encode | edit a number |

Old projects still open: `Project.load` migrates schema 1, dropping the
`file` field and keeping the in/out points it was cut from.

Folders renamed accordingly: `01_source`/`02_selected` → `01_selection`,
`03_arranged` → `02_arrangement`, `04_music` → `03_music`, `05_emotion` →
`04_emotion`, `06_final` → `05_output`.

### Added — automatic moment finding (`video_editor/detect.py`)

Point it at footage and it proposes the clips, instead of needing typed
timecodes. ffmpeg's `select` filter reports scene scores; the audio is reduced
to a coarse loudness curve; each shot boundary is scored on both, spread out
so the film does not take six clips from the same minute, and ranked until the
target length is filled. Every proposal records its reasoning
(`"scene 0.74, loudness 0.79 -> score 0.76"`).

`select --mode auto` is now the default. `--mode manual` keeps the old typed
in/out workflow. Tunable with `--threshold` and `--min-gap`.

### Added — event presets as data (`config/presets/*.json`)

Seven kinds of event ship: **marriage, engagement, party, baby_shower,
birthday, anniversary, general**. A preset sets the segments and their order,
the emotional arc, clip length limits, beat snapping, the audio mix and the
detector's sensitivity.

Adding an event type is now one JSON file and no code change. Segment
`keywords` let a file called `haldi_cam2.mp4` be filed under haldi
automatically.

### Added — a machine interface

- `--json` on every command: one document on stdout, warnings to stderr, and
  **no questions ever asked**, so a step cannot hang.
- `doctor` — checks ffmpeg, Python, presets and the optional face backend.
- `plan` — the film as a portable EDL; also written to `<project>/edit.json`.
- `presets` — lists the event types, `--verbose` shows their segments.
- Errors are JSON: `{"error": ..., "error_type": ...}`.
- Documented exit codes: 0 fine, 1 step failed, 2 bad input, 3 ffmpeg missing,
  130 cancelled.
- [CLAUDE.md](CLAUDE.md) — the agent brief.
- [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) — the JSON reference.
- [videoeditor.json](videoeditor.json) — machine-readable manifest of the
  pipeline, its settings and its limits.

### Changed — analysis reads footage in place

`emotion` and `arrange` used to analyse the extracted clip files. They now read
the original footage between the clip's in and out points (`-ss`/`-t`), which
is what makes the reference-only model possible. `beats.loudness_envelope` and
`emotion.visual_features` take `start`/`duration`, and the envelope's frame
size is configurable so a two-hour file can be scanned cheaply.

### Changed — preset-driven defaults

Beat snapping, audio mix, volumes, clip length limits and detector sensitivity
now come from the preset instead of being hardcoded. A party gets `music` audio
and `half-bar` snapping; an anniversary gets `two-bar`. Flags still win.

### Added — segment priors in the emotion step

A clip tagged `#vidaai` leans emotional and `#dance` leans fun, because the
preset says so — applied as a 15% nudge, not an override, so the picture and
sound still decide. `--no-prior` turns it off.

### Changed — repo layout

Moved to a `src/` layout (`src/video_editor/`), with `config/` for presets,
`scripts/` for the helper scripts (was `tools/`), `docs/`, and
`.github/workflows/ci.yml` running the tests on Linux and Windows against
Python 3.10 and 3.13.

### Fixed

- `parse_timecode("00:99:00")` was accepted because the hours field was zero.
  Minutes must now be under 60 in the `HH:MM:SS` form, while `90:00` still
  means ninety minutes in the `MM:SS` form.
- The selection progress bar used `print()` directly, which corrupted stdout
  under `--json`.
- `scripts/make_sample_footage.sh` built lavfi strings as `smptebars:size=…`
  instead of `smptebars=size=…`, and wrote absolute MSYS paths into the concat
  list, which ffmpeg cannot open on Windows. Both fixed; the list now uses
  relative names.

### Tests

109 tests, up from 54. New suites for presets (`test_presets.py`, including
loading a custom event type from a temp folder and rejecting malformed ones)
and the detector (`test_detect.py`, which builds footage with cuts at known
times and checks they are found). Still standard library only, still no media
checked in.

---

## 0.1.0 — 2026-11-27

First version. A five-step pipeline — select, arrange, music, emotions,
render — with:

- Interactive clip selection from one long file or a folder, with a progress
  bar against a target length in minutes.
- Clip ordering by 64-bit difference hashes of the edge frames, so cuts land
  on similar-looking frames.
- Beat detection with no audio libraries: ffmpeg reduces the song to a
  loudness envelope, Python does onset detection, autocorrelation for tempo
  and a comb filter for phase. Verified against generated click tracks
  (120 BPM read as 120.9, 100 as 99.7).
- Mood scoring from brightness, saturation, hue, motion and audio dynamics,
  with an optional real facial-expression backend behind `pip install fer`.
- Rendering from the original sources with the song laid under, started on its
  first beat.
- Marriage, engagement and general segment presets, hardcoded.
- 54 tests, standard library only.
