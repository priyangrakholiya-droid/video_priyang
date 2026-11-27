"""Automatic moment finding: point it at footage, get proposed clips back.

This is what makes the tool usable without a human typing timecodes, and it is
what an agent drives. The idea is the same one highlight detectors use on game
streams: the interesting moments are where the picture *changes* and where the
sound *peaks*.

  1. ffmpeg's `select` filter reports every frame whose scene score crosses a
     threshold - a cut, a camera move, somebody walking into frame. Those are
     the boundaries of the shots in the footage.
  2. The audio is reduced to a coarse loudness curve (one value per ~0.19s).
     Cheering, music, a dhol, laughter and speech all read as energy.
  3. Each shot boundary becomes a candidate clip, running until the next
     boundary, clamped to the preset's min/max clip length.
  4. Each candidate is scored on how loud it is and how strong its scene
     change was, then candidates are spread out (`min_gap_seconds`) so the
     film does not take six clips from the same thirty seconds.
  5. The best candidates are taken until the target length is filled.

Nothing is cut. The output is a list of references, which the select step
turns into clips in the manifest. That means a bad proposal costs nothing -
drop it and re-run with another threshold.
"""

from __future__ import annotations

import re
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

from video_editor.beats import BeatError, loudness_envelope
from video_editor.presets import Preset
from video_editor.probe import MediaInfo, ProbeError, probe, require_tools

# ~0.19 s per value at 22050 Hz: fine enough to find a cheer, coarse enough to
# scan a two-hour recording without filling memory.
ENERGY_FRAME_SAMPLES = 4096

_PTS_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_SCENE_RE = re.compile(r"lavfi\.scene_score=(\d+(?:\.\d+)?)")

# Loudness mapped to 0..1 across this dB window.
QUIET_DB = -55.0
LOUD_DB = -12.0


class DetectError(RuntimeError):
    pass


@dataclass
class Moment:
    """A proposed clip: where it is, how long, and why it was proposed."""

    source: str
    source_name: str
    start: float
    end: float
    score: float = 0.0
    scene_score: float = 0.0
    energy: float = 0.0
    segment: str = ""

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def reason(self) -> str:
        return (
            f"scene {self.scene_score:.2f}, loudness {self.energy:.2f} "
            f"-> score {self.score:.2f}"
        )


# --------------------------------------------------------------------- signals
def scene_changes(
    path: str | Path,
    threshold: float = 0.3,
    *,
    analysis_width: int = 320,
) -> list[tuple[float, float]]:
    """Every (time, scene score) where the picture changes sharply.

    Scaling down first is what keeps this fast - the scene score barely moves
    between 320 and 1920 pixels wide, but the decode cost does.
    """
    require_tools()
    chain = (
        f"scale={analysis_width}:-2,"
        f"select='gt(scene,{threshold:.4f})',"
        "metadata=print:file=-"
    )
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error",
            "-i", str(path), "-vf", chain, "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise DetectError(
            f"ffmpeg could not scan {Path(path).name}: "
            f"{(proc.stderr or '').strip()[-300:]}"
        )

    found: list[tuple[float, float]] = []
    pending: float | None = None
    for line in proc.stdout.splitlines():
        m = _PTS_RE.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = _SCENE_RE.search(line)
        if m and pending is not None:
            found.append((pending, float(m.group(1))))
            pending = None
    return found


def energy_curve(path: str | Path) -> tuple[list[float], list[float]]:
    """A coarse loudness curve, or empty lists when there is no audio."""
    try:
        return loudness_envelope(path, frame_samples=ENERGY_FRAME_SAMPLES)
    except (BeatError, ProbeError, OSError):
        return [], []


def _normalise_db(db: float) -> float:
    if db <= QUIET_DB:
        return 0.0
    if db >= LOUD_DB:
        return 1.0
    return (db - QUIET_DB) / (LOUD_DB - QUIET_DB)


def _mean_energy(
    times: list[float],
    levels: list[float],
    start: float,
    end: float,
) -> float:
    """Average normalised loudness over a time window."""
    if not times:
        return 0.0
    window = [
        _normalise_db(level)
        for moment, level in zip(times, levels)
        if start <= moment < end
    ]
    if not window:
        # Window shorter than one frame: take the nearest value.
        nearest = min(range(len(times)), key=lambda i: abs(times[i] - start))
        return _normalise_db(levels[nearest])
    return statistics.fmean(window)


