"""Step 4's analyser: read the mood of a clip and sort it into a folder.

HONEST LIMITS, PLEASE READ
--------------------------
Reading a *face* and naming the feeling on it needs a trained model. This
module therefore has two backends behind one interface:

  * HeuristicBackend (default, always available) looks at what ffmpeg can
    measure for free - brightness, colour warmth, how much the picture moves,
    how loud and how dynamic the audio is - and maps that to a mood. It is a
    good sorter of *energy* (a dance floor vs a quiet vidaai) and a poor
    reader of *faces*. It will put a sad moment shot in bright sun in the
    wrong folder sometimes.

  * FaceBackend (optional) uses a real facial-expression model if one is
    installed: `pip install fer` or `pip install deepface`. It samples frames,
    finds faces, and averages their expression scores. Slower, far better.

Pick one with --backend on the emotion step. Both write the same thing into
the manifest, so the rest of the pipeline does not care which ran.
"""

from __future__ import annotations

import math
import re
import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from video_editor.presets import EMOTIONS
from video_editor.probe import require_tools

_META_RE = re.compile(r"lavfi\.signalstats\.(\w+)=(-?\d+(?:\.\d+)?)")

# How many frames per second we sample for analysis. Low is fine and fast.
ANALYSIS_FPS = 4


class EmotionError(RuntimeError):
    pass


