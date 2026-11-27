"""Beat detection for the song chosen in step 3.

No audio libraries needed. The work is split so that the heavy lifting happens
inside ffmpeg and only a small envelope comes back into Python:

  1. ffmpeg resamples the song to mono 22050 Hz, chops it into 512-sample
     frames and prints the RMS level of each frame  -> a loudness envelope.
  2. We difference that envelope to get an onset strength signal: loudness
     rising fast means something was struck (a drum, a chord, a beat).
  3. Autocorrelating the onset signal gives the beat period (the tempo), and
     a comb search over one period gives the phase (where beat one sits).
  4. From period + phase we lay down a beat grid over the whole song, which
     step 3 then snaps every cut to.
"""

from __future__ import annotations

import math
import re
import subprocess
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

from video_editor.probe import ProbeError, require_tools

SAMPLE_RATE = 22050
FRAME_SAMPLES = 512
HOP = FRAME_SAMPLES / SAMPLE_RATE  # ~23.2 ms per envelope value

# Tempo search space. Wedding tracks sit comfortably inside this.
MIN_BPM = 60.0
MAX_BPM = 190.0
# Where we fold half/double tempo estimates back into.
PREFERRED_BPM = (70.0, 180.0)

_PTS_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?|-?inf|nan)")

SILENCE_DB = -120.0


class BeatError(RuntimeError):
    """The song could not be analysed."""


@dataclass
class BeatMap:
    """The beat grid of one song."""

    path: str
    duration: float
    bpm: float
    period: float            # seconds between beats
    offset: float            # time of the first beat
    beats: list[float] = field(default_factory=list)
    confidence: float = 0.0  # 0..1, how periodic the onsets actually were
    beats_per_bar: int = 4

    @property
    def bar_period(self) -> float:
        return self.period * self.beats_per_bar

    def nearest_beat(self, when: float) -> float:
        """The beat closest to `when`."""
        if not self.beats:
            return when
        i = bisect_left(self.beats, when)
        if i == 0:
            return self.beats[0]
        if i >= len(self.beats):
            return self.beats[-1]
        before, after = self.beats[i - 1], self.beats[i]
        return before if (when - before) <= (after - when) else after

    def snap_duration(self, seconds: float, *, group: int = 1) -> float:
        """Round a clip length to a whole number of beats (or bars).

        `group=1` snaps to beats, `group=4` snaps to a four-beat bar. The result
        is never zero: a clip always keeps at least one beat.
        """
        unit = self.period * max(group, 1)
        if unit <= 0:
            return seconds
        units = max(1, round(seconds / unit))
        return units * unit

    def beats_in(self, seconds: float, *, group: int = 1) -> int:
        unit = self.period * max(group, 1)
        return max(1, round(seconds / unit)) if unit > 0 else 1

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "duration": round(self.duration, 3),
            "bpm": round(self.bpm, 2),
            "period": round(self.period, 5),
            "offset": round(self.offset, 4),
            "confidence": round(self.confidence, 3),
            "beats_per_bar": self.beats_per_bar,
            "beat_count": len(self.beats),
            "beats": [round(b, 4) for b in self.beats],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BeatMap":
        return cls(
            path=data.get("path", ""),
            duration=float(data.get("duration") or 0.0),
            bpm=float(data.get("bpm") or 0.0),
            period=float(data.get("period") or 0.0),
            offset=float(data.get("offset") or 0.0),
            beats=[float(b) for b in (data.get("beats") or [])],
            confidence=float(data.get("confidence") or 0.0),
            beats_per_bar=int(data.get("beats_per_bar") or 4),
        )