# ------------------------------------------------------------------- proposing
def find_moments(
    path: str | Path,
    *,
    min_clip: float = 2.0,
    max_clip: float = 12.0,
    threshold: float = 0.3,
    prefer_loud: bool = True,
    info: MediaInfo | None = None,
    segment: str = "",
) -> list[Moment]:
    """Propose clips inside one file, unranked and unfiltered."""
    media = info or probe(path)
    source = str(Path(path).resolve())
    name = Path(path).name

    cuts = scene_changes(path, threshold)
    times, levels = energy_curve(path)

    # Shot boundaries: the start of the file, plus every scene change.
    boundaries: list[tuple[float, float]] = [(0.0, 0.0)] + cuts
    moments: list[Moment] = []
    for index, (start, scene_score) in enumerate(boundaries):
        next_start = (
            boundaries[index + 1][0] if index + 1 < len(boundaries) else media.duration
        )
        available = next_start - start
        if available < min_clip:
            continue  # too short a shot to use on its own
        end = min(start + max_clip, next_start, media.duration)
        if end - start < min_clip:
            continue

        energy = _mean_energy(times, levels, start, end)
        scene = min(scene_score, 1.0)
        if prefer_loud:
            score = 0.6 * energy + 0.4 * scene
        else:
            score = 0.35 * energy + 0.65 * scene
        moments.append(
            Moment(
                source=source,
                source_name=name,
                start=round(start, 3),
                end=round(end, 3),
                score=round(score, 4),
                scene_score=round(scene, 4),
                energy=round(energy, 4),
                segment=segment,
            )
        )
    return moments


def spread_out(moments: list[Moment], min_gap: float) -> list[Moment]:
    """Keep the best moments, never two closer together than `min_gap`.

    Greedy by score: take the strongest, veto anything too near it, repeat.
    This is what stops six clips coming from the same half minute.
    """
    kept: list[Moment] = []
    for moment in sorted(moments, key=lambda m: -m.score):
        clash = any(
            other.source == moment.source
            and abs(other.start - moment.start) < min_gap
            for other in kept
        )
        if not clash:
            kept.append(moment)
    return kept


def fill_target(moments: list[Moment], target: float) -> list[Moment]:
    """Take the best moments until the target runtime is filled."""
    chosen: list[Moment] = []
    total = 0.0
    for moment in sorted(moments, key=lambda m: -m.score):
        if total >= target:
            break
        chosen.append(moment)
        total += moment.duration
    # Hand them back in footage order: that is the sane default running order.
    return sorted(chosen, key=lambda m: (m.source_name, m.start))


def propose(
    sources: list[Path],
    *,
    target_duration: float,
    preset: Preset,
    threshold: float | None = None,
    min_gap: float | None = None,
    min_clip: float | None = None,
    max_clip: float | None = None,
    per_segment: bool = True,
    on_progress=None,
) -> tuple[list[Moment], dict[str, int]]:
    """Scan every source and propose a set of clips that fills the target.

    Returns (chosen moments, a count of how many candidates each file gave).
    """
    settings = preset.autodetect
    pacing = preset.pacing
    threshold = settings["scene_threshold"] if threshold is None else threshold
    min_gap = settings["min_gap_seconds"] if min_gap is None else min_gap
    prefer_loud = bool(settings.get("prefer_loud", True))
    min_clip = pacing["min_clip_seconds"] if min_clip is None else min_clip
    max_clip = pacing["max_clip_seconds"] if max_clip is None else max_clip

    if min_clip <= 0 or max_clip <= min_clip:
        raise DetectError(
            f"clip length range is nonsense: min {min_clip}, max {max_clip}"
        )

    everything: list[Moment] = []
    tally: dict[str, int] = {}
    for index, source in enumerate(sources, 1):
        if on_progress:
            on_progress(index, len(sources), Path(source).name)
        try:
            info = probe(source)
        except ProbeError as exc:
            tally[Path(source).name] = 0
            if on_progress:
                on_progress(index, len(sources), f"{Path(source).name}: {exc}")
            continue
        # A file named "haldi_01.mp4" belongs to the haldi segment; use that.
        segment = preset.guess_segment(Path(source).name) if per_segment else ""
        moments = find_moments(
            source,
            min_clip=min_clip,
            max_clip=max_clip,
            threshold=threshold,
            prefer_loud=prefer_loud,
            info=info,
            segment=segment,
        )
        tally[Path(source).name] = len(moments)
        everything.extend(moments)

    if not everything:
        raise DetectError(
            "no moments found. The footage may be one static shot - lower "
            "--threshold (try 0.15), or select clips by hand instead."
        )

    spread = spread_out(everything, min_gap)
    return fill_target(spread, target_duration), tally
