"""Tests for the automatic moment finder.

The ones needing video build their own footage with ffmpeg: six distinct
eight-second shots concatenated, so the scene detector has real cuts to find
at known times.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_editor import presets
from video_editor.detect import (
    DetectError,
    Moment,
    fill_target,
    find_moments,
    scene_changes,
    spread_out,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

SHOT_LENGTH = 8
SHOTS = ["smptebars", "testsrc2", "rgbtestsrc", "smptehdbars"]


def build_footage(directory: Path) -> Path:
    """Four distinct shots, so cuts fall at 8s, 16s and 24s."""
    parts = []
    for i, pattern in enumerate(SHOTS, 1):
        part = directory / f"p{i}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-v", "error", "-y",
                "-f", "lavfi",
                "-i", f"{pattern}=size=320x180:rate=15:duration={SHOT_LENGTH}",
                "-f", "lavfi", "-i", f"sine=frequency={300 + i * 150}:duration={SHOT_LENGTH}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(part),
            ],
            check=True, capture_output=True,
        )
        parts.append(part)

    listing = directory / "list.txt"
    listing.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts) + "\n", encoding="utf-8"
    )
    full = directory / "event.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(full),
        ],
        check=True, capture_output=True,
    )
    return full


def moment(source="a.mp4", start=0.0, end=5.0, score=0.5):
    return Moment(
        source=source, source_name=source, start=start, end=end, score=score
    )


class SpreadOut(unittest.TestCase):
    def test_keeps_the_better_of_two_close_moments(self):
        kept = spread_out(
            [
                moment(start=10.0, score=0.9),
                moment(start=11.0, score=0.4),
            ],
            min_gap=5.0,
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].score, 0.9)

    def test_keeps_both_when_far_apart(self):
        kept = spread_out(
            [moment(start=10.0, score=0.9), moment(start=40.0, score=0.4)],
            min_gap=5.0,
        )
        self.assertEqual(len(kept), 2)

    def test_the_gap_is_per_source_file(self):
        # Same timestamp in two different files is not a clash.
        kept = spread_out(
            [
                moment(source="a.mp4", start=10.0, score=0.9),
                moment(source="b.mp4", start=10.0, score=0.8),
            ],
            min_gap=30.0,
        )
        self.assertEqual(len(kept), 2)

    def test_empty_in_empty_out(self):
        self.assertEqual(spread_out([], 5.0), [])


class FillTarget(unittest.TestCase):
    def test_takes_the_best_until_the_target_is_met(self):
        moments = [
            moment(start=0.0, end=5.0, score=0.1),
            moment(start=10.0, end=15.0, score=0.9),
            moment(start=20.0, end=25.0, score=0.8),
        ]
        chosen = fill_target(moments, target=10.0)
        self.assertEqual(len(chosen), 2)
        self.assertEqual({c.score for c in chosen}, {0.9, 0.8})

    def test_returns_them_in_footage_order(self):
        moments = [
            moment(start=30.0, score=0.9),
            moment(start=10.0, score=0.8),
            moment(start=20.0, score=0.7),
        ]
        chosen = fill_target(moments, target=100.0)
        self.assertEqual([c.start for c in chosen], [10.0, 20.0, 30.0])

    def test_a_tiny_target_still_yields_one_clip(self):
        self.assertEqual(len(fill_target([moment()], target=0.1)), 1)


class MomentMaths(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(moment(start=4.0, end=9.0).duration, 5.0)

    def test_duration_never_negative(self):
        self.assertEqual(moment(start=9.0, end=4.0).duration, 0.0)

    def test_reason_mentions_both_signals(self):
        text = Moment("a", "a", 0, 5, score=0.7, scene_score=0.6, energy=0.8).reason()
        self.assertIn("scene", text)
        self.assertIn("loudness", text)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg is not installed")
class RealFootage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.footage = build_footage(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_finds_the_cuts_at_the_right_times(self):
        found = scene_changes(self.footage, threshold=0.3)
        times = [round(t) for t, _ in found]
        for expected in (SHOT_LENGTH, SHOT_LENGTH * 2, SHOT_LENGTH * 3):
            self.assertTrue(
                any(abs(t - expected) <= 1 for t in times),
                f"no cut detected near {expected}s, found {times}",
            )

    def test_a_high_threshold_finds_fewer_cuts(self):
        many = scene_changes(self.footage, threshold=0.1)
        few = scene_changes(self.footage, threshold=0.9)
        self.assertGreaterEqual(len(many), len(few))

    def test_proposed_moments_respect_the_length_limits(self):
        moments = find_moments(
            self.footage, min_clip=2.0, max_clip=6.0, threshold=0.3
        )
        self.assertTrue(moments)
        for m in moments:
            self.assertGreaterEqual(m.duration, 2.0 - 0.01)
            self.assertLessEqual(m.duration, 6.0 + 0.01)

    def test_proposed_moments_stay_inside_the_file(self):
        from video_editor.probe import probe

        duration = probe(self.footage).duration
        for m in find_moments(self.footage, threshold=0.3):
            self.assertGreaterEqual(m.start, 0.0)
            self.assertLessEqual(m.end, duration + 0.05)
            self.assertLess(m.start, m.end)

    def test_scores_are_in_range_and_explained(self):
        for m in find_moments(self.footage, threshold=0.3):
            self.assertGreaterEqual(m.score, 0.0)
            self.assertLessEqual(m.score, 1.0)
            self.assertGreaterEqual(m.energy, 0.0)
            self.assertLessEqual(m.energy, 1.0)

    def test_propose_fills_a_target(self):
        from video_editor.detect import propose

        preset = presets.load("party")
        chosen, tally = propose(
            [self.footage], target_duration=12.0, preset=preset, threshold=0.3
        )
        self.assertTrue(chosen)
        self.assertEqual(sum(tally.values()), tally[self.footage.name])
        total = sum(c.duration for c in chosen)
        self.assertGreater(total, 0)
        # It should not wildly overshoot: one clip of overshoot is acceptable.
        longest = max(c.duration for c in chosen)
        self.assertLessEqual(total - 12.0, longest)

    def test_nonsense_clip_limits_are_refused(self):
        from video_editor.detect import propose

        with self.assertRaises(DetectError):
            propose(
                [self.footage],
                target_duration=10.0,
                preset=presets.load("general"),
                min_clip=9.0,
                max_clip=3.0,
            )


if __name__ == "__main__":
    unittest.main()
