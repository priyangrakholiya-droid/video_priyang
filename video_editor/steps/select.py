"""STEP 1 - select: turn raw footage into a folder of chosen clips.

What happens
------------
You point the tool at either one long recording or a folder full of clips.
It reads every file, prints an inventory, then asks the one question that
drives everything else:

    How many minutes should the finished video be?

From there you type in/out points. After every entry it tells you how much of
your target you have filled, so you stop guessing. When you are done it cuts
the real clips with ffmpeg into:

    <project>/02_selected/<segment>/<id>_<label>.mp4

and records every in/out point in project.json, so nothing is lost if you
close the terminal.
"""

from __future__ import annotations

from pathlib import Path

from video_editor import ui
from video_editor.probe import MediaInfo, ProbeError, cut, find_sources, probe
from video_editor.project import PRESETS, Clip, Project, slugify
from video_editor.timecode import (
    TimecodeError,
    format_duration,
    format_timecode,
    parse_minutes,
    parse_timecode,
)

HELP = """
Type one selection per line:

  <in> <out>                  take that range out of the source
  <file#> <in> <out>          when you gave a folder: which file to cut from
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
  done      finish and cut the clips
  quit      leave without cutting anything
"""


def _inventory(sources: list[Path]) -> list[MediaInfo]:
    infos: list[MediaInfo] = []
    ui.heading("Reading the footage")
    for i, source in enumerate(sources, 1):
        ui.progress(i, len(sources), source.name)
        try:
            infos.append(probe(source))
        except ProbeError as exc:
            ui.warn(f"skipping {source.name}: {exc}")
    if not infos:
        raise ProbeError("none of those files could be read as video")
    return infos


def _show_inventory(infos: list[MediaInfo]) -> None:
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


def _show_selection(project: Project, infos: list[MediaInfo]) -> None:
    clips = project.clips
    ui.heading(f"Chosen so far ({len(clips)} clip(s))")
    ui.table(
        ["id", "source", "in", "out", "length", "segment", "label"],
        [
            [
                c.id,
                c.source_name,
                format_timecode(c.source_in),
                format_timecode(c.source_out),
                format_duration(c.duration),
                c.segment or "-",
                c.label or "-",
            ]
            for c in clips
        ],
    )
    _show_budget(project)


def _show_budget(project: Project) -> None:
    chosen = project.selected_duration
    target = project.target_duration
    if target <= 0:
        ui.note(f"total chosen: {format_duration(chosen)}")
        return
    pct = chosen / target * 100
    bar_width = 28
    filled = min(bar_width, int(round(bar_width * min(pct, 100) / 100)))
    bar = "#" * filled + "." * (bar_width - filled)
    line = (
        f"  [{bar}] {format_duration(chosen)} of {format_duration(target)}"
        f"  ({pct:.0f}%)"
    )
    print(line)
    remaining = target - chosen
    if remaining > 1:
        ui.note(f"{format_duration(remaining)} still to fill")
    elif remaining < -1:
        ui.warn(f"over target by {format_duration(-remaining)}")
    else:
        ui.ok("right on target")


def _parse_entry(
    raw: str,
    infos: list[MediaInfo],
    segments: list[str],
    single: bool,
) -> tuple[MediaInfo, float, float, str, str]:
    """Read one selection line. Returns (source, in, out, segment, label)."""
    text = raw.strip()
    segment = ""
    # Pull out #segment anywhere in the line.
    parts: list[str] = []
    for token in text.split():
        if token.startswith("#") and len(token) > 1:
            name = token[1:].lower()
            matches = [s for s in segments if s.startswith(name)]
            if not matches:
                raise TimecodeError(
                    f"unknown segment {name!r}. Known: {', '.join(segments)}"
                )
            segment = matches[0]
        else:
            parts.append(token)

    # A quoted label, or trailing words that are not timestamps, become a label.
    label = ""
    if '"' in text:
        chunks = text.split('"')
        if len(chunks) >= 3:
            label = chunks[1].strip()
            parts = [p for p in " ".join([chunks[0], chunks[2]]).split()
                     if not p.startswith("#")]

    if not parts:
        raise TimecodeError("nothing to read on that line")

    index = 0
    info = infos[0]
    if not single:
        if not parts[0].isdigit():
            raise TimecodeError(
                "start the line with the file number (see 'files')"
            )
        index = int(parts[0]) - 1
        if not 0 <= index < len(infos):
            raise TimecodeError(f"there is no file #{parts[0]}")
        info = infos[index]
        parts = parts[1:]
        if not parts:  # whole file
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


