"""STEP 5 - render: merge everything into the finished film.

It cuts each clip from the ORIGINAL source (not from the already-encoded clip
in 02_selected), so the final file is encoded once and loses nothing. Every
clip is normalised to one size, frame rate and audio layout first, because
ffmpeg's fast concat demands that they match.

The song is laid under the whole thing and, by default, started on its first
beat - that is what makes the cuts land on the music instead of near it.

Output:
    <project>/06_final/<slug>_final.mp4
    <project>/06_final/render_plan.csv   what went in, in order
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from video_editor import ui
from video_editor.beats import BeatMap
from video_editor.probe import probe, require_tools
from video_editor.project import Clip, Project, slugify
from video_editor.timecode import format_duration, format_timecode

AUDIO_MODES = ("music", "mix", "original", "silent")


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise RenderError(f"{what} failed:\n{detail}")


def _target_format(project: Project, clips: list[Clip], size: str | None, fps: float | None):
    """Decide one resolution and frame rate for the whole film."""
    if size:
        try:
            width, height = (int(v) for v in size.lower().split("x"))
        except ValueError:
            raise RenderError(f"--size wants WIDTHxHEIGHT, got {size!r}") from None
    else:
        width = height = 0

    rates: list[float] = []
    sizes: dict[tuple[int, int], int] = {}
    seen: set[str] = set()
    for clip in clips:
        if clip.source in seen:
            continue  # one probe per source file, not per clip
        seen.add(clip.source)
        try:
            info = probe(Path(clip.source))
        except Exception:  # noqa: BLE001 - a missing source is reported later
            continue
        if info.fps > 0:
            rates.append(info.fps)
        if info.width and info.height:
            sizes[(info.width, info.height)] = sizes.get((info.width, info.height), 0) + 1

    if not width:
        if sizes:
            width, height = max(sizes, key=lambda k: sizes[k])
        else:
            width, height = 1920, 1080
    # Even dimensions, or H.264 refuses.
    width += width % 2
    height += height % 2

    rate = fps or (max(set(rates), key=rates.count) if rates else 30.0)
    return width, height, round(rate, 3)


def _normalise(
    clip: Clip,
    destination: Path,
    *,
    width: int,
    height: int,
    fps: float,
    crf: int,
    preset: str,
) -> None:
    """Cut one clip from its original source and force it into the house format."""
    source = Path(clip.source)
    if not source.is_file():
        raise RenderError(f"{clip.id}: original source is gone ({source})")

    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps},format=yuv420p"
    )

    has_audio = False
    try:
        has_audio = probe(source).has_audio
    except Exception:  # noqa: BLE001 - a bad source is reported by ffmpeg below
        has_audio = False

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{clip.source_in:.3f}",
        "-i", str(source),
    ]
    # Only add the silent track when the clip really has no audio of its own.
    # Declaring an unused, infinite lavfi input is the kind of thing ffmpeg
    # tolerates in one release and rejects in the next, so do not declare one
    # we are not going to map.
    if not has_audio:
        cmd += [
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    cmd += [
        "-t", f"{clip.render_duration:.3f}",
        "-filter_complex", f"[0:v]{video_filter}[v]",
        "-map", "[v]",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
    ]
    if not has_audio:
        # Bound the infinite silence. With real audio, -t already bounds the
        # output and -shortest would only risk truncating it.
        cmd.append("-shortest")
    cmd += ["-video_track_timescale", "90000", str(destination)]
    _run(cmd, f"normalising {clip.id}")


def _concat(parts: list[Path], destination: Path, work: Path) -> None:
    """Join the normalised parts with the concat demuxer."""
    listing = work / "concat.txt"
    # A relative path inside a concat list is resolved against the directory
    # the LIST lives in - not the working directory. Writing the project-
    # relative path therefore produced <work>/<work>/0001_c001.mp4 and failed
    # on ffmpeg 8, which enforces that; ffmpeg 7 happened to resolve against
    # the working directory instead. The parts sit beside the list, so a bare
    # file name is correct everywhere and needs no quoting of long paths.
    entries: list[str] = []
    for part in parts:
        name = part.name if part.parent == work else part.resolve().as_posix()
        entries.append(f"file '{name}'")
    listing.write_text("\n".join(entries) + "\n", encoding="utf-8")
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(destination),
        ],
        "joining the clips",
    )


def _lay_music(
    silent_cut: Path,
    song: Path,
    destination: Path,
    *,
    mode: str,
    music_volume: float,
    original_volume: float,
    music_offset: float,
    duration: float,
    fade: float,
) -> None:
    """Put the song under the cut."""
    fade_out_at = max(duration - fade, 0.0)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(silent_cut),
    ]
    if mode in ("music", "mix"):
        # -stream_loop -1 keeps the bed going if the song is shorter than the cut.
        cmd += ["-stream_loop", "-1", "-ss", f"{music_offset:.4f}", "-i", str(song)]

    music_chain = (
        f"[1:a]volume={music_volume},"
        f"afade=t=in:st=0:d={min(fade, 1.5):.2f},"
        f"afade=t=out:st={fade_out_at:.3f}:d={fade:.2f}[m]"
    )
    if mode == "music":
        filters = music_chain + ";[m]anull[aout]"
    elif mode == "mix":
        filters = (
            music_chain
            + f";[0:a]volume={original_volume}[o]"
            + ";[o][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
    elif mode == "original":
        filters = "[0:a]anull[aout]"
    else:  # silent
        filters = ""

    video_fade = (
        f"[0:v]fade=t=in:st=0:d={min(fade, 1.0):.2f},"
        f"fade=t=out:st={fade_out_at:.3f}:d={fade:.2f}[vout]"
    )
    if filters:
        cmd += ["-filter_complex", f"{video_fade};{filters}", "-map", "[vout]", "-map", "[aout]"]
    else:
        cmd += ["-filter_complex", video_fade, "-map", "[vout]", "-an"]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(destination),
    ]
    _run(cmd, "laying the music under the cut")


def _plan(project: Project, clips: list[Clip], width: int, height: int, fps: float) -> Path:
    lines = ["position,clip_id,starts_at,length,source,source_in,segment,emotion,label"]
    timeline = 0.0
    for position, clip in enumerate(clips, 1):
        lines.append(
            ",".join([
                str(position),
                clip.id,
                format_timecode(timeline),
                f"{clip.render_duration:.3f}",
                clip.source_name,
                f"{clip.source_in:.3f}",
                clip.segment or "",
                clip.emotion or "",
                (clip.label or "").replace(",", " "),
            ])
        )
        timeline += clip.render_duration
    destination = project.dir("output") / "render_plan.csv"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def run(
    project_path: str | Path,
    *,
    audio: str | None = None,
    size: str | None = None,
    fps: float | None = None,
    crf: int = 19,
    preset: str = "veryfast",
    music_volume: float | None = None,
    original_volume: float | None = None,
    fade: float = 1.5,
    align_music: bool = True,
    keep_temp: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
    presets_dir: str | None = None,
) -> Path | None:
    """Run step 5. Returns the path of the finished file."""
    require_tools()
    project = Project.load(project_path, presets_dir)
    clips = [c for c in project.ordered_clips() if c.render_duration > 0.04]
    if not clips:
        raise RenderError("nothing to render. Run the select step first.")
    # Unset options fall back to the preset's own mix for this kind of event.
    audio = audio or project.setting("audio", "mode", "mix")
    if music_volume is None:
        music_volume = float(project.setting("audio", "music_volume", 0.9))
    if original_volume is None:
        original_volume = float(project.setting("audio", "original_volume", 0.25))
    if audio not in AUDIO_MODES:
        raise RenderError(f"--audio wants one of: {', '.join(AUDIO_MODES)}")

    ui.banner("STEP 5 of 5 - RENDER", "Merge it all into the finished film.")
    ui.note(f"project: {project.name}")
    if not project.is_done("arrange"):
        ui.warn("the clips were never arranged - rendering in selection order")

    width, height, rate = _target_format(project, clips, size, fps)
    total = sum(c.render_duration for c in clips)

    music_info = project.data.get("music") or {}
    song: Path | None = None
    music_offset = 0.0
    if music_info.get("file"):
        candidate = project.root / music_info["file"]
        if candidate.is_file():
            song = candidate
            if align_music:
                music_offset = float(music_info.get("offset") or 0.0)
        else:
            ui.warn(f"the song is missing from {candidate}")

    if audio in ("music", "mix") and song is None:
        ui.warn("no song in this project - rendering with the original audio")
        audio = "original"

    ui.heading("Render plan")
    ui.table(
        ["setting", "value"],
        [
            ["clips", len(clips)],
            ["runtime", format_duration(total)],
            ["size", f"{width}x{height}"],
            ["frame rate", f"{rate:g} fps"],
            ["audio", audio],
            ["song", song.name if song else "-"],
            ["music starts at", f"{music_offset:.3f}s (first beat)" if music_offset else "0s"],
            ["quality", f"crf {crf}, preset {preset}"],
            ["fades", f"{fade:g}s in and out"],
        ],
    )
    plan = _plan(project, clips, width, height, rate)
    ui.ok(f"plan written to {plan.relative_to(project.root)}")

    if dry_run:
        ui.note("--dry-run: stopping before encoding")
        return None
    if (
        ui.interactive()
        and not assume_yes
        and not ui.confirm(f"Render {format_duration(total)} now?", True)
    ):
        ui.warn("render cancelled")
        return None

    final_dir = project.dir("output")
    work = Path(
        tempfile.mkdtemp(prefix="ve_render_", dir=str(final_dir))
    )
    try:
        ui.heading(f"Encoding {len(clips)} clip(s)")
        parts: list[Path] = []
        for i, clip in enumerate(clips, 1):
            part = work / f"{i:04d}_{clip.id}.mp4"
            ui.progress(
                i, len(clips),
                f"{clip.id} {format_duration(clip.render_duration)} "
                f"{clip.label or clip.source_name}",
            )
            _normalise(
                clip, part,
                width=width, height=height, fps=rate, crf=crf, preset=preset,
            )
            parts.append(part)

        ui.heading("Joining")
        joined = work / "joined.mp4"
        _concat(parts, joined, work)
        ui.ok(f"joined {len(parts)} clip(s)")

        destination = final_dir / f"{slugify(project.name)}_final.mp4"
        if audio == "original" and fade <= 0:
            shutil.move(str(joined), str(destination))
        else:
            ui.heading("Music and fades")
            _lay_music(
                joined,
                song or joined,
                destination,
                mode=audio,
                music_volume=music_volume,
                original_volume=original_volume,
                music_offset=music_offset,
                duration=total,
                fade=fade,
            )
    finally:
        if keep_temp:
            ui.note(f"working files kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    info = probe(destination)
    project.data["output"] = {
        "file": str(destination.relative_to(project.root)).replace("\\", "/"),
        "duration": round(info.duration, 3),
        "size": info.resolution,
        "fps": info.fps,
        "audio_mode": audio,
    }
    project.mark_done("render")
    project.save()

    ui.banner("DONE - YOUR FILM IS READY")
    ui.ok(str(destination))
    ui.note(
        f"{format_duration(info.duration)}, {info.resolution}, {info.fps:g} fps, "
        f"{destination.stat().st_size / 1_000_000:.1f} MB"
    )
    target = project.target_duration
    if target:
        delta = info.duration - target
        ui.note(
            f"you asked for {format_duration(target)} and got "
            f"{format_duration(info.duration)} ({delta:+.0f}s)"
        )
    return destination