@dataclass
class Features:
    """Cheap, measurable properties of a clip."""

    brightness: float = 0.0   # 0..1
    saturation: float = 0.0   # 0..1
    warmth: float = 0.0       # 0..1, how far the average hue leans red/orange
    motion: float = 0.0       # 0..1, frame-to-frame change
    audio_energy: float = 0.0 # 0..1
    audio_dynamics: float = 0.0  # 0..1, how much the loudness swings
    has_audio: bool = False
    faces: dict[str, float] = field(default_factory=dict)  # filled by FaceBackend

    def as_dict(self) -> dict[str, float]:
        return {
            "brightness": round(self.brightness, 3),
            "saturation": round(self.saturation, 3),
            "warmth": round(self.warmth, 3),
            "motion": round(self.motion, 3),
            "audio_energy": round(self.audio_energy, 3),
            "audio_dynamics": round(self.audio_dynamics, 3),
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _warmth_from_hue(hue_degrees: float) -> float:
    """1.0 at red/orange (0-40 deg), 0.0 at cyan/blue (180-220 deg)."""
    # Distance around the colour wheel from 20 degrees (a warm skin/candle hue).
    delta = abs(((hue_degrees - 20.0 + 180.0) % 360.0) - 180.0)
    return _clamp(1.0 - delta / 180.0)


def visual_features(
    path: str | Path,
    *,
    start: float = 0.0,
    duration: float | None = None,
) -> dict[str, float]:
    """Average brightness, saturation, hue and inter-frame difference.

    `start`/`duration` analyse one stretch of a longer file, which is how
    every clip is measured: the footage is never cut, only read in place.
    """
    require_tools()
    chain = (
        f"fps={ANALYSIS_FPS},scale=160:-2,signalstats,"
        "metadata=print:file=-"
    )
    cmd = ["ffmpeg", "-hide_banner", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if duration is not None:
        cmd += ["-t", f"{max(duration, 0.05):.3f}"]
    cmd += ["-vf", chain, "-an", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise EmotionError(
            f"ffmpeg could not analyse {Path(path).name}: "
            f"{(proc.stderr or '').strip()[-300:]}"
        )

    collected: dict[str, list[float]] = {}
    for line in proc.stdout.splitlines():
        m = _META_RE.search(line)
        if m:
            collected.setdefault(m.group(1), []).append(float(m.group(2)))

    def mean_of(key: str, default: float = 0.0) -> float:
        values = collected.get(key) or []
        return statistics.fmean(values) if values else default

    return {
        "yavg": mean_of("YAVG", 128.0),
        "satavg": mean_of("SATAVG"),
        "hueavg": mean_of("HUEAVG", 20.0),
        "ydif": mean_of("YDIF"),
        "frames": float(len(collected.get("YAVG") or [])),
    }


def audio_features(
    path: str | Path,
    *,
    start: float = 0.0,
    duration: float | None = None,
) -> tuple[float, float, bool]:
    """Return (energy 0..1, dynamics 0..1, has_audio) for a stretch of audio."""
    # Imported here so a video-only install never pays for it.
    from video_editor.beats import BeatError, loudness_envelope

    try:
        _, levels = loudness_envelope(path, start=start, duration=duration)
    except Exception:  # no audio stream, or too short to measure
        return 0.0, 0.0, False
    if not levels:
        return 0.0, 0.0, False

    voiced = [db for db in levels if db > -70.0]
    if not voiced:
        return 0.0, 0.0, True
    mean_db = statistics.fmean(voiced)
    spread = statistics.pstdev(voiced) if len(voiced) > 1 else 0.0
    # -60 dB (near silence) -> 0, -10 dB (loud) -> 1
    energy = _clamp((mean_db + 60.0) / 50.0)
    dynamics = _clamp(spread / 15.0)
    return energy, dynamics, True


def extract_features(
    path: str | Path,
    *,
    start: float = 0.0,
    duration: float | None = None,
) -> Features:
    """Everything the heuristic backend needs, in two ffmpeg passes."""
    vis = visual_features(path, start=start, duration=duration)
    energy, dynamics, has_audio = audio_features(path, start=start, duration=duration)
    return Features(
        brightness=_clamp(vis["yavg"] / 255.0),
        saturation=_clamp(vis["satavg"] / 110.0),
        warmth=_warmth_from_hue(vis["hueavg"]),
        motion=_clamp(vis["ydif"] / 18.0),
        audio_energy=energy,
        audio_dynamics=dynamics,
        has_audio=has_audio,
    )


class Backend:
    """Interface every emotion backend implements."""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def score(
        self,
        path: str | Path,
        *,
        start: float = 0.0,
        duration: float | None = None,
    ) -> tuple[dict[str, float], Features]:
        """Score one stretch of a source file.

        The footage is read in place - `start` and `duration` locate the clip
        inside the original file, so nothing has to be cut out first.
        """
        raise NotImplementedError


class HeuristicBackend(Backend):
    """Mood from measurable energy. Fast, free, approximate."""

    name = "heuristic"

    def available(self) -> bool:
        return True

    def score(
        self,
        path: str | Path,
        *,
        start: float = 0.0,
        duration: float | None = None,
    ) -> tuple[dict[str, float], Features]:
        f = extract_features(path, start=start, duration=duration)
        still = 1.0 - f.motion
        quiet = 1.0 - f.audio_energy
        steady = 1.0 - f.audio_dynamics

        scores = {
            # Dance floor, baraat, games: lots of movement and noise.
            "fun": 0.55 * f.motion + 0.30 * f.audio_energy + 0.15 * f.saturation,
            # Bright, colourful, lively but not frantic.
            "happy": 0.35 * f.brightness + 0.30 * f.saturation
                     + 0.20 * f.audio_energy + 0.15 * f.motion,
            # Vidaai, hugs, speeches breaking up: slow, dim, voice that swells.
            "emotional": 0.40 * still + 0.30 * f.audio_dynamics
                         + 0.30 * (1.0 - f.brightness),
            # Couple moments: warm light, slow camera, soft sound.
            "romantic": 0.40 * f.warmth + 0.35 * still + 0.25 * quiet,
            # Pheras, rituals: static frame, warm fire light, even sound.
            "ritual": 0.40 * still + 0.30 * f.warmth + 0.30 * steady,
            # Decor, details, b-roll: nothing happening, nothing loud.
            "calm": 0.45 * still + 0.35 * quiet + 0.20 * steady,
        }
        if not f.has_audio:
            # Without sound, the audio terms are guesses; lean on the picture.
            for key in ("fun", "happy"):
                scores[key] *= 0.8
        total = sum(scores.values()) or 1.0
        return {k: round(v / total, 4) for k, v in scores.items()}, f


class FaceBackend(Backend):
    """Real facial-expression reading, when a model is installed."""

    name = "face"

    # Model labels -> our folders.
    MAP = {
        "happy": "happy",
        "surprise": "fun",
        "neutral": "calm",
        "sad": "emotional",
        "fear": "emotional",
        "angry": "emotional",
        "disgust": "emotional",
    }

    def __init__(self) -> None:
        self._detector = None
        self._kind = ""

    def available(self) -> bool:
        return self._load() is not None

    def _load(self):
        if self._detector is not None:
            return self._detector
        try:  # the lighter of the two
            from fer import FER  # type: ignore

            self._detector = FER(mtcnn=False)
            self._kind = "fer"
            return self._detector
        except Exception:
            pass
        try:
            from deepface import DeepFace  # type: ignore

            self._detector = DeepFace
            self._kind = "deepface"
            return self._detector
        except Exception:
            return None

    def score(
        self,
        path: str | Path,
        *,
        start: float = 0.0,
        duration: float | None = None,
    ) -> tuple[dict[str, float], Features]:
        detector = self._load()
        if detector is None:
            raise EmotionError(
                "no face-emotion model installed. Run `pip install fer` "
                "(or `pip install deepface`), or use --backend heuristic."
            )
        frames = self._sample_frames(path, start=start, duration=duration)
        if not frames:
            raise EmotionError(f"could not read frames from {Path(path).name}")

        tally: dict[str, float] = {}
        faces_seen = 0
        for frame in frames:
            for label, value in self._read_frame(frame).items():
                tally[label] = tally.get(label, 0.0) + value
                faces_seen += 1

        features = extract_features(path, start=start, duration=duration)
        if not tally:
            # No faces found: fall back rather than return nothing useful.
            scores, feats = HeuristicBackend().score(
                path, start=start, duration=duration
            )
            feats.faces = {}
            return scores, feats

        scores = {e: 0.0 for e in EMOTIONS}
        for label, value in tally.items():
            bucket = self.MAP.get(label.lower())
            if bucket:
                scores[bucket] += value
        # Faces tell us nothing about romance; keep the visual cue for that one.
        scores["romantic"] += features.warmth * (1.0 - features.motion) * 0.5
        total = sum(scores.values()) or 1.0
        features.faces = {k: round(v / (faces_seen or 1), 4) for k, v in tally.items()}
        return {k: round(v / total, 4) for k, v in scores.items()}, features

    def _sample_frames(
        self,
        path: str | Path,
        *,
        start: float = 0.0,
        duration: float | None = None,
        count: int = 6,
    ) -> list[Path]:
        """Write `count` JPEGs spread across the clip into a temp folder.

        These are the only files this tool ever extracts from your footage,
        they are a few kilobytes each, and they are deleted straight after.
        """
        import tempfile

        from video_editor.probe import probe

        span = duration if duration is not None else probe(path).duration - start
        span = max(span, 0.1)
        out_dir = Path(tempfile.mkdtemp(prefix="ve_faces_"))
        step = span / (count + 1)
        frames: list[Path] = []
        for i in range(1, count + 1):
            dest = out_dir / f"f{i:02d}.jpg"
            proc = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-v", "error", "-y",
                    "-ss", f"{start + step * i:.3f}", "-i", str(path),
                    "-frames:v", "1", "-q:v", "3", str(dest),
                ],
                capture_output=True,
            )
            if proc.returncode == 0 and dest.is_file():
                frames.append(dest)
        return frames

    def _read_frame(self, frame: Path) -> dict[str, float]:
        detector = self._load()
        try:
            if self._kind == "fer":
                import cv2  # type: ignore

                image = cv2.imread(str(frame))
                if image is None:
                    return {}
                found = detector.detect_emotions(image) or []
                merged: dict[str, float] = {}
                for face in found:
                    for label, value in (face.get("emotions") or {}).items():
                        merged[label] = merged.get(label, 0.0) + float(value)
                return merged
            result = detector.analyze(  # deepface
                img_path=str(frame),
                actions=["emotion"],
                enforce_detection=False,
                silent=True,
            )
            if isinstance(result, list):
                result = result[0] if result else {}
            raw = (result or {}).get("emotion") or {}
            return {k: float(v) / 100.0 for k, v in raw.items()}
        except Exception:
            return {}


BACKENDS: dict[str, type[Backend]] = {
    "heuristic": HeuristicBackend,
    "face": FaceBackend,
}


def get_backend(name: str) -> Backend:
    """Build a backend by name, with a clear error for a bad name."""
    try:
        return BACKENDS[name]()
    except KeyError:
        raise EmotionError(
            f"unknown backend {name!r}. Choose from: {', '.join(BACKENDS)}"
        ) from None


def top_emotion(scores: dict[str, float]) -> str:
    """The winning bucket, or 'calm' when we have nothing to go on."""
    if not scores:
        return "calm"
    return max(scores, key=lambda k: scores[k])


def describe_scores(scores: dict[str, float], *, top: int = 3) -> str:
    """'fun 42%, happy 31%, calm 12%'."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return ", ".join(f"{name} {value * 100:.0f}%" for name, value in ranked)


def confidence(scores: dict[str, float]) -> float:
    """How much the winner beats the runner-up: 0 = a coin toss."""
    if len(scores) < 2:
        return 0.0
    ranked = sorted(scores.values(), reverse=True)
    best, second = ranked[0], ranked[1]
    if best <= 0:
        return 0.0
    return _clamp((best - second) / best)


def is_uncertain(scores: dict[str, float], threshold: float = 0.15) -> bool:
    """True when the call is close enough that a human should look."""
    return confidence(scores) < threshold and not math.isclose(
        max(scores.values(), default=0.0), 0.0
    )
