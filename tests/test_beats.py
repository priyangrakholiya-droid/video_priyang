"""Beat detection tests.

The ones that need audio build their own click track with ffmpeg, so there is
no media checked into the repo. They skip themselves when ffmpeg is absent.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_editor.beats import BeatMap, analyse, estimate_period, onset_strength

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def click_track(path: Path, bpm: float, seconds: int = 20) -> Path:
    """A metronome at a known tempo: one decaying tone per beat."""
    period = 60.0 / bpm
    expression = f"0.9*sin(2*PI*660*t)*exp(-25*mod(t,{period:.6f}))"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi",
            "-i", f"aevalsrc='{expression}':d={seconds}:s=44100",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class BeatMapMaths(unittest.TestCase):
    """No audio needed: the grid arithmetic on its own."""

    def setUp(self):
        self.beatmap = BeatMap(
            path="song.mp3",
            duration=60.0,
            bpm=120.0,
            period=0.5,
            offset=0.25,
            beats=[0.25 + i * 0.5 for i in range(120)],
            confidence=0.8,
        )

    def test_snap_to_nearest_beat(self):
        self.assertAlmostEqual(self.beatmap.snap_duration(3.3), 3.5)
        self.assertAlmostEqual(self.beatmap.snap_duration(3.1), 3.0)

    def test_snap_to_a_bar(self):
        self.assertAlmostEqual(self.beatmap.snap_duration(3.3, group=4), 4.0)
        self.assertAlmostEqual(self.beatmap.snap_duration(7.0, group=4), 8.0)

    def test_snapping_never_returns_zero(self):
        self.assertAlmostEqual(self.beatmap.snap_duration(0.01), 0.5)
        self.assertAlmostEqual(self.beatmap.snap_duration(0.0, group=4), 2.0)

    def test_snapped_lengths_are_whole_beats(self):
        for wanted in (1.1, 2.7, 5.3, 9.9):
            snapped = self.beatmap.snap_duration(wanted)
            self.assertAlmostEqual(snapped / self.beatmap.period,
                                   round(snapped / self.beatmap.period))

    def test_beats_in(self):
        self.assertEqual(self.beatmap.beats_in(2.0), 4)
        self.assertEqual(self.beatmap.beats_in(2.0, group=4), 1)

    def test_nearest_beat(self):
        self.assertAlmostEqual(self.beatmap.nearest_beat(0.3), 0.25)
        self.assertAlmostEqual(self.beatmap.nearest_beat(0.70), 0.75)
        self.assertAlmostEqual(self.beatmap.nearest_beat(-5.0), 0.25)
        self.assertAlmostEqual(self.beatmap.nearest_beat(9999.0), self.beatmap.beats[-1])

    def test_bar_period(self):
        self.assertAlmostEqual(self.beatmap.bar_period, 2.0)

    def test_serialises_round_trip(self):
        again = BeatMap.from_dict(self.beatmap.to_dict())
        self.assertAlmostEqual(again.bpm, 120.0)
        self.assertAlmostEqual(again.period, 0.5)
        self.assertEqual(len(again.beats), 120)


class OnsetStrength(unittest.TestCase):
    def test_rising_loudness_makes_an_onset(self):
        levels = [-60.0, -60.0, -20.0, -30.0, -60.0, -60.0]
        onsets = onset_strength(levels)
        self.assertEqual(len(onsets), len(levels))
        self.assertGreater(max(onsets), 0.0)
        # The peak sits at or next to the jump, not at the end.
        self.assertLess(onsets.index(max(onsets)), 4)

    def test_flat_audio_has_no_onsets(self):
        self.assertEqual(max(onset_strength([-30.0] * 50)), 0.0)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg is not installed")
class RealAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_finds_120_bpm(self):
        song = click_track(self.tmp / "c120.wav", 120.0)
        beatmap = analyse(song)
        self.assertAlmostEqual(beatmap.bpm, 120.0, delta=2.0)
        self.assertGreater(beatmap.confidence, 0.3)

    def test_finds_100_bpm(self):
        song = click_track(self.tmp / "c100.wav", 100.0)
        self.assertAlmostEqual(analyse(song).bpm, 100.0, delta=2.0)

    def test_finds_140_bpm(self):
        song = click_track(self.tmp / "c140.wav", 140.0)
        self.assertAlmostEqual(analyse(song).bpm, 140.0, delta=3.0)

    def test_beats_are_evenly_spaced_and_cover_the_song(self):
        song = click_track(self.tmp / "even.wav", 120.0, seconds=20)
        beatmap = analyse(song)
        gaps = [
            beatmap.beats[i] - beatmap.beats[i - 1]
            for i in range(1, len(beatmap.beats))
        ]
        for gap in gaps:
            self.assertAlmostEqual(gap, beatmap.period, places=6)
        self.assertGreater(len(beatmap.beats), 30)
        self.assertLess(beatmap.beats[0], beatmap.period + 0.01)

    def test_phase_lands_on_the_clicks(self):
        # Clicks start at t=0, so the detected first beat must be near a multiple
        # of the period, not halfway between two clicks.
        beatmap = analyse(click_track(self.tmp / "phase.wav", 120.0))
        remainder = beatmap.offset % beatmap.period
        distance = min(remainder, beatmap.period - remainder)
        self.assertLess(distance, beatmap.period * 0.25)


class PeriodEstimation(unittest.TestCase):
    def test_a_synthetic_pulse_gives_its_own_period(self):
        # A spike every 21 frames (~0.49s at a 23.2ms hop) -> about 123 BPM.
        onsets = [1.0 if i % 21 == 0 else 0.0 for i in range(600)]
        period, confidence = estimate_period(onsets)
        self.assertAlmostEqual(60.0 / period, 123.0, delta=6.0)
        self.assertGreater(confidence, 0.5)

    def test_silence_is_refused(self):
        from video_editor.beats import BeatError

        with self.assertRaises(BeatError):
            estimate_period([0.0] * 600)


if __name__ == "__main__":
    unittest.main()
