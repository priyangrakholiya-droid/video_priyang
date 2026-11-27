"""STEP 1 - select: decide which stretches of footage the film is made of.

Nothing is cut here. A selection is a list of references - file, in-point,
out-point - written into the manifest and into 01_selection/selection.json.
That is why this step is instant even on hours of 4K, and why changing your
mind costs nothing.

Two ways to make the selection:

  auto    A detector scans the footage for shot changes and loud moments and
          proposes enough clips to fill your target length. You keep, drop or
          adjust what it found. This is the mode an agent uses, and the one to
          use on a long unedited recording.

  manual  You type in/out points, with a progress bar against your target.
          Use it when you know exactly which moments you want.
"""

from __future__ import annotations

from pathlib import Path

from video_editor import ui
from video_editor.detect import DetectError, Moment, propose
from video_editor.presets import Preset, PresetError
from video_editor.probe import MediaInfo, ProbeError, find_sources, probe
from video_editor.project import Clip, Project, slugify
from video_editor.timecode import (
    TimecodeError,
    format_duration,
    format_timecode,
    parse_minutes,
    parse_timecode,
)

MODES = ("auto", "manual")

HELP = """
Type one selection per line:

  <in> <out>                  take that range out of the source
  <file#> <in> <out>          when you gave a folder: which file to take from
  <file#>                     take a whole file as one clip
  <in> <out> #<segment>       file it under a segment, e.g. #varmala
  <in> <out> "ring close-up"  give it a label (quotes optional)

Timestamps accept 90, 1:30, 00:01:30.5 or 1h2m3s.

Commands:
  list      show the clips chosen so far
  files     show the source inventory again
  segments  show the segment names for this preset
  undo      drop the last selection
  drop <id> drop one selection by id
  help      show this text
  done      finish
  quit      leave without saving the selection
"""


# --------------------------------------------------------------------- reading
def read_sources(target: str, *, quiet: bool = False) -> list[MediaInfo]:
    """Probe one file or a whole folder."""
    sources = find_sources(target)
    infos: list[MediaInfo] = []
    if not quiet:
        ui.heading(f"Reading {len(sources)} file(s)")
    for i, source in enumerate(sources, 1):
        if not quiet:
            ui.progress(i, len(sources), source.name)
        try:
            infos.append(probe(source))
        except ProbeError as exc:
            ui.warn(f"skipping {source.name}: {exc}")
    if not infos:
        raise ProbeError("none of those files could be read as video")
    return infos


def show_inventory(infos: list[MediaInfo]) -> None:
    ui.heading("Source footage")
    ui.table(
        ["#", "file", "length", "size", "fps", "audio"],
        [
            [
                i,
                info.path.name,
                format_duration(info.duration),
                info.resolution,
                f"{info.fps:g}",
                "yes" if info.has_audio else "no",
            ]
            for i, info in enumerate(infos, 1)
        ],
    )
    total = sum(info.duration for info in infos)
    ui.note(f"{len(infos)} file(s), {format_duration(total)} of footage in total")


# --------------------------------------------------------------------- budget
def show_budget(project: Project) -> None:
    chosen = project.selected_duration
    target = project.target_duration
    if target <= 0:
        ui.note(f"total chosen: {format_duration(chosen)}")
        return
    pct = chosen / target * 100
    width = 28
    filled = min(width, int(round(width * min(pct, 100) / 100)))
    # ui.info, not print: in --json mode stdout must stay a single document.
    ui.info(
        f"  [{'#' * filled}{'.' * (width - filled)}] "
        f"{format_duration(chosen)} of {format_duration(target)}  ({pct:.0f}%)"
    )
    remaining = target - chosen
    if remaining > 1:
        ui.note(f"{format_duration(remaining)} still to fill")
    elif remaining < -1:
        ui.warn(f"over target by {format_duration(-remaining)}")
    else:
        ui.ok("right on target")


def show_selection(project: Project) -> None:
    clips = project.clips
    ui.heading(f"Selected ({len(clips)} clip(s))")
    ui.table(
        ["id", "source", "in", "out", "length", "segment", "from", "what it is"],
        [
            [
                c.id,
                c.source_name,
                format_timecode(c.source_in),
                format_timecode(c.source_out),
                format_duration(c.duration),
                c.segment or "-",
                c.origin,
                c.label or "-",
            ]
            for c in clips
        ],
    )
    show_budget(project)


# ----------------------------------------------------------------- auto mode
def moments_to_clips(project: Project, moments: list[Moment]) -> list[Clip]:
    clips: list[Clip] = []
    for moment in moments:
        clips.append(
            Clip(
                id=project.next_clip_id(clips),
                source=moment.source,
                source_name=moment.source_name,
                source_in=moment.start,
                source_out=moment.end,
                segment=moment.segment,
                score=moment.score,
                origin="auto",
                notes=moment.reason(),
            )
        )
    return clips