def run(
    input_path: str,
    *,
    projects_dir: Path,
    name: str | None = None,
    preset: str | None = None,
    minutes: float | None = None,
    reencode: bool = True,
) -> Project:
    """Run step 1 end to end and return the project it created."""
    sources = find_sources(input_path)
    single = len(sources) == 1
    infos = _inventory(sources)
    _show_inventory(infos)

    ui.banner(
        "STEP 1 of 5 - SELECT",
        "Pick the moments worth keeping.",
    )

    # --- the project itself -------------------------------------------------
    default_name = Path(input_path).stem.replace("_", " ").title()
    project_name = name or ui.ask("Project name", default_name)
    chosen_preset = preset or ui.choose(
        "What kind of film is this?", list(PRESETS), default="marriage"
    )

    # --- the question that drives the edit ----------------------------------
    if minutes is None:
        ui.heading("Target length")
        total_available = sum(i.duration for i in infos)
        ui.note(f"you have {format_duration(total_available)} of footage")
        target = ui.ask_until(
            "How many minutes should the finished video be?",
            parse_minutes,
            default="5",
        )
    else:
        target = minutes * 60
    assert isinstance(target, float)

    root = projects_dir / slugify(project_name)
    project = Project.create(
        root,
        name=project_name,
        preset=chosen_preset,
        target_duration=target,
        sources=[i.path for i in infos],
        input_path=str(Path(input_path).resolve()),
    )
    ui.ok(f"project folder ready: {root}")
    ui.note(f"target length: {format_duration(target)}")

    # --- picking -------------------------------------------------------------
    ui.heading("Now choose your clips")
    print(HELP)
    if single:
        ui.note(f"source: {infos[0].path.name} ({format_duration(infos[0].duration)})")

    segments = project.segments
    clips: list[Clip] = []
    while True:
        try:
            raw = ui.ask(f"select [{len(clips)} clips]")
        except ui.Abort:
            raw = "done"
        command = raw.strip().lower()

        if command in ("done", "d", ""):
            if not clips:
                if not ui.confirm("No clips chosen. Leave the project empty?", False):
                    continue
            break
        if command in ("quit", "q", "exit"):
            ui.warn("left without cutting. The project folder stays, run select again.")
            project.save()
            return project
        if command in ("help", "h", "?"):
            print(HELP)
            continue
        if command in ("files", "f"):
            _show_inventory(infos)
            continue
        if command in ("segments", "seg"):
            ui.note("segments: " + ", ".join(segments))
            continue
        if command in ("list", "l"):
            project.clips = clips
            _show_selection(project, infos)
            continue
        if command in ("undo", "u"):
            if clips:
                dropped = clips.pop()
                ui.note(f"dropped {dropped.id} ({format_duration(dropped.duration)})")
                project.clips = clips
                _show_budget(project)
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
                _show_budget(project)
            continue

        try:
            info, start, end, segment, label = _parse_entry(
                raw, infos, segments, single
            )
        except (TimecodeError, ValueError) as exc:
            ui.error(str(exc))
            continue

        project.clips = clips  # so next_clip_id sees what we have
        clip = Clip(
            id=project.next_clip_id(),
            source=str(info.path.resolve()),
            source_name=info.path.name,
            source_in=start,
            source_out=end,
            segment=segment,
            label=label,
        )
        clips.append(clip)
        project.clips = clips
        ui.ok(
            f"{clip.id}: {info.path.name} "
            f"{format_timecode(start)} -> {format_timecode(end)} "
            f"({format_duration(clip.duration)})"
            + (f"  #{segment}" if segment else "")
        )
        _show_budget(project)

    # --- cutting -------------------------------------------------------------
    project.clips = clips
    project.save()
    if not clips:
        ui.warn("no clips to cut")
        return project

    ui.heading(f"Cutting {len(clips)} clip(s) with ffmpeg")
    if not reencode:
        ui.warn(
            "stream-copy mode: cuts snap to keyframes, so in-points can drift "
            "by up to a couple of seconds"
        )
    selected_dir = project.dir("selected")
    written: list[Clip] = []
    for i, clip in enumerate(clips, 1):
        folder = selected_dir / (clip.segment or "unsorted")
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{clip.id}_{slugify(clip.label) if clip.label else 'clip'}"
        destination = folder / f"{stem}.mp4"
        ui.progress(i, len(clips), f"{clip.id} -> {destination.relative_to(project.root)}")
        try:
            cut(
                clip.source,
                clip.source_in,
                clip.duration,
                destination,
                reencode=reencode,
            )
        except ProbeError as exc:
            ui.error(f"{clip.id} failed: {exc}")
            continue
        clip.file = str(destination.relative_to(project.root)).replace("\\", "/")
        written.append(clip)

    project.clips = written
    project.mark_done("select")
    project.save()

    ui.banner("STEP 1 DONE")
    ui.ok(f"{len(written)} clip(s) in {project.dir('selected')}")
    _show_budget(project)
    ui.note(f"next:  python -m video_editor arrange \"{project.root}\"")
    return project
