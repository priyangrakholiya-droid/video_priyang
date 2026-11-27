"""Command line entry point - for a person at a terminal, and for an agent.

Every command takes `--json`, which silences the human output and prints one
JSON document on stdout instead. Every question a step would ask can be
answered with a flag, so nothing ever blocks. Those two properties together
are what make this drivable by Claude or any other agent - see CLAUDE.md.

    python -m video_editor select   <footage>    step 1: what to keep
    python -m video_editor arrange  [project]    step 2: what order
    python -m video_editor music    [project]    step 3: cut to the beat
    python -m video_editor emotions [project]    step 4: read the mood
    python -m video_editor render   [project]    step 5: make the film

    python -m video_editor run      <footage>    all five, unattended
    python -m video_editor status   [project]    where am I?
    python -m video_editor plan     [project]    the edit plan
    python -m video_editor list                  every project
    python -m video_editor presets               every kind of event
    python -m video_editor doctor                is this machine ready?
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from video_editor import __version__, ui
from video_editor.beats import BeatError
from video_editor.detect import DetectError
from video_editor.emotion import BACKENDS, EmotionError
from video_editor.presets import PresetError, load_all
from video_editor.presets import names as preset_names
from video_editor.probe import FFmpegMissing, ProbeError
from video_editor.project import (
    MANIFEST_NAME,
    STEP_ORDER,
    Project,
    ProjectError,
)
from video_editor.steps import arrange, emotions, music, render, select
from video_editor.steps.music import GROUPS
from video_editor.timecode import TimecodeError, format_duration

DEFAULT_PROJECTS_DIR = Path("projects")


def emit(payload: object) -> None:
    """Print one JSON document on stdout. The only thing --json writes."""
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


def _projects_dir(args: argparse.Namespace) -> Path:
    path = Path(getattr(args, "projects_dir", None) or DEFAULT_PROJECTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_project(given: str | None, args: argparse.Namespace) -> Path:
    """Accept a path, a project name, or nothing (the only project there is)."""
    if given:
        candidate = Path(given).expanduser()
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
        inside = _projects_dir(args) / given
        if (inside / MANIFEST_NAME).is_file():
            return inside
        raise ProjectError(
            f"no project at {given}. Run `video_editor list` to see what there is."
        )

    found = sorted(p.parent for p in _projects_dir(args).glob(f"*/{MANIFEST_NAME}"))
    if not found:
        raise ProjectError(
            "no projects yet. Start with: python -m video_editor select <footage>"
        )
    if len(found) == 1:
        return found[0]
    if getattr(args, "json", False):
        raise ProjectError(
            "several projects exist - name the one you mean: "
            + ", ".join(p.name for p in found)
        )
    names = [p.name for p in found]
    picked = ui.choose("Which project?", names)
    return found[names.index(picked)]


# ------------------------------------------------------------------- commands
def cmd_select(args: argparse.Namespace) -> int:
    project = select.run(
        args.footage,
        projects_dir=_projects_dir(args),
        name=args.name,
        preset_name=args.preset,
        minutes=args.minutes,
        mode=args.mode,
        threshold=args.threshold,
        min_gap=args.min_gap,
        presets_dir=args.presets_dir,
        quiet=args.json,
    )
    if args.json:
        emit(project.summary())
    return 0


def cmd_arrange(args: argparse.Namespace) -> int:
    project = arrange.run(
        _resolve_project(args.project, args),
        mode=args.mode,
        first=args.first,
        rehash=args.rehash,
        presets_dir=args.presets_dir,
        assume_yes=args.yes or args.json,
    )
    if args.json:
        emit(project.summary())
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    project = music.run(
        _resolve_project(args.project, args),
        song=args.song,
        group=args.snap,
        fit=args.fit,
        beats_per_bar=args.beats_per_bar,
        presets_dir=args.presets_dir,
    )
    if args.json:
        emit(project.summary())
    return 0


def cmd_emotions(args: argparse.Namespace) -> int:
    project = emotions.run(
        _resolve_project(args.project, args),
        backend=args.backend,
        force=args.force,
        skip_review=args.no_review or args.json,
        no_prior=args.no_prior,
        presets_dir=args.presets_dir,
    )
    if args.json:
        emit(project.summary())
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    path = _resolve_project(args.project, args)
    result = render.run(
        path,
        audio=args.audio,
        size=args.size,
        fps=args.fps,
        crf=args.crf,
        preset=args.x264_preset,
        music_volume=args.music_volume,
        original_volume=args.original_volume,
        fade=args.fade,
        align_music=not args.no_align_music,
        keep_temp=args.keep_temp,
        dry_run=args.dry_run,
        assume_yes=args.yes or args.json,
        presets_dir=args.presets_dir,
    )
    if args.json:
        summary = Project.load(path, args.presets_dir).summary()
        summary["rendered"] = str(result) if result else None
        emit(summary)
    return 0 if (result or args.dry_run) else 1


def cmd_run(args: argparse.Namespace) -> int:
    """All five steps, back to back, no questions if the flags are given."""
    ui.banner(
        "VIDEO EDITOR - FULL PIPELINE",
        "select -> arrange -> music -> emotions -> render",
    )
    project = select.run(
        args.footage,
        projects_dir=_projects_dir(args),
        name=args.name,
        preset_name=args.preset,
        minutes=args.minutes,
        mode=args.mode or "auto",
        threshold=args.threshold,
        min_gap=args.min_gap,
        presets_dir=args.presets_dir,
        quiet=args.json,
    )
    if not project.clips:
        if args.json:
            emit({"error": "no clips were selected", "project": project.summary()})
        else:
            ui.warn("no clips were selected, stopping here")
        return 1

    arrange.run(
        project.root,
        mode=args.arrange_mode,
        presets_dir=args.presets_dir,
        assume_yes=True,
    )
    if args.song:
        music.run(
            project.root,
            song=args.song,
            group=args.snap,
            fit=args.fit,
            presets_dir=args.presets_dir,
        )
    elif not args.json:
        ui.note("no --song given, skipping the music step")
    emotions.run(
        project.root,
        backend=args.backend,
        skip_review=True,
        presets_dir=args.presets_dir,
    )
    result = render.run(
        project.root,
        audio=args.audio,
        dry_run=args.dry_run,
        assume_yes=True,
        presets_dir=args.presets_dir,
    )
    if args.json:
        summary = Project.load(project.root, args.presets_dir).summary()
        summary["rendered"] = str(result) if result else None
        emit(summary)
    return 0 if (result or args.dry_run) else 1


def cmd_status(args: argparse.Namespace) -> int:
    project = Project.load(_resolve_project(args.project, args), args.presets_dir)
    if args.json:
        emit(project.summary())
        return 0

    ui.banner(project.name, str(project.root))
    ui.table(
        ["step", "state"],
        [[step, "done" if project.is_done(step) else "-"] for step in STEP_ORDER],
    )
    music_info = project.data.get("music") or {}
    output = project.data.get("output") or {}
    ui.heading("Numbers")
    ui.table(
        ["what", "value"],
        [
            ["preset", project.preset_name],
            ["target length", format_duration(project.target_duration)],
            ["clips", len(project.clips)],
            ["selected", format_duration(project.selected_duration)],
            ["after beat snap", format_duration(project.render_duration)],
            ["song", Path(music_info.get("file", "")).name or "-"],
            ["tempo", f"{music_info.get('bpm', 0):.1f} BPM" if music_info else "-"],
            ["output", output.get("file", "-")],
        ],
    )
    if project.clips:
        ui.heading("Clips")
        ui.table(
            ["#", "id", "length", "segment", "emotion", "source", "what it is"],
            [
                [
                    c.order if c.order is not None else "-",
                    c.id,
                    format_duration(c.render_duration),
                    c.segment or "-",
                    c.emotion or "-",
                    c.source_name,
                    c.label or "-",
                ]
                for c in project.ordered_clips()
            ],
        )
    nxt = project.next_step()
    if nxt:
        ui.note(f'next:  python -m video_editor {nxt} "{project.root}"')
    else:
        ui.ok("every step is done")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Print the portable edit plan: the film as pure data."""
    project = Project.load(_resolve_project(args.project, args), args.presets_dir)
    plan = project.edit_plan()
    if args.json:
        emit(plan)
        return 0
    ui.banner(f"Edit plan - {project.name}", f"{len(plan['clips'])} clips")
    ui.table(
        ["#", "at", "length", "source", "in", "segment", "emotion", "label"],
        [
            [
                entry["position"],
                entry["starts_at"],
                entry["duration"],
                Path(entry["source"]).name,
                entry["source_in"],
                entry["segment"] or "-",
                entry["emotion"] or "-",
                entry["label"] or "-",
            ]
            for entry in plan["clips"]
        ],
    )
    ui.note(f"runtime {format_duration(plan['runtime'])}")
    ui.note(f"the same thing as JSON lives in {project.root / 'edit.json'}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    base = _projects_dir(args)
    rows = []
    payload = []
    for manifest in sorted(base.glob(f"*/{MANIFEST_NAME}")):
        try:
            project = Project.load(manifest.parent, args.presets_dir)
        except ProjectError:
            continue
        summary = project.summary()
        payload.append(summary)
        rows.append([
            manifest.parent.name,
            summary["preset"],
            summary["clips"],
            format_duration(summary["render_duration"]),
            f"{len(summary['steps_done'])}/5",
            summary["updated"][:16],
        ])

    if args.json:
        emit({"projects_dir": str(base.resolve()), "projects": payload})
        return 0
    ui.banner("Projects", str(base.resolve()))
    if not rows:
        ui.note("none yet. Start with: python -m video_editor select <footage>")
        return 0
    ui.table(["folder", "preset", "clips", "runtime", "steps", "updated"], rows)
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    """Every kind of event this build knows how to cut."""
    everything = load_all(args.presets_dir)
    if args.json:
        emit({
            "presets": [p.to_dict() for p in everything.values()],
        })
        return 0

    ui.banner("Event presets", "config/presets/*.json - add a file, get a preset")
    ui.table(
        ["name", "title", "target", "segments", "snap", "audio"],
        [
            [
                preset.name,
                preset.title,
                f"{preset.target_minutes:g}m",
                len(preset.segments),
                preset.pacing_value("snap"),
                preset.audio.get("mode", "-"),
            ]
            for preset in sorted(everything.values(), key=lambda p: p.name)
        ],
    )
    if args.verbose:
        for preset in sorted(everything.values(), key=lambda p: p.name):
            ui.heading(f"{preset.name} - {preset.title}")
            ui.note(preset.description)
            ui.table(
                ["segment", "mood", "required", "matches"],
                [
                    [s.id, s.mood or "-", "yes" if s.required else "", ", ".join(s.keywords)]
                    for s in preset.segments
                ],
            )
            ui.note("arc: " + " -> ".join(preset.emotion_arc))
    else:
        ui.note("add --verbose to see each preset's segments")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that this machine can actually run the pipeline."""
    checks: list[dict[str, object]] = []

    for tool in ("ffmpeg", "ffprobe"):
        where = shutil.which(tool)
        checks.append({
            "check": tool,
            "ok": bool(where),
            "detail": where or f"not on PATH - install ffmpeg, then reopen the terminal",
        })

    checks.append({
        "check": "python",
        "ok": sys.version_info >= (3, 10),
        "detail": sys.version.split()[0],
    })

    try:
        found = load_all(args.presets_dir)
        checks.append({
            "check": "presets",
            "ok": True,
            "detail": f"{len(found)} loaded: {', '.join(sorted(found))}",
        })
    except PresetError as exc:
        checks.append({"check": "presets", "ok": False, "detail": str(exc)})

    try:
        from video_editor.emotion import FaceBackend

        available = FaceBackend().available()
    except Exception:  # noqa: BLE001
        available = False
    checks.append({
        "check": "face backend (optional)",
        "ok": True,
        "detail": "installed" if available else "not installed - `pip install fer` to enable",
    })

    base = _projects_dir(args)
    checks.append({
        "check": "projects dir",
        "ok": base.is_dir(),
        "detail": str(base.resolve()),
    })

    failed = [c for c in checks if not c["ok"]]
    if args.json:
        emit({"ready": not failed, "checks": checks})
        return 0 if not failed else 2

    ui.banner("Doctor", "can this machine cut a film?")
    ui.table(
        ["check", "state", "detail"],
        [[c["check"], "ok" if c["ok"] else "FAIL", c["detail"]] for c in checks],
    )
    if failed:
        ui.error(f"{len(failed)} problem(s) to fix before the pipeline will run")
        return 2
    ui.ok("ready")
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video_editor",
        description=(
            "A five-step video editor for events - marriage, engagement, party, "
            "baby shower and more. It stores references, not copies: no footage "
            "is ever duplicated, and only the finished film is written."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version", action="version", version=f"video_editor {__version__}"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--projects-dir", default=None,
        help="where project folders live (default: ./projects)",
    )
    common.add_argument(
        "--presets-dir", default=None,
        help="where the event presets live (default: ./config/presets)",
    )
    common.add_argument(
        "--json", action="store_true",
        help="print one JSON document instead of human output, and never ask",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_select_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("footage", help="one video file, or a folder of clips")
        sub.add_argument("--name", help="project name (default: from the file name)")
        sub.add_argument(
            "--preset", choices=preset_names(), metavar="EVENT",
            help="kind of event: " + ", ".join(preset_names()),
        )
        sub.add_argument(
            "--minutes", type=float,
            help="target length in minutes (default: the preset's own)",
        )
        sub.add_argument(
            "--threshold", type=float,
            help="scene-change sensitivity, 0.1 (many) to 0.6 (few)",
        )
        sub.add_argument(
            "--min-gap", type=float,
            help="seconds that must separate two chosen moments",
        )

    p = subparsers.add_parser(
        "select", parents=[common], help="STEP 1: choose which moments to keep"
    )
    add_select_options(p)
    p.add_argument(
        "--mode", choices=select.MODES,
        help="auto: detect the moments; manual: type in/out points",
    )
    p.set_defaults(func=cmd_select)

    p = subparsers.add_parser(
        "arrange", parents=[common], help="STEP 2: decide the running order"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument("--mode", choices=arrange.MODES, help="how to order the clips")
    p.add_argument("--first", help="clip id to open the film with (match mode)")
    p.add_argument("--rehash", action="store_true", help="re-read the edge frames")
    p.add_argument("--yes", action="store_true", help="keep the order without asking")
    p.set_defaults(func=cmd_arrange)

    p = subparsers.add_parser(
        "music", parents=[common], help="STEP 3: find the beat and cut to it"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument("--song", help="the song file (or a folder to pick from)")
    p.add_argument(
        "--snap", choices=sorted(GROUPS),
        help="snap cuts to a beat, half-bar, bar or two-bar",
    )
    p.add_argument(
        "--fit", choices=("song", "target", "both"),
        help="trim whole beats off the longest clips until the cut fits",
    )
    p.add_argument("--beats-per-bar", type=int, default=4, help="time signature")
    p.set_defaults(func=cmd_music)

    p = subparsers.add_parser(
        "emotions", parents=[common], help="STEP 4: read the mood of each clip"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument(
        "--backend", choices=sorted(BACKENDS), default="heuristic",
        help="heuristic (free, approximate) or face (needs `pip install fer`)",
    )
    p.add_argument("--force", action="store_true", help="re-score clips already done")
    p.add_argument("--no-review", action="store_true", help="skip the correction pass")
    p.add_argument(
        "--no-prior", action="store_true",
        help="do not let a clip's segment nudge its mood",
    )
    p.set_defaults(func=cmd_emotions)

    p = subparsers.add_parser(
        "render", parents=[common], help="STEP 5: merge into the final film"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument(
        "--audio", choices=render.AUDIO_MODES,
        help="music only, mix with the original, original only, or silent",
    )
    p.add_argument("--size", help="output size, e.g. 1920x1080")
    p.add_argument("--fps", type=float, help="output frame rate")
    p.add_argument("--crf", type=int, default=19, help="quality, 18 best - 28 small")
    p.add_argument(
        "--x264-preset", default="veryfast",
        help="libx264 speed/size tradeoff (ultrafast..veryslow)",
    )
    p.add_argument("--music-volume", type=float, default=None)
    p.add_argument("--original-volume", type=float, default=None)
    p.add_argument("--fade", type=float, default=1.5, help="fade in/out seconds")
    p.add_argument(
        "--no-align-music", action="store_true",
        help="do not shift the song to start on its first beat",
    )
    p.add_argument("--keep-temp", action="store_true", help="keep the working files")
    p.add_argument("--dry-run", action="store_true", help="plan it, do not encode")
    p.add_argument("--yes", action="store_true", help="render without asking")
    p.set_defaults(func=cmd_render)

    p = subparsers.add_parser(
        "run", parents=[common], help="all five steps, one after another"
    )
    add_select_options(p)
    p.add_argument("--mode", choices=select.MODES, help="selection mode (default auto)")
    p.add_argument(
        "--arrange-mode", choices=arrange.MODES, help="ordering mode (default story)"
    )
    p.add_argument("--song", help="the song file; without it the music step is skipped")
    p.add_argument("--snap", choices=sorted(GROUPS))
    p.add_argument("--fit", choices=("song", "target", "both"))
    p.add_argument("--backend", choices=sorted(BACKENDS), default="heuristic")
    p.add_argument("--audio", choices=render.AUDIO_MODES)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run)

    p = subparsers.add_parser(
        "status", parents=[common], help="show where a project stands"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.set_defaults(func=cmd_status)

    p = subparsers.add_parser(
        "plan", parents=[common], help="print the edit plan for a project"
    )
    p.add_argument("project", nargs="?", help="project folder or name")
    p.set_defaults(func=cmd_plan)

    p = subparsers.add_parser("list", parents=[common], help="list every project")
    p.set_defaults(func=cmd_list)

    p = subparsers.add_parser(
        "presets", parents=[common], help="list the kinds of event it can cut"
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", help="show each preset's segments"
    )
    p.set_defaults(func=cmd_presets)

    p = subparsers.add_parser(
        "doctor", parents=[common], help="check this machine is ready"
    )
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "json", False):
        ui.set_quiet(True)

    def fail(exc: Exception, code: int) -> int:
        if getattr(args, "json", False):
            emit({"error": str(exc), "error_type": type(exc).__name__})
        else:
            ui.error(str(exc))
        return code

    try:
        return int(args.func(args) or 0)
    except ui.Abort as exc:
        return fail(exc if str(exc) else RuntimeError("cancelled"), 130)
    except KeyboardInterrupt:
        return fail(RuntimeError("interrupted"), 130)
    except FFmpegMissing as exc:
        return fail(exc, 3)
    except (
        ProjectError,
        ProbeError,
        EmotionError,
        TimecodeError,
        PresetError,
        BeatError,
        DetectError,
    ) as exc:
        return fail(exc, 2)
    except RuntimeError as exc:  # render and step errors
        return fail(exc, 1)


if __name__ == "__main__":
    sys.exit(main())