def run_auto(
    project: Project,
    infos: list[MediaInfo],
    preset: Preset,
    *,
    threshold: float | None,
    min_gap: float | None,
    quiet: bool = False,
) -> list[Clip]:
    """Let the detector propose the selection."""
    ui.heading("Scanning the footage for moments")
    ui.note(
        "looking for shot changes and loud moments - no footage is written, "
        "this only reads"
    )

    def progress(index: int, total: int, label: str) -> None:
        if not quiet:
            ui.progress(index, total, label)

    moments, tally = propose(
        [info.path for info in infos],
        target_duration=project.target_duration,
        preset=preset,
        threshold=threshold,
        min_gap=min_gap,
        on_progress=progress,
    )

    ui.heading("What the scan found")
    ui.table(
        ["file", "candidate moments"],
        [[name, count] for name, count in tally.items()],
    )
    clips = moments_to_clips(project, moments)
    project.clips = clips
    project.candidates = []
    ui.ok(f"proposed {len(clips)} clip(s)")
    ui.table(
        ["id", "source", "in", "length", "segment", "score", "why"],
        [
            [
                c.id,
                c.source_name,
                format_timecode(c.source_in),
                format_duration(c.duration),
                c.segment or "-",
                f"{c.score:.2f}",
                c.notes,
            ]
            for c in clips
        ],
    )
    show_budget(project)
    return clips


# --------------------------------------------------------------- manual mode
def parse_entry(
    raw: str,
    infos: list[MediaInfo],
    preset: Preset,
    single: bool,
) -> tuple[MediaInfo, float, float, str, str]:
    """Read one typed selection line."""
    text = raw.strip()
    segment = ""
    parts: list[str] = []
    for token in text.split():
        if token.startswith("#") and len(token) > 1:
            segment = preset.resolve_segment(token)
        else:
            parts.append(token)

    label = ""
    if '"' in text:
        chunks = text.split('"')
        if len(chunks) >= 3:
            label = chunks[1].strip()
            parts = [
                p for p in " ".join([chunks[0], chunks[2]]).split()
                if not p.startswith("#")
            ]

    if not parts:
        raise TimecodeError("nothing to read on that line")

    info = infos[0]
    if not single:
        if not parts[0].isdigit():
            raise TimecodeError("start the line with the file number (see 'files')")
        index = int(parts[0]) - 1
        if not 0 <= index < len(infos):
            raise TimecodeError(f"there is no file #{parts[0]}")
        info = infos[index]
        parts = parts[1:]
        if not parts:
            return info, 0.0, info.duration, segment, label

    if len(parts) < 2:
        raise TimecodeError("give both an in-point and an out-point")

    start = parse_timecode(parts[0])
    end = parse_timecode(parts[1])
    leftover = parts[2:]
    if leftover and not label:
        label = " ".join(leftover)

    if end <= start:
        raise TimecodeError(
            f"the out-point ({format_timecode(end)}) must come after the "
            f"in-point ({format_timecode(start)})"
        )
    if start >= info.duration:
        raise TimecodeError(
            f"{format_timecode(start)} is past the end of {info.path.name} "
            f"({format_duration(info.duration)} long)"
        )
    if end > info.duration:
        ui.warn(
            f"out-point trimmed to the end of {info.path.name} "
            f"({format_timecode(info.duration)})"
        )
        end = info.duration
    return info, start, end, segment, label


def run_manual(
    project: Project,
    infos: list[MediaInfo],
    preset: Preset,
    *,
    starting: list[Clip] | None = None,
) -> list[Clip] | None:
    """Type the selection. Returns None if the user quit."""
    single = len(infos) == 1
    ui.heading("Choose your clips")
    ui.info(HELP)
    if single:
        ui.note(
            f"source: {infos[0].path.name} "
            f"({format_duration(infos[0].duration)})"
        )
    ui.note("segments: " + ", ".join(preset.segment_ids))

    clips: list[Clip] = list(starting or [])
    while True:
        try:
            raw = ui.ask(f"select [{len(clips)} clips]")
        except ui.Abort:
            raw = "done"
        command = raw.strip().lower()

        if command in ("done", "d", ""):
            if not clips and not ui.confirm("Nothing chosen. Finish anyway?", False):
                continue
            return clips
        if command in ("quit", "q", "exit"):
            return None
        if command in ("help", "h", "?"):
            ui.info(HELP)
            continue
        if command in ("files", "f"):
            show_inventory(infos)
            continue
        if command in ("segments", "seg"):
            ui.note("segments: " + ", ".join(preset.segment_ids))
            continue
        if command in ("list", "l"):
            project.clips = clips
            show_selection(project)
            continue
        if command in ("undo", "u"):
            if clips:
                dropped = clips.pop()
                ui.note(f"dropped {dropped.id} ({format_duration(dropped.duration)})")
                project.clips = clips
                show_budget(project)
            else:
                ui.warn("nothing to undo")
            continue
        if command.startswith("drop "):
            wanted = raw.split(maxsplit=1)[1].strip()
            before = len(clips)
            clips = [c for c in clips if c.id != wanted]
            if len(clips) == before:
                ui.warn(f"no clip with id {wanted}")
            else:
                ui.note(f"dropped {wanted}")
                project.clips = clips
                show_budget(project)
            continue

        try:
            info, start, end, segment, label = parse_entry(raw, infos, preset, single)
        except (TimecodeError, PresetError, ValueError) as exc:
            ui.error(str(exc))
            continue

        clip = Clip(
            id=project.next_clip_id(clips),
            source=str(info.path.resolve()),
            source_name=info.path.name,
            source_in=start,
            source_out=end,
            segment=segment or preset.guess_segment(label or info.path.name),
            label=label,
            origin="manual",
        )
        clips.append(clip)
        project.clips = clips
        ui.ok(
            f"{clip.id}: {info.path.name} "
            f"{format_timecode(start)} -> {format_timecode(end)} "
            f"({format_duration(clip.duration)})"
            + (f"  #{clip.segment}" if clip.segment else "")
        )
        show_budget(project)


