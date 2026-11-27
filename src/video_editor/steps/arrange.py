"""STEP 2 - arrange: decide which clip comes after which clip.

The edge frames are read straight out of the ORIGINAL footage at the clip's
in and out points - nothing has been cut, so there is nothing to read but the
source. Each frame becomes a 64-bit fingerprint, and the cost of cutting from
one clip to another is how many of those bits differ.

Four ways to order a film:

  story    The preset's segment order (for a marriage: mehndi, haldi, baraat,
           varmala, pheras, vidaai, reception), frame-matched inside each
           segment. The right default for any event.
  match    Pure frame matching across everything: each cut lands on the most
           similar-looking frame available. Smoothest, ignores chronology.
  emotion  The preset's emotional arc, frame-matched inside each mood.
           Needs step 4.
  manual   You type the order.

Output is 02_arrangement/order.json and cuts.csv - definitions, not video.
"""

from __future__ import annotations

from pathlib import Path

from video_editor import ui
from video_editor.probe import frame_hash, hash_distance
from video_editor.project import Clip, Project
from video_editor.timecode import format_duration, format_timecode

MODES = ("story", "match", "emotion", "manual")

# Out of 64 bits: below this a cut reads as continuous.
SMOOTH_CUT = 14
# Above this it reads as a visible jump.
HARD_CUT = 26
# No information about a join: treated as an average cut.
UNKNOWN_COST = 32


def compute_hashes(project: Project, *, force: bool = False) -> list[Clip]:
    """Fingerprint each clip's first and last frame, read from the source."""
    clips = project.clips
    todo = [c for c in clips if force or c.head_hash is None or c.tail_hash is None]
    if not todo:
        return clips

    ui.heading(f"Reading the edge frames of {len(todo)} clip(s)")
    ui.note("two frames per clip, read in place from the original footage")
    for i, clip in enumerate(todo, 1):
        source = Path(clip.source)
        if not source.is_file():
            ui.warn(f"{clip.id}: source missing ({source.name}), cannot match it")
            continue
        ui.progress(i, len(todo), f"{clip.id} {clip.describe()}")
        length = clip.duration
        inset = min(0.12, max(length * 0.05, 0.02))
        clip.head_hash = frame_hash(source, clip.source_in + inset)
        clip.tail_hash = frame_hash(source, max(clip.source_in, clip.source_out - inset))

    by_id = {c.id: c for c in todo}
    merged = [by_id.get(c.id, c) for c in clips]
    project.clips = merged
    project.save()
    return merged


def join_cost(a: Clip, b: Clip) -> int:
    """How jarring the cut from a to b looks, 0 (seamless) to 64."""
    if a.tail_hash is None or b.head_hash is None:
        return UNKNOWN_COST
    return hash_distance(a.tail_hash, b.head_hash)


def chain_by_match(clips: list[Clip], first: Clip | None = None) -> list[Clip]:
    """Greedy nearest-neighbour chain over the join costs."""
    if len(clips) <= 1:
        return list(clips)
    remaining = list(clips)
    if first is None:
        # Open on the clip nothing else cuts into cleanly: it has no better home.
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
    """Preset segment order, frame-matched inside each segment."""
    order = {name: i for i, name in enumerate(project.segments)}
    buckets: dict[str, list[Clip]] = {}
    for clip in clips:
        buckets.setdefault(clip.segment or "~unsorted", []).append(clip)
    result: list[Clip] = []
    for segment in sorted(buckets, key=lambda s: (order.get(s, 999), s)):
        result.extend(chain_by_match(buckets[segment]))
    return result


def arrange_by_emotion(project: Project, clips: list[Clip]) -> list[Clip]:
    """The preset's emotional arc, frame-matched inside each mood."""
    arc = project.emotion_arc
    rank = {name: i for i, name in enumerate(arc)}
    buckets: dict[str, list[Clip]] = {}
    for clip in clips:
        buckets.setdefault(clip.emotion or "~none", []).append(clip)
    result: list[Clip] = []
    for mood in sorted(buckets, key=lambda m: (rank.get(m, 99), m)):
        result.extend(chain_by_match(buckets[mood]))
    return result


def arrange_manually(clips: list[Clip]) -> list[Clip]:
    """The user types the order: 'c003 c001 c004', or '3 1 4'."""
    by_id = {c.id: c for c in clips}
    by_index = {str(i): c for i, c in enumerate(clips, 1)}
    ui.note("type the ids or numbers in the order you want, space separated")
    ui.note("anything left out is appended at the end, in its current order")
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


