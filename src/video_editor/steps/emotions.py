"""STEP 4 - emotions: read the mood of every clip and record it.

In schema 1 this step hard-linked copies of the footage into folders named
after feelings. It does not any more: a clip is a reference, so its emotion is
a field, and the groups are a document you can read:

    04_emotion/scores.json    every clip, all six scores, and why
    04_emotion/emotions.csv   the same thing for a spreadsheet
    04_emotion/groups.json    the clip ids in each bucket, in order

That is strictly more useful than folders of duplicated video: you get the
scores, not just the winner, and the file is a few kilobytes.

The clip is measured in place - ffmpeg reads the original footage between the
clip's in and out points. Nothing is extracted.

Two backends, see video_editor/emotion.py for the honest limits of each:
  --backend heuristic   (default) energy, light and sound. Free and fast.
  --backend face        a real expression model, if `pip install fer` is done.
"""

from __future__ import annotations

from pathlib import Path

from video_editor import ui
from video_editor.emotion import (
    EmotionError,
    describe_scores,
    get_backend,
    is_uncertain,
    top_emotion,
)
from video_editor.presets import EMOTIONS
from video_editor.project import Clip, Project
from video_editor.timecode import format_duration

# How much a segment's own mood is allowed to pull the score. The picture and
# the sound decide; the preset only breaks ties.
SEGMENT_PRIOR = 0.15


def apply_segment_prior(project: Project, clip: Clip, scores: dict[str, float]) -> dict[str, float]:
    """Nudge a clip towards the mood its segment usually carries.

    A clip tagged #vidaai is probably emotional and a clip tagged #dance is
    probably fun, and that knowledge is already in the preset. It is applied
    as a small prior, not an override, so bright happy footage in the vidaai
    can still score happy.
    """
    if not clip.segment or project._preset is None:
        return scores
    mood = project.preset.mood_of(clip.segment)
    if not mood or mood not in scores:
        return scores
    nudged = dict(scores)
    nudged[mood] = nudged.get(mood, 0.0) + SEGMENT_PRIOR
    total = sum(nudged.values()) or 1.0
    return {k: round(v / total, 4) for k, v in nudged.items()}


def analyse_clips(
    project: Project,
    backend_name: str,
    *,
    force: bool = False,
    use_prior: bool = True,
) -> list[Clip]:
    """Score every clip and store the result in the manifest."""
    backend = get_backend(backend_name)
    if not backend.available():
        raise EmotionError(
            f"the {backend_name!r} backend is not available here. "
            "Install its model, or use --backend heuristic."
        )

    clips = project.clips
    todo = [c for c in clips if force or not c.emotion]
    if not todo:
        ui.note("every clip already has an emotion; pass --force to redo them")
        return clips

    ui.heading(f"Reading {len(todo)} clip(s) with the {backend.name} backend")
    ui.note("each clip is measured in place, inside the original footage")
    uncertain = 0
    for i, clip in enumerate(todo, 1):
        source = Path(clip.source)
        if not source.is_file():
            ui.warn(f"{clip.id}: source missing ({source.name}), skipped")
            continue
        ui.progress(i, len(todo), f"{clip.id} {clip.describe()}")
        try:
            scores, _features = backend.score(
                source, start=clip.source_in, duration=clip.duration
            )
        except EmotionError as exc:
            ui.error(f"{clip.id}: {exc}")
            continue
        if use_prior:
            scores = apply_segment_prior(project, clip, scores)
        clip.emotion_scores = scores
        clip.emotion = top_emotion(scores)
        detail = describe_scores(scores)
        if is_uncertain(scores):
            uncertain += 1
            ui.warn(f"    {clip.emotion}  (close call: {detail})")
        else:
            ui.note(f"   {clip.emotion}  ({detail})")

    by_id = {c.id: c for c in todo}
    merged = [by_id.get(c.id, c) for c in clips]
    project.clips = merged
    if uncertain:
        ui.warn(f"{uncertain} clip(s) were close calls - worth reviewing")
    return merged


def review(project: Project) -> list[Clip]:
    """Let the user correct any clip the machine got wrong."""
    clips = project.clips
    ui.heading("Review and correct")
    ui.note("type: <clip id> <emotion>   e.g.  c007 romantic")
    ui.note(f"emotions: {', '.join(EMOTIONS)}")
    ui.note("'list' to see them all, 'done' when happy")
    by_id = {c.id: c for c in clips}
    while True:
        try:
            raw = ui.ask("review").strip()
        except ui.Abort:
            break
        command = raw.lower()
        if command in ("done", "d", ""):
            break
        if command in ("list", "l"):
            report(project)
            continue
        parts = raw.split()
        if len(parts) != 2:
            ui.error("give a clip id and an emotion, e.g. c007 romantic")
            continue
        clip_id, wanted = parts[0], parts[1].lower()
        clip = by_id.get(clip_id)
        if clip is None:
            ui.error(f"no clip with id {clip_id}")
            continue
        matches = [e for e in EMOTIONS if e.startswith(wanted)]
        if not matches:
            ui.error(f"unknown emotion {wanted!r}. Pick from: {', '.join(EMOTIONS)}")
            continue
        clip.emotion = matches[0]
        clip.notes = (clip.notes + " | set by hand").strip(" |")
        ui.ok(f"{clip_id} -> {matches[0]}")
    project.clips = clips
    return clips


