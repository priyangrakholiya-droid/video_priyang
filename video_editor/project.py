"""The project folder: its layout on disk and its manifest (project.json).

Every step of the pipeline reads the manifest, does its work, and writes the
manifest back. That way you can stop after any step and pick up later.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = "project.json"

# One folder per step, numbered so they sort in pipeline order.
STEP_DIRS: dict[str, str] = {
    "source": "01_source",
    "selected": "02_selected",
    "arranged": "03_arranged",
    "music": "04_music",
    "emotion": "05_emotion",
    "final": "06_final",
}

# The emotion buckets step 4 sorts clips into (folders under 05_emotion/).
EMOTIONS: tuple[str, ...] = (
    "happy",      # smiles, bright, lively
    "emotional",  # tears, hugs, farewells
    "romantic",   # couple moments, warm and slow
    "fun",        # dance, games, high energy
    "ritual",     # ceremony, steady and formal
    "calm",       # details, decor, b-roll
)

# Wedding-film presets: the segments an engagement or marriage film is cut from.
PRESETS: dict[str, tuple[str, ...]] = {
    "engagement": (
        "arrival",
        "ring_exchange",
        "couple_portraits",
        "family",
        "speeches",
        "cake_and_toast",
        "dance",
        "candid",
    ),
    "marriage": (
        "mehndi",
        "haldi",
        "baraat",
        "welcome",
        "varmala",
        "pheras",
        "rituals",
        "couple_portraits",
        "family",
        "vidaai",
        "reception",
        "dance",
        "candid",
    ),
    "general": (
        "opening",
        "main",
        "people",
        "detail",
        "closing",
    ),
}


def slugify(text: str) -> str:
    """Turn a title into a safe folder name."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip()).strip("-").lower()
    return slug or "project"


@dataclass
class Clip:
    """One piece of footage the user kept in step 1."""

    id: str
    source: str               # absolute path of the file it was cut from
    source_name: str
    source_in: float          # in-point inside that source, seconds
    source_out: float         # out-point inside that source, seconds
    file: str = ""            # extracted clip, relative to the project root
    label: str = ""
    order: int | None = None  # set by step 2 (arrange)
    segment: str = ""         # e.g. "varmala"
    emotion: str = ""         # set by step 4
    emotion_scores: dict[str, float] = field(default_factory=dict)
    beat_duration: float | None = None  # set by step 3: length snapped to the beat
    head_hash: int | None = None        # frame hash of the first frame (step 2)
    tail_hash: int | None = None        # frame hash of the last frame  (step 2)
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(self.source_out - self.source_in, 0.0)

    @property
    def render_duration(self) -> float:
        """What the final cut uses: the beat-snapped length when we have one."""
        return self.beat_duration if self.beat_duration else self.duration


class ProjectError(RuntimeError):
    pass


class Project:
    """Read/write access to one project folder."""

    def __init__(self, root: Path, data: dict[str, Any]):
        self.root = Path(root)
        self.data = data

    # ------------------------------------------------------------------ create
    @classmethod
    def create(
        cls,
        root: Path,
        *,
        name: str,
        preset: str = "general",
        target_duration: float = 0.0,
        sources: list[Path] | None = None,
        input_path: str = "",
    ) -> "Project":
        root = Path(root)
        if (root / MANIFEST_NAME).exists():
            raise ProjectError(
                f"a project already lives in {root}. Delete it or pick another name."
            )
        if preset not in PRESETS:
            raise ProjectError(
                f"unknown preset {preset!r}. Choose from: {', '.join(PRESETS)}"
            )
        root.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "schema": 1,
            "name": name,
            "slug": slugify(name),
            "preset": preset,
            "segments": list(PRESETS[preset]),
            "created": datetime.now().isoformat(timespec="seconds"),
            "updated": "",
            "input_path": input_path,
            "target_duration": target_duration,
            "sources": [str(Path(s).resolve()) for s in (sources or [])],
            "clips": [],
            "music": {},  # filled by step 3
            "steps_done": [],
        }
        project = cls(root, data)
        project.ensure_dirs()
        project.save()
        return project

    @classmethod
    def load(cls, root: str | Path) -> "Project":
        root = Path(root).expanduser()
        manifest = root / MANIFEST_NAME
        if not manifest.is_file():
            raise ProjectError(
                f"no {MANIFEST_NAME} in {root}. Run the select step first."
            )
        with manifest.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(root, data)

    # ------------------------------------------------------------------ layout
    def dir(self, step: str) -> Path:
        """Absolute path of a step folder, created on demand."""
        try:
            name = STEP_DIRS[step]
        except KeyError:
            raise ProjectError(f"unknown step folder {step!r}") from None
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        """Create every step folder, plus emotion and segment sub-folders."""
        for step in STEP_DIRS:
            self.dir(step)
        for emotion in EMOTIONS:
            (self.dir("emotion") / emotion).mkdir(parents=True, exist_ok=True)
        for segment in self.segments:
            (self.dir("selected") / segment).mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- properties
    @property
    def name(self) -> str:
        return self.data.get("name", self.root.name)

    @property
    def preset(self) -> str:
        return self.data.get("preset", "general")

    @property
    def segments(self) -> list[str]:
        return list(self.data.get("segments") or PRESETS["general"])

    @property
    def target_duration(self) -> float:
        return float(self.data.get("target_duration") or 0.0)

    @target_duration.setter
    def target_duration(self, seconds: float) -> None:
        self.data["target_duration"] = float(seconds)

    @property
    def clips(self) -> list[Clip]:
        return [Clip(**c) for c in self.data.get("clips", [])]

    @clips.setter
    def clips(self, clips: list[Clip]) -> None:
        self.data["clips"] = [asdict(c) for c in clips]

    def ordered_clips(self) -> list[Clip]:
        """Clips in the order step 2 decided; unarranged ones come last."""
        return sorted(
            self.clips,
            key=lambda c: (c.order is None, c.order if c.order is not None else 0, c.id),
        )

    @property
    def selected_duration(self) -> float:
        return sum(c.duration for c in self.clips)

    @property
    def render_duration(self) -> float:
        return sum(c.render_duration for c in self.clips)

    def next_clip_id(self) -> str:
        existing = {c.id for c in self.clips}
        n = len(existing) + 1
        while f"c{n:03d}" in existing:
            n += 1
        return f"c{n:03d}"

    def mark_done(self, step: str) -> None:
        done = self.data.setdefault("steps_done", [])
        if step not in done:
            done.append(step)

    def is_done(self, step: str) -> bool:
        return step in (self.data.get("steps_done") or [])

    # ----------------------------------------------------------------- persist
    def save(self) -> None:
        """Write project.json atomically, so a crash cannot shred the manifest."""
        self.data["updated"] = datetime.now().isoformat(timespec="seconds")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (MANIFEST_NAME + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        shutil.move(str(tmp), str(self.root / MANIFEST_NAME))
