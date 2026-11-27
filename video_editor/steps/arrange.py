"""STEP 2 - arrange: decide which clip comes after which clip.

The question this step answers is "what do I put next?". Four ways to answer:

  match      Look at the LAST frame of every clip and the FIRST frame of every
             other clip, and chain them so each cut lands on the most similar
             looking frame. This is what makes an edit feel continuous instead
             of jumpy: a wide shot of the mandap follows a wide shot of the
             mandap, not a close-up of a shoe.

  story      Follow the preset's segment order (mehndi -> haldi -> baraat ->
             varmala -> pheras -> vidaai -> reception), then match inside each
             segment. This is the one you want for a wedding film.

  emotion    Build an arc: calm -> happy -> fun -> romantic -> ritual ->
             emotional. Needs step 4 to have run.

  manual     You type the order.

The order is written back to project.json and mirrored as numbered files in
03_arranged/, with a concat list and an EDL that any editor can read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from video_editor import ui
from video_editor.probe import frame_hash, hash_distance
from video_editor.project import Clip, Project
from video_editor.timecode import format_duration, format_timecode

MODES = ("match", "story", "emotion", "manual")

# The emotional shape of a wedding film, start to finish.
EMOTION_ARC = ("calm", "happy", "fun", "romantic", "ritual", "emotional")

# Two frames closer than this (out of 64 bits) count as a smooth join.
SMOOTH_CUT = 14
# Beyond this the cut is a visible jump.
HARD_CUT = 26


def _clip_path(project: Project, clip: Clip) -> Path | None:
    if not clip.file:
        return None
    path = project.root / clip.file
    return path if path.is_file() else None


def compute_hashes(project: Project, *, force: bool = False) -> list[Clip]:
    """Fill in each clip's first-frame and last-frame hash."""
    clips = project.clips
    todo = [
        c for c in clips
        if force or c.head_hash is None or c.tail_hash is None
    ]
    if not todo:
        return clips

    ui.heading(f"Reading the first and last frame of {len(todo)} clip(s)")
    for i, clip in enumerate(todo, 1):
        path = _clip_path(project, clip)
        if path is None:
            ui.warn(f"{clip.id}: clip file missing, cannot match it")
            continue
        ui.progress(i, len(todo), clip.id)
        length = clip.duration
        # A hair inside the clip: the very first/last frame is often a fade.
        clip.head_hash = frame_hash(path, min(0.08, length * 0.05))
        clip.tail_hash = frame_hash(path, max(0.0, length - max(0.12, length * 0.05)))

    by_id = {c.id: c for c in todo}
    merged = [by_id.get(c.id, c) for c in clips]
    project.clips = merged
    project.save()
    return merged


def join_cost(a: Clip, b: Clip) -> int:
    """How jarring the cut from clip a to clip b looks. Lower is smoother."""
    if a.tail_hash is None or b.head_hash is None:
        return 32  # no information: treat as an average cut
    return hash_distance(a.tail_hash, b.head_hash)


def chain_by_match(clips: list[Clip], first: Clip | None = None) -> list[Clip]:
    """Greedy nearest-neighbour chain over the frame hashes.

    Start somewhere, then repeatedly take whichever unused clip opens on the
    frame most like the one we are leaving.
    """
    if len(clips) <= 1:
        return list(clips)

    remaining = list(clips)
    if first is None:
        # Open on the clip that is the *worst* follower - nothing matches into
        # it anyway, so it earns its place at the front.
        first = max(
            remaining,
            key=lambda c: min(
                (join_cost(other, c) for other in remaining if other.id != c.id),
                default=0,
            ),
        )
    remaining.remove(first)
    chain = [first]
    while remaining:
        current = chain[-1]
        nxt = min(remaining, key=lambda c: (join_cost(current, c), c.id))
        remaining.remove(nxt)
        chain.append(nxt)
    return chain


def arrange_by_story(project: Project, clips: list[Clip]) -> list[Clip]:
    """Segment order from the preset, frame-matched inside each segment."""
    order = {name: i for i, name in enumerate(project.segments)}
    buckets: dict[str, list[Clip]] = {}
    for clip in clips:
        buckets.setdefault(clip.segment or "~unsorted", []).append(clip)

    result: list[Clip] = []
    for segment in sorted(buckets, key=lambda s: (order.get(s, 999), s)):
        result.extend(chain_by_match(buckets[segment]))
    return result


def arrange_by_emotion(clips: list[Clip]) -> list[Clip]:
    """Walk the emotional arc, frame-matched inside each mood."""
    buckets: dict[str, list[Clip]] = {}
    for clip in clips:
        buckets.setdefault(clip.emotion or "~none", []).append(clip)
    rank = {name: i for i, name in enumerate(EMOTION_ARC)}
    result: list[Clip] = []
    for mood in sorted(buckets, key=lambda m: (rank.get(m, 99), m)):
        result.extend(chain_by_match(buckets[mood]))
    return result


def arrange_manually(clips: list[Clip]) -> list[Clip]:
    """Let the user type the order, e.g. 'c003 c001 c004' or '3 1 4'."""
    by_id = {c.id: c for c in clips}
    by_index = {str(i): c for i, c in enumerate(clips, 1)}
    ui.note("type the ids or numbers in the order you want, separated by spaces")
    ui.note("anything you leave out is appended at the end in its current order")
    while True:
        raw = ui.ask("order")
        if not raw.strip():
            return list(clips)
        picked: list[Clip] = []
        unknown: list[str] = []
        seen: set[str] = set()
        for token in raw.split():
            clip = by_id.get(token) or by_index.get(token)
            if clip is None:
                unknown.append(token)
            elif clip.id not in seen:
                seen.add(clip.id)
                picked.append(clip)
        if unknown:
            ui.error(f"not a clip: {', '.join(unknown)}")
            continue
        rest = [c for c in clips if c.id not in seen]
        if rest:
            ui.note(f"appending {len(rest)} clip(s) you did not mention")
        return picked + rest


