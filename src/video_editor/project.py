"""The project: a folder of DEFINITIONS, not a folder of video.

This is the thing that changed in schema 2, and it is the point of the design:

    A clip is a reference - a source path and an in/out point - and nothing
    else. No piece of footage is ever copied, re-encoded or hard-linked into
    the project. Only one video file is ever written: the finished film.

So a project folder stays a few hundred kilobytes no matter how much footage
you point it at, every step is instant and reversible, and the final render
goes straight back to the original frames, losing nothing to an intermediate
encode. It also means a project is a document: you can read it, edit it in a
text editor, send it to someone else, or hand it to an agent.

    projects/priya-rahul-marriage/
      project.json              the whole state, the only thing that matters
      edit.json                 the portable edit plan (references + timings)
      01_selection/             selection.json, candidates.json
      02_arrangement/           order.json, cuts.csv
      03_music/                 beatmap.json, beats.txt, beat_sheet.csv
      04_emotion/               scores.json, emotions.csv
      05_output/                the finished film + render_plan.csv
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from video_editor.presets import EMOTIONS, Preset, PresetError, load as load_preset

MANIFEST_NAME = "project.json"
EDIT_PLAN_NAME = "edit.json"
SCHEMA = 2

# One folder per step. They hold definitions and reports - never footage,
# except 05_output, which holds the single finished film.
STEP_DIRS: dict[str, str] = {
    "selection": "01_selection",
    "arrangement": "02_arrangement",
    "music": "03_music",
    "emotion": "04_emotion",
    "output": "05_output",
}

STEP_ORDER: tuple[str, ...] = ("select", "arrange", "music", "emotions", "render")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip()).strip("-").lower()
    return slug or "project"


class ProjectError(RuntimeError):
    pass


@dataclass
class Clip:
    """A reference to a stretch of footage. Holds no video, only coordinates."""

    id: str
    source: str               # absolute path of the original file
    source_name: str
    source_in: float          # seconds into that file
    source_out: float
    label: str = ""
    order: int | None = None  # running order, set by step 2
    segment: str = ""         # which part of the event
    emotion: str = ""         # set by step 4
    emotion_scores: dict[str, float] = field(default_factory=dict)
    beat_duration: float | None = None  # beat-snapped length, set by step 3
    head_hash: int | None = None        # first-frame fingerprint, step 2
    tail_hash: int | None = None        # last-frame fingerprint, step 2
    score: float = 0.0        # confidence, when a detector proposed this clip
    origin: str = "manual"    # "manual" or "auto"
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(self.source_out - self.source_in, 0.0)

    @property
    def render_duration(self) -> float:
        """What the final cut uses: the beat-snapped length when we have one."""
        return self.beat_duration if self.beat_duration else self.duration

    @property
    def render_out(self) -> float:
        """Where the cut actually ends in the source, after beat snapping."""
        return self.source_in + self.render_duration

    def describe(self) -> str:
        return self.label or f"{self.source_name} @ {self.source_in:.1f}s"


class Project:
    """Read/write access to one project folder."""

    def __init__(self, root: Path, data: dict[str, Any], preset: Preset | None = None):
        self.root = Path(root)
        self.data = data
        self._preset = preset

    # ------------------------------------------------------------------ create
    @classmethod
    def create(
        cls,
        root: Path,
        *,
        name: str,
        preset: str | Preset = "general",
        target_duration: float | None = None,
        sources: list[Path] | None = None,
        input_path: str = "",
        presets_dir: str | None = None,
    ) -> "Project":
        root = Path(root)
        if (root / MANIFEST_NAME).exists():
            raise ProjectError(
                f"a project already lives in {root}. Delete it or pick another name."
            )
        resolved = preset if isinstance(preset, Preset) else load_preset(preset, presets_dir)
        root.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "schema": SCHEMA,
            "name": name,
            "slug": slugify(name),
            "preset": resolved.name,
            "preset_title": resolved.title,
            "segments": resolved.segment_ids,
            "created": datetime.now().isoformat(timespec="seconds"),
            "updated": "",
            "input_path": input_path,
            "target_duration": (
                resolved.target_duration if target_duration is None else target_duration
            ),
            "sources": [str(Path(s).resolve()) for s in (sources or [])],
            "clips": [],
            "candidates": [],
            "music": {},
            "output": {},
            "steps_done": [],
            "settings": {
                "pacing": dict(resolved.pacing),
                "audio": dict(resolved.audio),
                "autodetect": dict(resolved.autodetect),
            },
        }
        project = cls(root, data, resolved)
        project.ensure_dirs()
        project.save()
        return project

    @classmethod
    def load(cls, root: str | Path, presets_dir: str | None = None) -> "Project":
        root = Path(root).expanduser()
        manifest = root / MANIFEST_NAME
        if not manifest.is_file():
            raise ProjectError(f"no {MANIFEST_NAME} in {root}. Run the select step first.")
        with manifest.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        schema = int(data.get("schema") or 1)
        if schema > SCHEMA:
            raise ProjectError(
                f"{manifest} was written by a newer version "
                f"(schema {schema}, this build understands {SCHEMA})."
            )
        if schema < SCHEMA:
            data = _migrate(data, schema)

        preset: Preset | None = None
        try:
            preset = load_preset(data.get("preset") or "general", presets_dir)
        except PresetError:
            preset = None  # a project can still be read with its preset missing
        return cls(root, data, preset)

    # ------------------------------------------------------------------ layout
    def dir(self, step: str) -> Path:
        try:
            name = STEP_DIRS[step]
        except KeyError:
            raise ProjectError(
                f"unknown step folder {step!r}. Known: {', '.join(STEP_DIRS)}"
            ) from None
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        for step in STEP_DIRS:
            self.dir(step)

    def write_definition(self, step: str, filename: str, payload: Any) -> Path:
        """Write one JSON definition file into a step folder."""
        destination = self.dir(step) / filename
        with destination.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return destination

    def write_report(self, step: str, filename: str, lines: list[str]) -> Path:
        """Write one CSV/text report into a step folder."""
        destination = self.dir(step) / filename
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return destination

    # -------------------------------------------------------------- properties
    @property
    def name(self) -> str:
        return self.data.get("name", self.root.name)

    @property
    def slug(self) -> str:
        return self.data.get("slug") or slugify(self.name)

    @property
    def preset_name(self) -> str:
        return self.data.get("preset", "general")

    @property
    def preset(self) -> Preset:
        if self._preset is None:
            raise ProjectError(
                f"the preset {self.preset_name!r} this project was made with is not "
                "installed. Restore config/presets, or set another with --preset."
            )
        return self._preset

    @property
    def segments(self) -> list[str]:
        return list(self.data.get("segments") or [])

    @property
    def emotion_arc(self) -> list[str]:
        if self._preset is not None:
            return list(self._preset.emotion_arc)
        return list(EMOTIONS)

    @property
    def settings(self) -> dict[str, Any]:
        return self.data.setdefault("settings", {})

    def setting(self, group: str, key: str, default: Any = None) -> Any:
        return (self.settings.get(group) or {}).get(key, default)

    @property
    def target_duration(self) -> float:
        return float(self.data.get("target_duration") or 0.0)

    @target_duration.setter
    def target_duration(self, seconds: float) -> None:
        self.data["target_duration"] = float(seconds)

    @property
    def sources(self) -> list[str]:
        return list(self.data.get("sources") or [])

    @property
    def clips(self) -> list[Clip]:
        return [Clip(**c) for c in self.data.get("clips", [])]

    @clips.setter
    def clips(self, clips: list[Clip]) -> None:
        self.data["clips"] = [asdict(c) for c in clips]

    @property
    def candidates(self) -> list[Clip]:
        """Moments a detector proposed but that have not been accepted yet."""
        return [Clip(**c) for c in self.data.get("candidates", [])]

    @candidates.setter
    def candidates(self, clips: list[Clip]) -> None:
        self.data["candidates"] = [asdict(c) for c in clips]

    def ordered_clips(self) -> list[Clip]:
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

    def clip(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def next_clip_id(self, existing: list[Clip] | None = None) -> str:
        taken = {c.id for c in (existing if existing is not None else self.clips)}
        n = len(taken) + 1
        while f"c{n:03d}" in taken:
            n += 1
        return f"c{n:03d}"

    # -------------------------------------------------------------- step state
    def mark_done(self, step: str) -> None:
        done = self.data.setdefault("steps_done", [])
        if step not in done:
            done.append(step)

    def is_done(self, step: str) -> bool:
        return step in (self.data.get("steps_done") or [])

    def next_step(self) -> str | None:
        return next((s for s in STEP_ORDER if not self.is_done(s)), None)

    # ------------------------------------------------------------- edit plan
    def edit_plan(self) -> dict[str, Any]:
        """The portable plan: everything needed to rebuild this film elsewhere.

        Deliberately free of machine-specific state (no frame hashes, no
        scores) so it reads cleanly and diffs cleanly.
        """
        music = self.data.get("music") or {}
        timeline = 0.0
        entries = []
        for clip in self.ordered_clips():
            entries.append({
                "position": clip.order,
                "id": clip.id,
                "source": clip.source,
                "source_in": round(clip.source_in, 3),
                "source_out": round(clip.render_out, 3),
                "duration": round(clip.render_duration, 3),
                "starts_at": round(timeline, 3),
                "segment": clip.segment,
                "emotion": clip.emotion,
                "label": clip.label,
            })
            timeline += clip.render_duration
        return {
            "schema": SCHEMA,
            "name": self.name,
            "preset": self.preset_name,
            "target_duration": round(self.target_duration, 3),
            "runtime": round(timeline, 3),
            "music": {
                "file": music.get("file", ""),
                "bpm": music.get("bpm"),
                "period": music.get("period"),
                "offset": music.get("offset"),
                "snap": music.get("snap_group"),
            } if music else {},
            "audio": dict(self.settings.get("audio") or {}),
            "clips": entries,
        }

    def write_edit_plan(self) -> Path:
        destination = self.root / EDIT_PLAN_NAME
        with destination.open("w", encoding="utf-8") as fh:
            json.dump(self.edit_plan(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return destination

    # ---------------------------------------------------------------- summary
    def summary(self) -> dict[str, Any]:
        """Compact machine-readable state. This is what `--json` prints."""
        music = self.data.get("music") or {}
        by_emotion: dict[str, int] = {}
        by_segment: dict[str, int] = {}
        for clip in self.clips:
            if clip.emotion:
                by_emotion[clip.emotion] = by_emotion.get(clip.emotion, 0) + 1
            if clip.segment:
                by_segment[clip.segment] = by_segment.get(clip.segment, 0) + 1
        return {
            "project": self.root.name,
            "path": str(self.root.resolve()),
            "name": self.name,
            "preset": self.preset_name,
            "target_duration": round(self.target_duration, 3),
            "clips": len(self.clips),
            "candidates": len(self.candidates),
            "selected_duration": round(self.selected_duration, 3),
            "render_duration": round(self.render_duration, 3),
            "arranged": all(c.order is not None for c in self.clips) and bool(self.clips),
            "music": {
                "file": music.get("file", ""),
                "bpm": music.get("bpm"),
                "snap": music.get("snap_group"),
            } if music else None,
            "by_segment": by_segment,
            "by_emotion": by_emotion,
            "steps_done": list(self.data.get("steps_done") or []),
            "next_step": self.next_step(),
            "output": dict(self.data.get("output") or {}),
            "updated": self.data.get("updated", ""),
        }

    # ----------------------------------------------------------------- persist
    def save(self) -> None:
        """Write project.json atomically, then refresh edit.json beside it."""
        self.data["updated"] = datetime.now().isoformat(timespec="seconds")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (MANIFEST_NAME + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        shutil.move(str(tmp), str(self.root / MANIFEST_NAME))
        if self.data.get("clips"):
            self.write_edit_plan()


def _migrate(data: dict[str, Any], from_schema: int) -> dict[str, Any]:
    """Bring an older project.json up to the current schema.

    Schema 1 kept a copy of every clip inside the project and recorded it in a
    "file" field. Schema 2 holds references only, so that field is dropped -
    the in/out points it was cut from are what matter, and those are kept.
    """
    if from_schema <= 1:
        for clip in data.get("clips") or []:
            clip.pop("file", None)
            clip.setdefault("score", 0.0)
            clip.setdefault("origin", "manual")
        data.setdefault("candidates", [])
        data.setdefault("output", data.pop("final", {}) or {})
        data.setdefault("settings", {})
        data["schema"] = 2
    return data
