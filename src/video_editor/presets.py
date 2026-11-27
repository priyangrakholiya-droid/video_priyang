"""Event presets, loaded from `config/presets/*.json`.

A preset is data, not code. Adding a new kind of event - a naming ceremony, a
graduation, a corporate launch - means dropping one more JSON file into
`config/presets/`. Nothing in this package needs to change.

Each file looks like this:

    {
      "name": "baby_shower",
      "title": "Baby shower",
      "description": "...",
      "target_minutes": 4.0,
      "segments": [
        {"id": "reveal", "title": "Reveal", "mood": "happy",
         "keywords": ["reveal", "gender"], "required": false}
      ],
      "emotion_arc": ["calm", "happy", "fun", "romantic", "emotional"],
      "pacing": {"min_clip_seconds": 2.0, "max_clip_seconds": 10.0, "snap": "bar"},
      "audio": {"mode": "mix", "music_volume": 0.85, "original_volume": 0.3},
      "autodetect": {"scene_threshold": 0.3, "min_gap_seconds": 4.0,
                     "prefer_loud": false}
    }

What each part drives:

  segments      the running order used by `arrange --mode story`, and the
                segment names you can tag a clip with. `mood` gives the
                emotion step a prior, `keywords` let a file name or a label
                be matched to a segment automatically.
  emotion_arc   the order used by `arrange --mode emotion`.
  pacing        how long a clip may be, and the default beat snapping.
  audio         the default mix for the render step.
  autodetect    how aggressively `autoselect` looks for moments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# The six emotion buckets. Fixed, because the analyser scores exactly these.
EMOTIONS: tuple[str, ...] = (
    "happy",
    "emotional",
    "romantic",
    "fun",
    "ritual",
    "calm",
)

# Used when a preset omits a section, and as the fallback preset if the
# config folder is missing entirely (a pip install without the repo).
DEFAULT_PACING = {"min_clip_seconds": 2.0, "max_clip_seconds": 12.0, "snap": "bar"}
DEFAULT_AUDIO = {"mode": "mix", "music_volume": 0.9, "original_volume": 0.25}
DEFAULT_AUTODETECT = {
    "scene_threshold": 0.3,
    "min_gap_seconds": 4.0,
    "prefer_loud": True,
}
DEFAULT_ARC = ("calm", "happy", "fun", "romantic", "ritual", "emotional")

FALLBACK = {
    "schema": 1,
    "name": "general",
    "title": "General purpose",
    "description": "Built-in fallback preset (config/presets was not found).",
    "target_minutes": 5.0,
    "segments": [
        {"id": "opening", "title": "Opening", "mood": "calm", "keywords": []},
        {"id": "main", "title": "Main action", "mood": "happy", "keywords": []},
        {"id": "people", "title": "People", "mood": "happy", "keywords": []},
        {"id": "detail", "title": "Details", "mood": "calm", "keywords": []},
        {"id": "closing", "title": "Closing", "mood": "emotional", "keywords": []},
    ],
    "emotion_arc": list(DEFAULT_ARC),
    "pacing": dict(DEFAULT_PACING),
    "audio": dict(DEFAULT_AUDIO),
    "autodetect": dict(DEFAULT_AUTODETECT),
}


class PresetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Segment:
    """One part of an event, e.g. the varmala, or the cake cutting."""

    id: str
    title: str = ""
    mood: str = ""
    keywords: tuple[str, ...] = ()
    required: bool = False

    def matches(self, text: str) -> bool:
        """True if a file name or label looks like this segment."""
        haystack = (text or "").lower()
        if not haystack:
            return False
        if self.id.replace("_", " ") in haystack or self.id in haystack:
            return True
        return any(word and word in haystack for word in self.keywords)


@dataclass(frozen=True)
class Preset:
    """One kind of event."""

    name: str
    title: str
    description: str
    target_minutes: float
    segments: tuple[Segment, ...]
    emotion_arc: tuple[str, ...]
    pacing: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PACING))
    audio: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_AUDIO))
    autodetect: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_AUTODETECT)
    )
    source: str = ""

    # ------------------------------------------------------------- accessors
    @property
    def segment_ids(self) -> list[str]:
        return [s.id for s in self.segments]

    @property
    def required_segments(self) -> list[str]:
        return [s.id for s in self.segments if s.required]

    @property
    def target_duration(self) -> float:
        return self.target_minutes * 60.0

    def segment(self, sid: str) -> Segment | None:
        return next((s for s in self.segments if s.id == sid), None)

    def resolve_segment(self, text: str) -> str:
        """Accept a full id, a prefix, or a guess from a file name/label."""
        wanted = (text or "").strip().lower().lstrip("#")
        if not wanted:
            return ""
        exact = self.segment(wanted)
        if exact:
            return exact.id
        prefixed = [s.id for s in self.segments if s.id.startswith(wanted)]
        if len(prefixed) == 1:
            return prefixed[0]
        if prefixed:
            raise PresetError(
                f"{wanted!r} could be any of: {', '.join(prefixed)}. Be more specific."
            )
        guessed = [s.id for s in self.segments if s.matches(wanted)]
        if len(guessed) == 1:
            return guessed[0]
        raise PresetError(
            f"unknown segment {wanted!r} for the {self.name} preset. "
            f"Known: {', '.join(self.segment_ids)}"
        )

    def guess_segment(self, text: str) -> str:
        """Best-effort segment for a file name or label. '' when unsure."""
        hits = [s.id for s in self.segments if s.matches(text)]
        return hits[0] if len(hits) == 1 else ""

    def mood_of(self, segment_id: str) -> str:
        seg = self.segment(segment_id)
        return seg.mood if seg else ""

    def pacing_value(self, key: str) -> Any:
        return self.pacing.get(key, DEFAULT_PACING.get(key))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "target_minutes": self.target_minutes,
            "segments": [
                {
                    "id": s.id,
                    "title": s.title,
                    "mood": s.mood,
                    "keywords": list(s.keywords),
                    "required": s.required,
                }
                for s in self.segments
            ],
            "emotion_arc": list(self.emotion_arc),
            "pacing": dict(self.pacing),
            "audio": dict(self.audio),
            "autodetect": dict(self.autodetect),
        }


# ------------------------------------------------------------------- loading
def presets_dir(override: str | Path | None = None) -> Path | None:
    """Where the preset files live.

    Search order: an explicit override, then `config/presets` beside the
    working directory, then `config/presets` at the root of this checkout.
    Returns None when none of those exist.
    """
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path.cwd() / "config" / "presets")
    # src/video_editor/presets.py -> repo root
    candidates.append(Path(__file__).resolve().parents[2] / "config" / "presets")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _build(data: dict[str, Any], source: str = "") -> Preset:
    name = data.get("name")
    if not name:
        raise PresetError(f"{source or 'preset'} has no \"name\"")
    raw_segments = data.get("segments") or []
    if not raw_segments:
        raise PresetError(f"preset {name!r} lists no segments")

    segments: list[Segment] = []
    seen: set[str] = set()
    for raw in raw_segments:
        if isinstance(raw, str):  # allow a bare list of ids
            raw = {"id": raw}
        sid = (raw.get("id") or "").strip()
        if not sid:
            raise PresetError(f"preset {name!r} has a segment with no id")
        if sid in seen:
            raise PresetError(f"preset {name!r} lists the segment {sid!r} twice")
        seen.add(sid)
        segments.append(
            Segment(
                id=sid,
                title=raw.get("title") or sid.replace("_", " ").title(),
                mood=raw.get("mood") or "",
                keywords=tuple(str(k).lower() for k in (raw.get("keywords") or [])),
                required=bool(raw.get("required")),
            )
        )

    arc = tuple(data.get("emotion_arc") or DEFAULT_ARC)
    unknown = [mood for mood in arc if mood not in EMOTIONS]
    if unknown:
        raise PresetError(
            f"preset {name!r} names unknown emotions in emotion_arc: "
            f"{', '.join(unknown)}. Known: {', '.join(EMOTIONS)}"
        )

    try:
        target = float(data.get("target_minutes") or 5.0)
    except (TypeError, ValueError):
        raise PresetError(f"preset {name!r} has a non-numeric target_minutes") from None
    if target <= 0:
        raise PresetError(f"preset {name!r} has a target_minutes of {target}")

    return Preset(
        name=name,
        title=data.get("title") or name.replace("_", " ").title(),
        description=data.get("description") or "",
        target_minutes=target,
        segments=tuple(segments),
        emotion_arc=arc,
        pacing={**DEFAULT_PACING, **(data.get("pacing") or {})},
        audio={**DEFAULT_AUDIO, **(data.get("audio") or {})},
        autodetect={**DEFAULT_AUTODETECT, **(data.get("autodetect") or {})},
        source=source,
    )


@lru_cache(maxsize=8)
def load_all(override: str | None = None) -> dict[str, Preset]:
    """Every preset on disk, keyed by name. Cached per presets directory."""
    directory = presets_dir(override)
    if directory is None:
        return {"general": _build(FALLBACK, source="<built-in>")}

    found: dict[str, Preset] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            preset = _build(data, source=str(path))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: not valid JSON ({exc})")
            continue
        except PresetError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if preset.name in found:
            errors.append(f"{path.name}: a preset named {preset.name!r} already loaded")
            continue
        found[preset.name] = preset

    if not found:
        detail = "; ".join(errors) if errors else "the folder holds no .json files"
        raise PresetError(f"no usable presets in {directory} ({detail})")
    if errors:
        # Broken files are skipped, not fatal - but say so loudly.
        import sys

        for problem in errors:
            print(f"  [!] skipped preset {problem}", file=sys.stderr)
    return found


def load(name: str, override: str | None = None) -> Preset:
    """One preset by name, with a helpful error listing the alternatives."""
    everything = load_all(override)
    key = (name or "").strip().lower()
    if key in everything:
        return everything[key]
    close = [k for k in everything if k.startswith(key)] if key else []
    if len(close) == 1:
        return everything[close[0]]
    raise PresetError(
        f"unknown preset {name!r}. Available: {', '.join(sorted(everything))}"
    )


def names(override: str | None = None) -> list[str]:
    return sorted(load_all(override))
