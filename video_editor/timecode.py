"""Parsing and formatting of timestamps typed by a human."""

from __future__ import annotations

import re

_TC_RE = re.compile(
    r"""^\s*
    (?:(?P<h>\d+):)?        # optional hours
    (?:(?P<m>\d+):)?        # optional minutes
    (?P<s>\d+(?:\.\d+)?)    # seconds, may be fractional
    \s*$""",
    re.VERBOSE,
)

_UNIT_RE = re.compile(
    r"^\s*(?:(?P<h>\d+(?:\.\d+)?)h)?"
    r"(?:(?P<m>\d+(?:\.\d+)?)m)?"
    r"(?:(?P<s>\d+(?:\.\d+)?)s)?\s*$",
    re.IGNORECASE,
)


class TimecodeError(ValueError):
    """Raised when a string cannot be read as a timestamp."""


def parse_timecode(text: str) -> float:
    """Turn '90', '1:30', '00:01:30.5' or '1h2m3s' into seconds.

    >>> parse_timecode("1:30")
    90.0
    >>> parse_timecode("00:01:30.5")
    90.5
    """
    if text is None:
        raise TimecodeError("no timestamp given")
    raw = text.strip()
    if not raw:
        raise TimecodeError("no timestamp given")

    m = _TC_RE.match(raw)
    if m:
        hours = float(m.group("h") or 0)
        minutes = float(m.group("m") or 0)
        seconds = float(m.group("s"))
        # '1:30' means 1 minute 30 seconds, not 1 hour 30 minutes.
        two_part = bool(m.group("h")) and not m.group("m")
        if two_part:
            hours, minutes = 0.0, float(m.group("h"))
        # In HH:MM:SS the minutes field cannot reach 60 - '00:99:00' is a typo,
        # not an hour and 39 minutes. In the MM:SS form a big minutes value is
        # fine: '90:00' is a legitimate hour and a half.
        if m.group("h") and m.group("m") and minutes >= 60:
            raise TimecodeError(f"{raw!r}: minutes must be under 60")
        # Any colon form means the last field is seconds, so it cannot reach 60.
        if m.group("h") and seconds >= 60:
            raise TimecodeError(f"{raw!r}: seconds must be under 60")
        return hours * 3600 + minutes * 60 + seconds

    m = _UNIT_RE.match(raw)
    if m and any(m.group(g) for g in ("h", "m", "s")):
        return (
            float(m.group("h") or 0) * 3600
            + float(m.group("m") or 0) * 60
            + float(m.group("s") or 0)
        )

    raise TimecodeError(
        f"{raw!r} is not a timestamp. Use 90, 1:30, 00:01:30.5 or 1h2m3s."
    )


def format_timecode(seconds: float) -> str:
    """Seconds -> 'HH:MM:SS.mmm' (what ffmpeg and humans both read)."""
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    if ms == 1000:  # rounding carried over
        whole += 1
        ms = 0
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_duration(seconds: float) -> str:
    """Seconds -> '2m 05s', for readable summaries."""
    total = int(round(seconds))
    m, s = divmod(total, 60)
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def parse_minutes(text: str) -> float:
    """Read the answer to 'how many minutes?' and return seconds."""
    raw = (text or "").strip().lower().rstrip("m").strip()
    if not raw:
        raise TimecodeError("no duration given")
    try:
        minutes = float(raw)
    except ValueError:
        # Allow '1:30' to mean a minute and a half.
        return parse_timecode(text)
    if minutes <= 0:
        raise TimecodeError("the target duration must be more than 0 minutes")
    return minutes * 60