def report(project: Project, chain: list[Clip]) -> dict[str, float]:
    """Print the running order and return its join statistics."""
    ui.heading("The running order")
    rows = []
    timeline = 0.0
    for position, clip in enumerate(chain, 1):
        if position == 1:
            quality = "-"
        else:
            cost = join_cost(chain[position - 2], clip)
            word = (
                "smooth" if cost <= SMOOTH_CUT
                else "ok" if cost <= HARD_CUT
                else "JUMP"
            )
            quality = f"{cost}/64 {word}"
        rows.append([
            position,
            clip.id,
            format_timecode(timeline),
            format_duration(clip.render_duration),
            clip.segment or "-",
            clip.emotion or "-",
            quality,
            clip.describe(),
        ])
        timeline += clip.render_duration
    ui.table(
        ["#", "id", "at", "length", "segment", "emotion", "cut into it", "what it is"],
        rows,
    )

    costs = [join_cost(chain[i - 1], chain[i]) for i in range(1, len(chain))]
    stats = {
        "cuts": len(costs),
        "smooth": sum(1 for c in costs if c <= SMOOTH_CUT),
        "jumps": sum(1 for c in costs if c > HARD_CUT),
        "average": round(sum(costs) / len(costs), 2) if costs else 0.0,
        "runtime": round(timeline, 3),
    }
    if costs:
        ui.note(
            f"{stats['cuts']} cuts: {stats['smooth']} smooth, "
            f"{stats['jumps']} visible jumps, average {stats['average']}/64"
        )
    ui.note(f"total runtime: {format_duration(timeline)}")
    return stats


def write_definition(project: Project, chain: list[Clip], mode: str, stats: dict) -> Path:
    """02_arrangement/order.json plus a cuts.csv you can read in a spreadsheet."""
    timeline = 0.0
    entries = []
    rows = ["position,clip_id,at,length,source,source_in,source_out,segment,emotion,join_cost,label"]
    for position, clip in enumerate(chain, 1):
        cost = join_cost(chain[position - 2], clip) if position > 1 else ""
        entries.append({
            "position": position,
            "id": clip.id,
            "at": round(timeline, 3),
            "duration": round(clip.render_duration, 3),
            "source": clip.source,
            "source_in": round(clip.source_in, 3),
            "source_out": round(clip.render_out, 3),
            "segment": clip.segment,
            "emotion": clip.emotion,
            "join_cost": cost,
        })
        rows.append(
            ",".join([
                str(position), clip.id, format_timecode(timeline),
                f"{clip.render_duration:.3f}", clip.source_name,
                f"{clip.source_in:.3f}", f"{clip.render_out:.3f}",
                clip.segment or "", clip.emotion or "", str(cost),
                (clip.label or "").replace(",", " "),
            ])
        )
        timeline += clip.render_duration

    project.write_report("arrangement", "cuts.csv", rows)
    return project.write_definition(
        "arrangement",
        "order.json",
        {
            "schema": 2,
            "project": project.name,
            "mode": mode,
            "statistics": stats,
            "thresholds": {"smooth_below": SMOOTH_CUT, "jump_above": HARD_CUT},
            "order": entries,
        },
    )


def run(
    project_path: str | Path,
    *,
    mode: str | None = None,
    first: str | None = None,
    rehash: bool = False,
    presets_dir: str | None = None,
    assume_yes: bool = False,
) -> Project:
    """Run step 2 and return the project."""
    project = Project.load(project_path, presets_dir)
    clips = project.clips
    if not clips:
        raise RuntimeError("this project has no clips yet. Run the select step first.")

    ui.banner("STEP 2 of 5 - ARRANGE", "Work out which clip belongs after which.")
    ui.note(f"project: {project.name} ({len(clips)} clips, {project.preset_name})")

    chosen = mode or (
        ui.choose("How should the clips be ordered?", list(MODES), default="story")
        if ui.interactive()
        else "story"
    )
    if chosen not in MODES:
        raise RuntimeError(f"unknown mode {chosen!r}. Choose from: {', '.join(MODES)}")

    if chosen != "manual":
        clips = compute_hashes(project, force=rehash)

    if chosen == "match":
        head = next((c for c in clips if c.id == first), None) if first else None
        if first and head is None:
            ui.warn(f"no clip with id {first}; letting the matcher pick the opener")
        chain = chain_by_match(clips, head)
    elif chosen == "story":
        chain = arrange_by_story(project, clips)
    elif chosen == "emotion":
        if not any(c.emotion for c in clips):
            ui.warn(
                "no clip has an emotion yet - run the emotions step first, or "
                "the arc is meaningless. Falling back to match."
            )
            chain = chain_by_match(clips)
        else:
            chain = arrange_by_emotion(project, clips)
    else:
        report(project, clips)
        chain = arrange_manually(clips)

    for position, clip in enumerate(chain, 1):
        clip.order = position
    project.clips = chain
    stats = report(project, chain)

    if ui.interactive() and not assume_yes and not ui.confirm("Keep this order?", True):
        ui.warn("order not saved. Run arrange again to try another mode.")
        return project

    definition = write_definition(project, chain, chosen, stats)
    project.mark_done("arrange")
    project.save()

    ui.banner("STEP 2 DONE")
    ui.ok(f"order written to {definition.relative_to(project.root)}")
    ui.note(f'next:  python -m video_editor music "{project.root}"')
    return project