def _report(project: Project, chain: list[Clip]) -> None:
    ui.heading("The running order")
    rows = []
    for position, clip in enumerate(chain, 1):
        if position == 1:
            cost_text = "-"
        else:
            cost = join_cost(chain[position - 2], clip)
            quality = (
                "smooth" if cost <= SMOOTH_CUT
                else "ok" if cost <= HARD_CUT
                else "JUMP"
            )
            cost_text = f"{cost}/64 {quality}"
        rows.append([
            position,
            clip.id,
            format_duration(clip.render_duration),
            clip.segment or "-",
            clip.emotion or "-",
            cost_text,
            clip.label or clip.source_name,
        ])
    ui.table(
        ["#", "id", "length", "segment", "emotion", "cut into it", "what it is"],
        rows,
    )
    costs = [join_cost(chain[i - 1], chain[i]) for i in range(1, len(chain))]
    if costs:
        smooth = sum(1 for c in costs if c <= SMOOTH_CUT)
        jumps = sum(1 for c in costs if c > HARD_CUT)
        ui.note(
            f"{len(costs)} cuts: {smooth} smooth, {jumps} visible jumps, "
            f"average distance {sum(costs) / len(costs):.1f}/64"
        )
    ui.note(f"total runtime: {format_duration(sum(c.render_duration for c in chain))}")


def _write_outputs(project: Project, chain: list[Clip]) -> None:
    """Mirror the order into 03_arranged/ as numbered files, plus lists."""
    out_dir = project.dir("arranged")
    for stale in out_dir.glob("*"):
        if stale.is_file():
            stale.unlink()

    concat_lines: list[str] = []
    edl_lines = ["position,clip_id,file,source,source_in,source_out,duration,segment,emotion"]
    for position, clip in enumerate(chain, 1):
        source_file = _clip_path(project, clip)
        if source_file is None:
            ui.warn(f"{clip.id}: no clip file to copy into 03_arranged")
            continue
        stem = f"{position:03d}_{clip.id}"
        if clip.label:
            from video_editor.project import slugify

            stem += f"_{slugify(clip.label)}"
        destination = out_dir / f"{stem}{source_file.suffix}"
        try:  # a hard link costs no disk space; fall back to a copy
            if destination.exists():
                destination.unlink()
            import os

            os.link(source_file, destination)
        except OSError:
            shutil.copy2(source_file, destination)
        # ffmpeg concat wants forward slashes and escaped quotes.
        concat_lines.append(f"file '{destination.as_posix()}'")
        edl_lines.append(
            ",".join([
                str(position),
                clip.id,
                destination.name,
                clip.source_name,
                f"{clip.source_in:.3f}",
                f"{clip.source_out:.3f}",
                f"{clip.render_duration:.3f}",
                clip.segment or "",
                clip.emotion or "",
            ])
        )

    (out_dir / "concat.txt").write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    (out_dir / "edl.csv").write_text("\n".join(edl_lines) + "\n", encoding="utf-8")
    ui.ok(f"{len(concat_lines)} clip(s) laid out in {out_dir}")
    ui.note("concat.txt feeds ffmpeg; edl.csv opens in Excel or any NLE")


def run(
    project_path: str | Path,
    *,
    mode: str | None = None,
    first: str | None = None,
    rehash: bool = False,
) -> Project:
    """Run step 2 and return the project."""
    project = Project.load(project_path)
    clips = project.clips
    if not clips:
        raise RuntimeError(
            "this project has no clips yet. Run the select step first."
        )

    ui.banner(
        "STEP 2 of 5 - ARRANGE",
        "Work out which clip belongs after which clip.",
    )
    ui.note(f"project: {project.name} ({len(clips)} clips)")

    chosen = mode or ui.choose(
        "How should the clips be ordered?",
        list(MODES),
        default="story" if project.preset != "general" else "match",
    )
    if chosen not in MODES:
        raise RuntimeError(f"unknown mode {chosen!r}. Choose from: {', '.join(MODES)}")

    if chosen in ("match", "story", "emotion"):
        clips = compute_hashes(project, force=rehash)

    if chosen == "match":
        head = next((c for c in clips if c.id == first), None) if first else None
        if first and head is None:
            ui.warn(f"no clip with id {first}; letting the matcher choose the opener")
        chain = chain_by_match(clips, head)
    elif chosen == "story":
        chain = arrange_by_story(project, clips)
    elif chosen == "emotion":
        if not any(c.emotion for c in clips):
            ui.warn(
                "no clip has an emotion yet - run the emotions step first, "
                "or the arc will be meaningless. Falling back to match."
            )
            chain = chain_by_match(clips)
        else:
            chain = arrange_by_emotion(clips)
    else:
        _report(project, clips)
        chain = arrange_manually(clips)

    for position, clip in enumerate(chain, 1):
        clip.order = position
    project.clips = chain
    _report(project, chain)

    if ui.interactive() and not ui.confirm("Keep this order?", True):
        ui.warn("order not saved. Run arrange again to try another mode.")
        return project

    _write_outputs(project, chain)
    project.mark_done("arrange")
    project.save()

    ui.banner("STEP 2 DONE")
    ui.note(f"next:  python -m video_editor music \"{project.root}\"")
    return project