def group_clips(project: Project) -> dict[str, list[Clip]]:
    groups: dict[str, list[Clip]] = {e: [] for e in EMOTIONS}
    for clip in project.ordered_clips():
        groups.setdefault(clip.emotion or "unsorted", []).append(clip)
    return {name: members for name, members in groups.items() if members}


def report(project: Project) -> None:
    clips = project.ordered_clips()
    ui.heading("Emotions")
    ui.table(
        ["id", "emotion", "length", "segment", "top scores", "what it is"],
        [
            [
                c.id,
                c.emotion or "-",
                format_duration(c.render_duration),
                c.segment or "-",
                describe_scores(c.emotion_scores, top=2) if c.emotion_scores else "-",
                c.describe(),
            ]
            for c in clips
        ],
    )
    ui.heading("Totals per emotion")
    groups = group_clips(project)
    ui.table(
        ["emotion", "clips", "runtime", "clip ids"],
        [
            [
                name,
                len(members),
                format_duration(sum(c.render_duration for c in members)),
                " ".join(c.id for c in members),
            ]
            for name, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        ],
    )


def write_definition(project: Project, backend: str) -> Path:
    """Write scores.json, groups.json and emotions.csv."""
    clips = project.ordered_clips()
    groups = group_clips(project)

    project.write_definition(
        "emotion",
        "groups.json",
        {
            "schema": 2,
            "project": project.name,
            "backend": backend,
            "arc": project.emotion_arc,
            "groups": {
                name: {
                    "clips": [c.id for c in members],
                    "count": len(members),
                    "runtime": round(sum(c.render_duration for c in members), 3),
                }
                for name, members in groups.items()
            },
        },
    )

    rows = [
        "clip_id,emotion,length,segment,source,source_in,label," + ",".join(EMOTIONS)
    ]
    for clip in clips:
        rows.append(
            ",".join(
                [
                    clip.id,
                    clip.emotion or "",
                    f"{clip.render_duration:.3f}",
                    clip.segment or "",
                    clip.source_name,
                    f"{clip.source_in:.3f}",
                    (clip.label or "").replace(",", " "),
                ]
                + [f"{clip.emotion_scores.get(e, 0.0):.4f}" for e in EMOTIONS]
            )
        )
    project.write_report("emotion", "emotions.csv", rows)

    return project.write_definition(
        "emotion",
        "scores.json",
        {
            "schema": 2,
            "project": project.name,
            "backend": backend,
            "segment_prior": SEGMENT_PRIOR,
            "clips": [
                {
                    "id": clip.id,
                    "emotion": clip.emotion,
                    "scores": clip.emotion_scores,
                    "segment": clip.segment,
                    "source": clip.source,
                    "source_in": round(clip.source_in, 3),
                    "duration": round(clip.render_duration, 3),
                    "notes": clip.notes,
                }
                for clip in clips
            ],
        },
    )


def run(
    project_path: str | Path,
    *,
    backend: str = "heuristic",
    force: bool = False,
    skip_review: bool = False,
    no_prior: bool = False,
    presets_dir: str | None = None,
) -> Project:
    """Run step 4 and return the project."""
    project = Project.load(project_path, presets_dir)
    if not project.clips:
        raise RuntimeError("no clips in this project. Run the select step first.")

    ui.banner("STEP 4 of 5 - EMOTIONS", "Read the feeling each clip carries.")
    ui.note(f"project: {project.name}")
    if backend == "heuristic":
        ui.note(
            "heuristic backend: judges energy, light and sound - not faces. "
            "Expect to correct a few."
        )

    analyse_clips(project, backend, force=force, use_prior=not no_prior)
    project.save()
    report(project)

    if ui.interactive() and not skip_review:
        if ui.confirm("Correct any of these by hand?", False):
            review(project)
            project.save()
            report(project)

    definition = write_definition(project, backend)
    project.data["emotion_backend"] = backend
    project.mark_done("emotions")
    project.save()

    ui.banner("STEP 4 DONE")
    ui.ok(f"scores written to {definition.relative_to(project.root)}")
    ui.note("groups.json lists the clip ids per feeling - no video was copied")
    ui.note(f'next:  python -m video_editor render "{project.root}"')
    return project
