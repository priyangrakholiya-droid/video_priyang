"""STEP 4 - emotions: read the mood of every clip and file it in a folder.

After this step 05_emotion/ looks like this, with a hard link to every clip in
the bucket it belongs to:

    05_emotion/
      happy/      c004_cake.mp4  c011_dance-floor.mp4
      emotional/  c019_vidaai.mp4
      romantic/   c007_couple-walk.mp4
      fun/        c012_baraat.mp4
      ritual/     c015_pheras.mp4
      calm/       c002_decor.mp4
      index.csv   every clip, its scores and why it landed where it did

So when you want "all the emotional moments" for a montage, you open one
folder instead of scrubbing the whole wedding again.

Two backends, see video_editor/emotion.py for the honest limits of each:
  --backend heuristic   (default) energy and colour. Free, fast, approximate.
  --backend face        a real expression model, if you pip install fer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from video_editor import ui
from video_editor.emotion import (
    EmotionError,
    describe_scores,
    get_backend,
    is_uncertain,
    top_emotion,
)
from video_editor.project import EMOTIONS, Clip, Project
from video_editor.timecode import format_duration


def _clip_path(project: Project, clip: Clip) -> Path | None:
    if not clip.file:
        return None
    path = project.root / clip.file
    return path if path.is_file() else None


def analyse_clips(
    project: Project,
    backend_name: str,
    *,
    force: bool = False,
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
    uncertain: list[Clip] = []
    for i, clip in enumerate(todo, 1):
        path = _clip_path(project, clip)
        if path is None:
            ui.warn(f"{clip.id}: clip file missing, skipped")
            continue
        ui.progress(i, len(todo), f"{clip.id} {clip.label or clip.source_name}")
        try:
            scores, features = backend.score(path)
        except EmotionError as exc:
            ui.error(f"{clip.id}: {exc}")
            continue
        clip.emotion_scores = scores
        clip.emotion = top_emotion(scores)
        detail = describe_scores(scores)
        if is_uncertain(scores):
            uncertain.append(clip)
            ui.warn(f"    {clip.emotion}  (close call: {detail})")
        else:
            ui.note(f"   {clip.emotion}  ({detail})")

    by_id = {c.id: c for c in todo}
    merged = [by_id.get(c.id, c) for c in clips]
    project.clips = merged

    if uncertain:
        ui.warn(
            f"{len(uncertain)} clip(s) were close calls - worth a look with "
            "'review' below"
        )
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
        raw = ui.ask("review").strip()
        command = raw.lower()
        if command in ("done", "d", ""):
            break
        if command in ("list", "l"):
            _report(project)
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
        clip.notes = (clip.notes + " set by hand").strip()
        ui.ok(f"{clip_id} -> {matches[0]}")
    project.clips = clips
    return clips


def _report(project: Project) -> None:
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
                c.label or c.source_name,
            ]
            for c in clips
        ],
    )
    counts: dict[str, list[Clip]] = {}
    for clip in clips:
        counts.setdefault(clip.emotion or "unsorted", []).append(clip)
    ui.heading("Totals per folder")
    ui.table(
        ["emotion", "clips", "runtime"],
        [
            [
                name,
                len(group),
                format_duration(sum(c.render_duration for c in group)),
            ]
            for name, group in sorted(
                counts.items(), key=lambda kv: -len(kv[1])
            )
        ],
    )


def _file_into_folders(project: Project) -> None:
    """Hard-link (or copy) each clip into 05_emotion/<emotion>/."""
    root = project.dir("emotion")
    for emotion in EMOTIONS:
        folder = root / emotion
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("*"):
            if stale.is_file():
                stale.unlink()

    filed = 0
    for clip in project.ordered_clips():
        source = _clip_path(project, clip)
        if source is None or not clip.emotion:
            continue
        folder = root / clip.emotion
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / source.name
        try:
            if destination.exists():
                destination.unlink()
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        filed += 1

    lines = ["clip_id,emotion,file,length,segment,label," + ",".join(EMOTIONS)]
    for clip in project.ordered_clips():
        lines.append(
            ",".join(
                [
                    clip.id,
                    clip.emotion or "",
                    Path(clip.file).name if clip.file else "",
                    f"{clip.render_duration:.3f}",
                    clip.segment or "",
                    (clip.label or "").replace(",", " "),
                ]
                + [f"{clip.emotion_scores.get(e, 0.0):.4f}" for e in EMOTIONS]
            )
        )
    (root / "index.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ui.ok(f"{filed} clip(s) filed under {root}")
    ui.note("index.csv holds every score, so you can re-sort them yourself")


def run(
    project_path: str | Path,
    *,
    backend: str = "heuristic",
    force: bool = False,
    skip_review: bool = False,
) -> Project:
    """Run step 4 and return the project."""
    project = Project.load(project_path)
    if not project.clips:
        raise RuntimeError("no clips in this project. Run the select step first.")

    ui.banner(
        "STEP 4 of 5 - EMOTIONS",
        "Sort every clip into the feeling it carries.",
    )
    ui.note(f"project: {project.name}")
    if backend == "heuristic":
        ui.note(
            "heuristic backend: judges energy, light and sound - not faces. "
            "Expect to correct a few."
        )

    analyse_clips(project, backend, force=force)
    project.save()
    _report(project)

    if ui.interactive() and not skip_review:
        if ui.confirm("Correct any of these by hand?", False):
            review(project)
            project.save()
            _report(project)

    _file_into_folders(project)
    project.data["emotion_backend"] = backend
    project.mark_done("emotions")
    project.save()

    ui.banner("STEP 4 DONE")
    ui.note(f"next:  python -m video_editor render \"{project.root}\"")
    return project