# ---------------------------------------------------------------- definition
def write_definition(project: Project, infos: list[MediaInfo]) -> Path:
    """01_selection/selection.json - the selection as a readable document."""
    payload = {
        "schema": 2,
        "project": project.name,
        "preset": project.preset_name,
        "target_duration": round(project.target_duration, 3),
        "selected_duration": round(project.selected_duration, 3),
        "sources": [
            {
                "path": str(info.path.resolve()),
                "name": info.path.name,
                "duration": round(info.duration, 3),
                "size": info.resolution,
                "fps": info.fps,
                "has_audio": info.has_audio,
            }
            for info in infos
        ],
        "clips": [
            {
                "id": c.id,
                "source": c.source,
                "source_in": round(c.source_in, 3),
                "source_out": round(c.source_out, 3),
                "duration": round(c.duration, 3),
                "segment": c.segment,
                "label": c.label,
                "origin": c.origin,
                "score": c.score,
                "notes": c.notes,
            }
            for c in project.clips
        ],
    }
    return project.write_definition("selection", "selection.json", payload)


# ---------------------------------------------------------------------- entry
def run(
    footage: str,
    *,
    projects_dir: Path,
    name: str | None = None,
    preset_name: str | None = None,
    minutes: float | None = None,
    mode: str | None = None,
    threshold: float | None = None,
    min_gap: float | None = None,
    presets_dir: str | None = None,
    quiet: bool = False,
) -> Project:
    """Run step 1 and return the project it created."""
    from video_editor.presets import load as load_preset, names as preset_names

    infos = read_sources(footage, quiet=quiet)
    if not quiet:
        show_inventory(infos)

    ui.banner("STEP 1 of 5 - SELECT", "Decide which moments the film is made of.")

    default_name = Path(footage).stem.replace("_", " ").title()
    project_name = name or ui.ask("Project name", default_name)
    chosen_preset_name = preset_name or ui.choose(
        "What kind of event is this?", preset_names(presets_dir), default="marriage"
    )
    preset = load_preset(chosen_preset_name, presets_dir)
    ui.note(f"preset: {preset.title} - {preset.description}")

    if minutes is None:
        ui.heading("Target length")
        ui.note(
            f"you have {format_duration(sum(i.duration for i in infos))} of footage"
        )
        target = ui.ask_until(
            "How many minutes should the finished video be?",
            parse_minutes,
            default=f"{preset.target_minutes:g}",
        )
    else:
        target = minutes * 60
    assert isinstance(target, float)

    root = projects_dir / slugify(project_name)
    project = Project.create(
        root,
        name=project_name,
        preset=preset,
        target_duration=target,
        sources=[i.path for i in infos],
        input_path=str(Path(footage).resolve()),
        presets_dir=presets_dir,
    )
    ui.ok(f"project ready: {root}")
    ui.note(f"target length: {format_duration(target)}")
    ui.note("no footage is copied - this project stores references only")

    chosen_mode = mode or (
        ui.choose(
            "How should the clips be chosen?",
            list(MODES),
            default="auto",
        )
        if ui.interactive()
        else "auto"
    )
    if chosen_mode not in MODES:
        raise ProbeError(f"unknown mode {chosen_mode!r}. Choose from: {', '.join(MODES)}")

    if chosen_mode == "auto":
        try:
            clips = run_auto(
                project, infos, preset,
                threshold=threshold, min_gap=min_gap, quiet=quiet,
            )
        except DetectError as exc:
            ui.error(str(exc))
            if not ui.interactive():
                raise
            ui.note("falling back to manual selection")
            clips = run_manual(project, infos, preset) or []
        else:
            if ui.interactive() and ui.confirm("Adjust this selection by hand?", False):
                adjusted = run_manual(project, infos, preset, starting=clips)
                if adjusted is not None:
                    clips = adjusted
    else:
        result = run_manual(project, infos, preset)
        if result is None:
            ui.warn("left without saving a selection. Run select again.")
            return project
        clips = result

    project.clips = clips
    if clips:
        project.mark_done("select")
    definition = write_definition(project, infos)
    project.save()

    ui.banner("STEP 1 DONE")
    ui.ok(f"{len(clips)} clip(s) selected, {format_duration(project.selected_duration)}")
    ui.note(f"written to {definition.relative_to(project.root)} (references, no video)")
    show_budget(project)
    ui.note(f'next:  python -m video_editor arrange "{project.root}"')
    return project
