"""Command line entry point.

    python -m video_editor select  <footage>        step 1
    python -m video_editor arrange <project>        step 2
    python -m video_editor music   <project>        step 3
    python -m video_editor emotions <project>       step 4
    python -m video_editor render  <project>        step 5

    python -m video_editor run     <footage>        all five, back to back
    python -m video_editor status  <project>        where am I?
    python -m video_editor list                     every project
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_editor import __version__, ui
from video_editor.emotion import BACKENDS, EmotionError
from video_editor.probe import FFmpegMissing, ProbeError
from video_editor.project import MANIFEST_NAME, PRESETS, Project, ProjectError
from video_editor.steps import arrange, emotions, music, render, select
from video_editor.steps.music import GROUPS
from video_editor.timecode import TimecodeError, format_duration

DEFAULT_PROJECTS_DIR = Path("projects")

STEP_ORDER = ("select", "arrange", "music", "emotions", "render")


def _projects_dir(args: argparse.Namespace) -> Path:
    path = Path(getattr(args, "projects_dir", None) or DEFAULT_PROJECTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_project(given: str | None, args: argparse.Namespace) -> Path:
    """Accept a project path, a project name, or nothing (the only one there is)."""
    if given:
        candidate = Path(given).expanduser()
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
        inside = _projects_dir(args) / given
        if (inside / MANIFEST_NAME).is_file():
            return inside
        raise ProjectError(f"no project at {given}")

    found = sorted(
        p.parent for p in _projects_dir(args).glob(f"*/{MANIFEST_NAME}")
    )
    if not found:
        raise ProjectError(
            "no projects yet. Start with: python -m video_editor select <footage>"
        )
    if len(found) == 1:
        return found[0]
    names = [p.name for p in found]
    picked = ui.choose("Which project?", names)
    return found[names.index(picked)]


# ------------------------------------------------------------------- commands
def cmd_select(args: argparse.Namespace) -> int:
    select.run(
        args.footage,
        projects_dir=_projects_dir(args),
        name=args.name,
        preset=args.preset,
        minutes=args.minutes,
        reencode=not args.stream_copy,
    )
    return 0


def cmd_arrange(args: argparse.Namespace) -> int:
    arrange.run(
        _resolve_project(args.project, args),
        mode=args.mode,
        first=args.first,
        rehash=args.rehash,
    )
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    music.run(
        _resolve_project(args.project, args),
        song=args.song,
        group=args.snap,
        fit=args.fit,
        beats_per_bar=args.beats_per_bar,
    )
    return 0


def cmd_emotions(args: argparse.Namespace) -> int:
    emotions.run(
        _resolve_project(args.project, args),
        backend=args.backend,
        force=args.force,
        skip_review=args.no_review,
    )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    render.run(
        _resolve_project(args.project, args),
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
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """All five steps, one after another."""
    ui.banner(
        "VIDEO EDITOR - FULL PIPELINE",
        "select -> arrange -> music -> emotions -> render",
    )
    project = select.run(
        args.footage,
        projects_dir=_projects_dir(args),
        name=args.name,
        preset=args.preset,
        minutes=args.minutes,
        reencode=not args.stream_copy,
    )
    if not project.clips:
        ui.warn("no clips were chosen, stopping here")
        return 1
    arrange.run(project.root, mode=args.mode)
    if args.song or ui.interactive():
        music.run(project.root, song=args.song, group=args.snap, fit=args.fit)
    emotions.run(project.root, backend=args.backend, skip_review=args.no_review)
    render.run(project.root, audio=args.audio, dry_run=args.dry_run)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    project = Project.load(_resolve_project(args.project, args))
    ui.banner(project.name, str(project.root))
    rows = []
    for step in STEP_ORDER:
        done = project.is_done(step)
        rows.append([step, "done" if done else "-"])
    ui.table(["step", "state"], rows)

    clips = project.clips
    music_info = project.data.get("music") or {}
    ui.heading("Numbers")
    ui.table(
        ["what", "value"],
        [
            ["preset", project.preset],
            ["target length", format_duration(project.target_duration)],
            ["clips", len(clips)],
            ["selected", format_duration(project.selected_duration)],
            ["after beat snap", format_duration(project.render_duration)],
            ["song", Path(music_info.get("file", "")).name or "-"],
            ["tempo", f"{music_info.get('bpm', 0):.1f} BPM" if music_info else "-"],
            ["final file", (project.data.get("final") or {}).get("file", "-")],
        ],
    )
    if clips:
        ui.heading("Clips")
        ui.table(
            ["#", "id", "length", "segment", "emotion", "what it is"],
            [
                [
                    c.order if c.order is not None else "-",
                    c.id,
                    format_duration(c.render_duration),
                    c.segment or "-",
                    c.emotion or "-",
                    c.label or c.source_name,
                ]
                for c in project.ordered_clips()
            ],
        )
    nxt = next((s for s in STEP_ORDER if not project.is_done(s)), None)
    if nxt:
        ui.note(f"next:  python -m video_editor {nxt} \"{project.root}\"")
    else:
        ui.ok("every step is done")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    base = _projects_dir(args)
    found = sorted(base.glob(f"*/{MANIFEST_NAME}"))
    ui.banner("Projects", str(base.resolve()))
    if not found:
        ui.note("none yet. Start with: python -m video_editor select <footage>")
        return 0
    rows = []
    for manifest in found:
        try:
            project = Project.load(manifest.parent)
        except ProjectError:
            continue
        steps_done = sum(1 for s in STEP_ORDER if project.is_done(s))
        rows.append([
            manifest.parent.name,
            project.preset,
            len(project.clips),
            format_duration(project.render_duration),
            f"{steps_done}/5",
            project.data.get("updated", "")[:16],
        ])
    ui.table(["folder", "preset", "clips", "runtime", "steps", "updated"], rows)
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video_editor",
        description=(
            "A five-step video editor for engagement and marriage films: "
            "select clips, arrange them, cut to the beat of a song, sort by "
            "emotion, render."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"video_editor {__version__}")
    parser.add_argument(
        "--projects-dir",
        default=None,
        help="where project folders live (default: ./projects)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- shared option groups ---------------------------------------------
    def add_select_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("footage", help="one video file, or a folder of clips")
        sub.add_argument("--name", help="project name (default: from the file name)")
        sub.add_argument(
            "--preset", choices=sorted(PRESETS), help="which kind of film this is"
        )
        sub.add_argument(
            "--minutes", type=float,
            help="target length in minutes (skips the question)",
        )
        sub.add_argument(
            "--stream-copy", action="store_true",
            help="cut without re-encoding: much faster, but cuts snap to keyframes",
        )

    p = subparsers.add_parser("select", help="STEP 1: choose the clips to keep")
    add_select_options(p)
    p.set_defaults(func=cmd_select)

    p = subparsers.add_parser("arrange", help="STEP 2: decide the running order")
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument("--mode", choices=arrange.MODES, help="how to order the clips")
    p.add_argument("--first", help="clip id to open the film with (match mode)")
    p.add_argument(
        "--rehash", action="store_true", help="re-read every clip's edge frames"
    )
    p.set_defaults(func=cmd_arrange)

    p = subparsers.add_parser("music", help="STEP 3: find the beat and cut to it")
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument("--song", help="the song file (or a folder to pick from)")
    p.add_argument(
        "--snap", choices=sorted(GROUPS), help="snap cuts to a beat, half-bar, bar..."
    )
    p.add_argument(
        "--fit", choices=("song", "target", "both"),
        help="trim whole beats off the longest clips until the cut fits",
    )
    p.add_argument(
        "--beats-per-bar", type=int, default=4, help="time signature (default 4)"
    )
    p.set_defaults(func=cmd_music)

    p = subparsers.add_parser("emotions", help="STEP 4: sort clips into emotion folders")
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument(
        "--backend", choices=sorted(BACKENDS), default="heuristic",
        help="heuristic (free, approximate) or face (needs `pip install fer`)",
    )
    p.add_argument("--force", action="store_true", help="re-read clips already scored")
    p.add_argument(
        "--no-review", action="store_true", help="do not offer the correction pass"
    )
    p.set_defaults(func=cmd_emotions)

    p = subparsers.add_parser("render", help="STEP 5: merge into the final film")
    p.add_argument("project", nargs="?", help="project folder or name")
    p.add_argument(
        "--audio", choices=render.AUDIO_MODES, default="music",
        help="music only, mix with the original, original only, or silent",
    )
    p.add_argument("--size", help="output size, e.g. 1920x1080")
    p.add_argument("--fps", type=float, help="output frame rate")
    p.add_argument("--crf", type=int, default=19, help="quality, 18 best - 28 small")
    p.add_argument(
        "--x264-preset", default="veryfast",
        help="libx264 speed/size tradeoff (ultrafast..veryslow)",
    )
    p.add_argument("--music-volume", type=float, default=0.9)
    p.add_argument("--original-volume", type=float, default=0.25)
    p.add_argument("--fade", type=float, default=1.5, help="fade in/out seconds")
    p.add_argument(
        "--no-align-music", action="store_true",
        help="do not shift the song to start on its first beat",
    )
    p.add_argument("--keep-temp", action="store_true", help="keep the working files")
    p.add_argument("--dry-run", action="store_true", help="plan it, do not encode")
    p.set_defaults(func=cmd_render)

    p = subparsers.add_parser("run", help="all five steps, one after another")
    add_select_options(p)
    p.add_argument("--mode", choices=arrange.MODES, help="arrange mode")
    p.add_argument("--song", help="the song file")
    p.add_argument("--snap", choices=sorted(GROUPS), help="beat snapping")
    p.add_argument("--fit", choices=("song", "target", "both"))
    p.add_argument("--backend", choices=sorted(BACKENDS), default="heuristic")
    p.add_argument("--no-review", action="store_true")
    p.add_argument("--audio", choices=render.AUDIO_MODES, default="music")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run)

    p = subparsers.add_parser("status", help="show where a project stands")
    p.add_argument("project", nargs="?", help="project folder or name")
    p.set_defaults(func=cmd_status)

    p = subparsers.add_parser("list", help="list every project")
    p.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ui.Abort as exc:
        ui.warn(str(exc) or "cancelled")
        return 130
    except KeyboardInterrupt:
        ui.warn("\ninterrupted")
        return 130
    except FFmpegMissing as exc:
        ui.error(str(exc))
        return 3
    except (ProjectError, ProbeError, EmotionError, TimecodeError) as exc:
        ui.error(str(exc))
        return 2
    except RuntimeError as exc:  # render and step errors
        ui.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