# --------------------------------------------------------------------- stage 1
def loudness_envelope(
    path: str | Path,
    *,
    frame_samples: int = FRAME_SAMPLES,
    start: float = 0.0,
    duration: float | None = None,
) -> tuple[list[float], list[float]]:
    """Return (times, dB levels) of the audio, one value per frame.

    `frame_samples` trades resolution for speed: the 512 default gives a 23 ms
    hop, which beat detection needs. Scanning a two-hour recording for loud
    moments does not, so the detector passes something much larger.
    """
    require_tools()
    path = Path(path)
    if not path.is_file():
        raise BeatError(f"song not found: {path}")

    chain = (
        f"aresample={SAMPLE_RATE},"
        "aformat=channel_layouts=mono,"
        f"asetnsamples=n={int(frame_samples)}:p=0,"
        "astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    cmd = ["ffmpeg", "-hide_banner", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if duration is not None:
        cmd += ["-t", f"{max(duration, 0.05):.3f}"]
    cmd += ["-map", "0:a:0", "-af", chain, "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[-400:]
        raise BeatError(f"ffmpeg could not read audio from {path.name}: {err}")

    times: list[float] = []
    levels: list[float] = []
    pending: float | None = None
    for line in proc.stdout.splitlines():
        m = _PTS_RE.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = _RMS_RE.search(line)
        if m and pending is not None:
            raw = m.group(1)
            try:
                db = float(raw)
                if not math.isfinite(db):
                    db = SILENCE_DB
            except ValueError:
                db = SILENCE_DB
            times.append(pending)
            levels.append(max(db, SILENCE_DB))
            pending = None

    if len(levels) < 20:
        raise BeatError(
            f"{path.name} gave too little audio to analyse "
            f"({len(levels)} frames). Is there really an audio track?"
        )
    return times, levels


# --------------------------------------------------------------------- stage 2
def onset_strength(levels: list[float]) -> list[float]:
    """Half-wave rectified, smoothed first difference of the loudness curve."""
    raw = [0.0]
    for i in range(1, len(levels)):
        raw.append(max(levels[i] - levels[i - 1], 0.0))

    # 3-frame moving average: kills single-frame jitter, keeps real attacks.
    smooth: list[float] = []
    for i in range(len(raw)):
        lo = max(0, i - 1)
        hi = min(len(raw), i + 2)
        smooth.append(sum(raw[lo:hi]) / (hi - lo))

    mean = sum(smooth) / len(smooth)
    # Subtract the mean so quiet passages do not drag the correlation around.
    return [max(v - mean, 0.0) for v in smooth]


# --------------------------------------------------------------------- stage 3
def _autocorrelate(signal: list[float], lag: int) -> float:
    n = len(signal) - lag
    if n <= 0:
        return 0.0
    total = 0.0
    for i in range(n):
        total += signal[i] * signal[i + lag]
    return total / n


def estimate_period(onsets: list[float]) -> tuple[float, float]:
    """Return (beat period in seconds, confidence 0..1)."""
    min_lag = max(2, int(round(60.0 / MAX_BPM / HOP)))
    max_lag = min(len(onsets) - 2, int(round(60.0 / MIN_BPM / HOP)))
    if max_lag <= min_lag:
        raise BeatError("the song is too short to find a tempo")

    scores = {lag: _autocorrelate(onsets, lag) for lag in range(min_lag, max_lag + 1)}
    best_lag = max(scores, key=lambda k: scores[k])
    best = scores[best_lag]
    if best <= 0:
        raise BeatError("no rhythmic pulse found in this song")

    # Parabolic interpolation around the peak for sub-frame precision.
    left = scores.get(best_lag - 1, 0.0)
    right = scores.get(best_lag + 1, 0.0)
    denom = left - 2 * best + right
    shift = 0.5 * (left - right) / denom if denom else 0.0
    shift = max(-0.5, min(0.5, shift))
    period = (best_lag + shift) * HOP

    # Fold octave errors (half / double tempo) into the musical range.
    while period > 0 and 60.0 / period < PREFERRED_BPM[0]:
        period /= 2.0
    while period > 0 and 60.0 / period > PREFERRED_BPM[1]:
        period *= 2.0

    mean_score = sum(scores.values()) / len(scores)
    confidence = 0.0 if best <= 0 else max(0.0, min(1.0, 1.0 - (mean_score / best)))
    return period, confidence


def estimate_offset(onsets: list[float], period: float) -> float:
    """Find where beat one sits, by sliding a comb over a single period."""
    lag = period / HOP
    if lag < 2:
        return 0.0
    best_offset, best_score = 0.0, -1.0
    steps = max(8, int(round(lag)))
    for s in range(steps):
        offset_frames = s * lag / steps
        score = 0.0
        k = 0
        while True:
            pos = offset_frames + k * lag
            idx = int(round(pos))
            if idx >= len(onsets):
                break
            score += onsets[idx]
            k += 1
        if score > best_score:
            best_score, best_offset = score, offset_frames * HOP
    return best_offset


# --------------------------------------------------------------------- stage 4
def analyse(path: str | Path, *, beats_per_bar: int = 4) -> BeatMap:
    """Full pipeline: song file in, beat grid out."""
    path = Path(path)
    times, levels = loudness_envelope(path)
    onsets = onset_strength(levels)
    period, confidence = estimate_period(onsets)
    offset = estimate_offset(onsets, period)

    duration = times[-1] + HOP if times else 0.0
    beats: list[float] = []
    t = offset
    # Guard against a pathological period producing a runaway loop.
    while t < duration and len(beats) < 100_000:
        beats.append(t)
        t += period

    return BeatMap(
        path=str(path.resolve()),
        duration=duration,
        bpm=60.0 / period if period else 0.0,
        period=period,
        offset=offset,
        beats=beats,
        confidence=confidence,
        beats_per_bar=max(1, beats_per_bar),
    )


def describe(beatmap: BeatMap) -> str:
    """One-line human summary of a beat map."""
    quality = (
        "strong" if beatmap.confidence >= 0.6
        else "usable" if beatmap.confidence >= 0.35
        else "weak"
    )
    return (
        f"{beatmap.bpm:.1f} BPM  "
        f"(beat every {beatmap.period:.3f}s, first beat at {beatmap.offset:.3f}s, "
        f"{len(beatmap.beats)} beats, {quality} pulse)"
    )


def probe_audio_duration(path: str | Path) -> float:
    """Duration of an audio file, via ffprobe."""
    require_tools()
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ProbeError(f"could not read {Path(path).name}")
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0
