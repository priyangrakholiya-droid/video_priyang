# Contributing

Pull requests welcome. The project has two rules that shape everything else:

1. **No pip dependencies in the core pipeline.** Standard library plus ffmpeg.
   Anything heavier goes behind an optional backend, the way the `face` emotion
   backend does, and the tool must still work without it.
2. **Be honest in the output.** If a measurement is a guess, say so. The
   `close call` flag on emotion scores and the `weak pulse` warning on beat
   detection are the pattern to follow — never present a shaky number as a
   confident one.

## Getting set up

```bash
git clone https://github.com/<you>/video_editor.git
cd video_editor
python -m unittest discover -s tests -t . -v
```

There is nothing to install. If `ffmpeg` is missing, the audio tests skip
themselves and the rest still run.

## Trying a change end to end

```bash
bash tools/run_sample_pipeline.sh
```

That builds synthetic footage and a click track with ffmpeg, runs all five
steps unattended, and fails loudly if no film comes out. Run it before opening
a PR — it catches the integration mistakes that unit tests miss.

## Tests

- `unittest`, not pytest, so there is nothing to install.
- **No media in the repo.** Tests that need audio or video build it with
  ffmpeg into a temp folder and clean up after themselves.
- Tests that need ffmpeg are wrapped in
  `@unittest.skipUnless(HAS_FFMPEG, ...)`.
- A new algorithm needs a test with a *known answer* — the beat tests generate
  a click track at an exact BPM and assert the detector finds it. That is the
  bar.

## Layout

```
video_editor/
  cli.py          argparse, error handling, exit codes
  project.py      the project folder and project.json
  probe.py        ffmpeg/ffprobe wrappers, cutting, frame hashing
  beats.py        tempo and beat-grid detection
  emotion.py      mood scoring, both backends
  timecode.py     parsing and formatting timestamps
  ui.py           prompts, tables, progress
  steps/
    select.py     step 1
    arrange.py    step 2
    music.py      step 3
    emotions.py   step 4
    render.py     step 5
tests/
tools/
docs/
```

A step module owns one folder in the project and one entry in `steps_done`. It
reads `project.json`, does its work, writes `project.json` back. Keep that
shape: it is what lets a user stop after any step and come back tomorrow.

## Style

- Type hints on anything public.
- Docstrings that say *why*, not *what the code plainly says*.
- Error messages that name the fix, not just the problem. `"-5 is not a
  timestamp. Use 90, 1:30, 00:01:30.5 or 1h2m3s."` rather than
  `"invalid input"`.
- Never crash on a user typo. Re-ask the question.

## Things worth doing

- Crossfades and transitions between clips in the render step.
- Tempo-drift tracking for live recordings, instead of one rigid grid.
- Reading faces without a 500 MB install — a small ONNX expression model.
- A `--proxy` mode: cut at 480p for speed, re-render the final at full size.
- Speech detection, so cuts avoid landing mid-sentence.
