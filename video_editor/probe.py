"""Thin wrappers around the ffmpeg / ffprobe binaries."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpg", ".mpeg",
    ".wmv", ".flv", ".mts", ".m2ts", ".3gp", ".ts",
}


class FFmpegMissing(RuntimeError):
    """ffmpeg or ffprobe is not installed / not on PATH."""


class ProbeError(RuntimeError):
    """ffprobe could not read a file."""


def require_tools() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise FFmpegMissing(
            f"{' and '.join(missing)} not found on PATH. "
            "Install ffmpeg (it ships ffprobe too) and reopen your terminal."
        )


@dataclass(frozen=True)
class MediaInfo:
    """What we need to know about a source file."""

    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ProbeError((proc.stderr or proc.stdout or "").strip()[-600:])
    return proc.stdout


def _parse_fps(text: str | None) -> float:
    if not text or "/" not in text:
        try:
            return float(text) if text else 0.0
        except ValueError:
            return 0.0
    num, _, den = text.partition("/")
    try:
        num_f, den_f = float(num), float(den)
    except ValueError:
        return 0.0
    return num_f / den_f if den_f else 0.0


def probe(path: str | Path) -> MediaInfo:
    """Read duration, resolution, fps and audio presence from a media file."""
    require_tools()
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"not a file: {path}")

    raw = _run([
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ])
    data = json.loads(raw or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path.name}")

    duration = 0.0
    for candidate in (data.get("format", {}).get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break
    if duration <= 0:
        raise ProbeError(f"could not read the duration of {path.name}")

    return MediaInfo(
        path=path,
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=round(_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")), 3),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def find_sources(target: str | Path) -> list[Path]:
    """Return the video files a user pointed us at (one file, or a folder)."""
    target = Path(target).expanduser()
    if target.is_file():
        return [target]
    if target.is_dir():
        found = sorted(
            p for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
        )
        if not found:
            raise ProbeError(f"no video files in {target}")
        return found
    raise ProbeError(f"path does not exist: {target}")


def cut(
    source: str | Path,
    start: float,
    duration: float,
    destination: str | Path,
    *,
    reencode: bool = True,
) -> Path:
    """Write `duration` seconds of `source`, starting at `start`, to `destination`.

    Re-encoding is the default: a stream copy can only cut on keyframes, which
    silently moves your in-point by up to a couple of seconds.
    """
    require_tools()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
    ]
    if reencode:
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        ]
    else:
        cmd += ["-c", "copy"]
    cmd += ["-movflags", "+faststart", str(destination)]
    _run(cmd)
    return destination


def frame_hash(source: str | Path, at: float) -> int | None:
    """A 64-bit difference hash of the frame at `at` seconds.

    Used by the arrange step to tell whether two clips look alike at the cut.
    Returns None when the frame cannot be read (e.g. past the end of file).
    """
    require_tools()
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(at, 0):.3f}", "-i", str(source),
        "-frames:v", "1",
        "-vf", "scale=9:8:flags=bilinear,format=gray",
        "-f", "image2pipe", "-c:v", "pgm", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    pixels = _read_pgm(proc.stdout)
    if pixels is None:
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _read_pgm(blob: bytes) -> list[int] | None:
    """Minimal binary PGM (P5) reader: returns 72 grey values for a 9x8 image."""
    if not blob.startswith(b"P5"):
        return None
    fields: list[bytes] = []
    i = 2
    while len(fields) < 3 and i < len(blob):
        while i < len(blob) and blob[i : i + 1].isspace():
            i += 1
        if blob[i : i + 1] == b"#":  # comment line
            while i < len(blob) and blob[i : i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(blob) and not blob[i : i + 1].isspace():
            i += 1
        fields.append(blob[start:i])
    if len(fields) < 3:
        return None
    try:
        width, height, maxval = (int(f) for f in fields)
    except ValueError:
        return None
    if (width, height) != (9, 8) or maxval > 255:
        return None
    i += 1  # single whitespace byte before the pixel data
    pixels = blob[i : i + width * height]
    if len(pixels) < width * height:
        return None
    return list(pixels)


def hash_distance(a: int, b: int) -> int:
    """How many of the 64 bits differ: 0 = identical frames, 32 = unrelated."""
    return bin(a ^ b).count("1")
