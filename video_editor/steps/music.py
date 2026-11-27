"""STEP 3 - music: ask for the song, find its beats, cut to them.

Why this step exists
--------------------
A wedding film lives or dies on whether the cuts land with the music. Do it by
hand and you are nudging clip edges around for hours. This step does it in one
pass:

  1. It asks you for the song and copies it into 04_music/ so the project is
     self-contained.
  2. It detects the tempo and the beat grid (see video_editor/beats.py).
  3. It rounds every clip's length to a whole number of beats - or bars, if you
     want the cuts to land on the "one" - so clip 1 ends exactly as a beat
     lands, clip 2 starts there, and so on down the timeline.
  4. It writes a beat sheet: for every clip, which beat it starts on and how
     many beats it holds.

Lengthening a clip pulls extra frames from the original source when they are
there, so snapping does not cost you footage you had chosen.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from video_editor import beats as beat_tools
from video_editor import ui
from video_editor.beats import BeatError, BeatMap
from video_editor.probe import ProbeError, probe
from video_editor.project import Clip, Project
from video_editor.timecode import format_duration, format_timecode

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

GROUPS = {
    "beat": 1,      # a cut can land on any beat - busiest, best for dance
    "half-bar": 2,  # every two beats
    "bar": 4,       # every four beats - calm, lands on the "one"
    "two-bar": 8,   # long holds, good for slow romantic montages
}


def _find_song(given: str | None) -> Path:
    """Resolve the song the user wants: a file, or a folder to pick from."""
    if given:
        path = Path(given).expanduser()
        if path.is_file():
            return path
        if path.is_dir():
            found = sorted(
                p for p in path.iterdir()
                if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
            )
            if not found:
                raise BeatError(f"no audio files in {path}")
            if len(found) == 1:
                return found[0]
            ui.heading("Songs in that folder")
            names = [p.name for p in found]
            picked = ui.choose("Which song?", names)
            return found[names.index(picked)]
        raise BeatError(f"no such file: {path}")

    ui.heading("The song")
    ui.note("drag the song onto the terminal, or paste its full path")
    while True:
        raw = ui.ask("Song file (mp3, wav, m4a...)")
        candidate = Path(raw.strip().strip('"').strip("'")).expanduser()
        if candidate.is_file():
            return candidate
        ui.error(f"not a file: {candidate}")


def _store_song(project: Project, song: Path) -> Path:
    """Copy the song into the project so the folder travels on its own."""
    destination = project.dir("music") / song.name
    if destination.resolve() != song.resolve():
        shutil.copy2(song, destination)
    return destination


def _source_duration(cache: dict[str, float], path: str) -> float:
    if path not in cache:
        try:
            cache[path] = probe(path).duration
        except ProbeError:
            cache[path] = 0.0
    return cache[path]


def snap_clips(
    project: Project,
    beatmap: BeatMap,
    *,
    group: int,
) -> list[Clip]:
    """Round every clip to a whole number of beats (or bars)."""
    unit = beatmap.period * group
    cache: dict[str, float] = {}
    clips = project.ordered_clips()

    for clip in clips:
        wanted = beatmap.snap_duration(clip.duration, group=group)
        source_total = _source_duration(cache, clip.source)
        headroom = max(source_total - clip.source_in, 0.0)
        if source_total <= 0:
            # Could not read the source: never ask for more than we already cut.
            wanted = min(wanted, clip.duration)
        elif wanted > headroom:
            # Shed whole units until the clip fits what the source still holds.
            while wanted > headroom and wanted > unit:
                wanted -= unit
            wanted = min(wanted, headroom)
        clip.beat_duration = round(max(wanted, 0.04), 4)
    project.clips = clips
    return clips


def fit_to(project: Project, beatmap: BeatMap, *, group: int, limit: float) -> list[Clip]:
    """Trim whole beats off the longest clips until the cut fits `limit`."""
    unit = beatmap.period * group
    clips = project.ordered_clips()
    guard = 0
    while sum(c.render_duration for c in clips) > limit and guard < 10_000:
        guard += 1
        # Longest first, but never below one unit.
        candidates = [c for c in clips if c.render_duration > unit * 1.5]
        if not candidates:
            break
        victim = max(candidates, key=lambda c: c.render_duration)
        victim.beat_duration = round(victim.render_duration - unit, 4)
    project.clips = clips
    return clips


def _beat_sheet(project: Project, beatmap: BeatMap, group: int) -> Path:
    """Write which beat each clip starts on.

    Two time columns, because they are not the same thing:
      starts_at  - where the cut sits in the finished film, measured from 0
      song_time  - the same moment inside the original song file

    They differ by the song's own lead-in (its first beat is at
    offset={offset:.3f}s). The render step starts the song at that offset, which
    puts beat one at 00:00:00 of the film - that is what makes the cuts land.
    """
    lines = [
        f"# beat grid: {beatmap.bpm:.2f} BPM, period {beatmap.period:.5f}s, "
        f"first beat at {beatmap.offset:.4f}s in {Path(beatmap.path).name}",
        "# the render step shifts the song by that offset so beat 1 = 00:00:00",
        "position,clip_id,starts_at,song_time,start_beat,beats_held,length,segment,label",
    ]
    timeline = 0.0
    for position, clip in enumerate(project.ordered_clips(), 1):
        beats_held = beatmap.beats_in(clip.render_duration, group=group) * group
        start_beat = int(round(timeline / beatmap.period)) + 1 if beatmap.period else 0
        lines.append(
            ",".join([
                str(position),
                clip.id,
                format_timecode(timeline),
                format_timecode(timeline + beatmap.offset),
                str(start_beat),
                str(beats_held),
                f"{clip.render_duration:.3f}",
                clip.segment or "",
                (clip.label or "").replace(",", " "),
            ])
        )
        timeline += clip.render_duration
    destination = project.dir("music") / "beat_sheet.csv"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _report(project: Project, beatmap: BeatMap, group: int, before: float) -> None:
    after = project.render_duration
    ui.heading("Cuts snapped to the beat")
    rows = []
    timeline = 0.0
    for position, clip in enumerate(project.ordered_clips(), 1):
        held = beatmap.beats_in(clip.render_duration, group=group) * group
        shift = clip.render_duration - clip.duration
        rows.append([
            position,
            clip.id,
            format_duration(clip.duration),
            format_duration(clip.render_duration),
            f"{shift:+.2f}s",
            f"{held} beat" + ("s" if held != 1 else ""),
            format_timecode(timeline),
        ])
        timeline += clip.render_duration
    ui.table(
        ["#", "id", "was", "now", "change", "holds", "starts at"],
        rows,
    )
    ui.note(f"runtime {format_duration(before)} -> {format_duration(after)}")
    if beatmap.duration:
        if after > beatmap.duration + 0.5:
            ui.warn(
                f"the cut runs {format_duration(after - beatmap.duration)} longer "
                f"than the song ({format_duration(beatmap.duration)}). "
                "The render step will loop or fade the music - or re-run with --fit song."
            )
        else:
            ui.ok(
                f"fits inside the song with "
                f"{format_duration(beatmap.duration - after)} to spare"
            )
    target = project.target_duration
    if target:
        delta = after - target
        word = "over" if delta > 0 else "under"
        if abs(delta) > 2:
            ui.note(f"{format_duration(abs(delta))} {word} your {format_duration(target)} target")
        else:
            ui.ok(f"on target ({format_duration(target)})")


def run(
    project_path: str | Path,
    *,
    song: str | None = None,
    group: str | None = None,
    fit: str | None = None,
    beats_per_bar: int = 4,
) -> Project:
    """Run step 3 and return the project."""
    project = Project.load(project_path)
    if not project.clips:
        raise RuntimeError("no clips in this project. Run the select step first.")

    ui.banner(
        "STEP 3 of 5 - MUSIC",
        "Find the beat of the song and put every cut on it.",
    )
    ui.note(f"project: {project.name}")
    if not project.is_done("arrange"):
        ui.warn(
            "the clips are not arranged yet. Beat snapping works anyway, but "
            "run the arrange step first so the beat sheet matches the real order."
        )

    source_song = _find_song(song)
    stored = _store_song(project, source_song)
    ui.ok(f"song copied to {stored.relative_to(project.root)}")

    ui.heading("Listening for the beat")
    ui.note("this reads the whole song once; a few seconds for a normal track")
    beatmap = beat_tools.analyse(stored, beats_per_bar=beats_per_bar)
    ui.ok(beat_tools.describe(beatmap))
    if beatmap.confidence < 0.35:
        ui.warn(
            "the pulse is weak - a soft or free-tempo song. Check the beat "
            "sheet before you trust the cuts."
        )

    group_name = group or (
        ui.choose(
            "Snap cuts to...",
            list(GROUPS),
            default="bar",
        )
        if ui.interactive()
        else "bar"
    )
    if group_name not in GROUPS:
        raise RuntimeError(
            f"unknown group {group_name!r}. Choose from: {', '.join(GROUPS)}"
        )
    unit = GROUPS[group_name]
    ui.note(
        f"one {group_name} = {unit} beat(s) = "
        f"{beatmap.period * unit:.3f}s at {beatmap.bpm:.1f} BPM"
    )

    before = project.render_duration or project.selected_duration
    snap_clips(project, beatmap, group=unit)

    if fit in ("song", "target", "both"):
        limits = []
        if fit in ("song", "both") and beatmap.duration:
            limits.append(beatmap.duration)
        if fit in ("target", "both") and project.target_duration:
            limits.append(project.target_duration)
        if limits:
            fit_to(project, beatmap, group=unit, limit=min(limits))

    project.data["music"] = {
        **beatmap.to_dict(),
        "file": str(stored.relative_to(project.root)).replace("\\", "/"),
        "original_path": str(source_song.resolve()),
        "snap_group": group_name,
        "snap_beats": unit,
    }
    _report(project, beatmap, unit, before)

    sheet = _beat_sheet(project, beatmap, unit)
    grid = project.dir("music") / "beats.txt"
    grid.write_text(
        "\n".join(f"{t:.4f}" for t in beatmap.beats) + "\n", encoding="utf-8"
    )
    ui.ok(f"beat sheet: {sheet.relative_to(project.root)}")
    ui.ok(f"beat grid:  {grid.relative_to(project.root)} ({len(beatmap.beats)} beats)")

    project.mark_done("music")
    project.save()

    ui.banner("STEP 3 DONE")
    ui.note(f"next:  python -m video_editor emotions \"{project.root}\"")
    return project
