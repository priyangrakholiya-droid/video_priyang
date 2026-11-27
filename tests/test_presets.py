import json
import shutil
import tempfile
import unittest
from pathlib import Path

from video_editor import presets


class ShippedPresets(unittest.TestCase):
    """The presets in config/presets must all be valid and usable."""

    @classmethod
    def setUpClass(cls):
        presets.load_all.cache_clear()
        cls.all = presets.load_all()

    def test_the_documented_events_are_present(self):
        for name in (
            "marriage", "engagement", "party", "baby_shower",
            "birthday", "anniversary", "general",
        ):
            self.assertIn(name, self.all, name)

    def test_every_preset_is_well_formed(self):
        for name, preset in self.all.items():
            with self.subTest(preset=name):
                self.assertTrue(preset.segments, "no segments")
                self.assertGreater(preset.target_minutes, 0)
                self.assertTrue(preset.title)
                self.assertTrue(preset.description)
                ids = preset.segment_ids
                self.assertEqual(len(ids), len(set(ids)), "duplicate segment ids")

    def test_every_arc_mood_is_a_real_emotion(self):
        for name, preset in self.all.items():
            with self.subTest(preset=name):
                for mood in preset.emotion_arc:
                    self.assertIn(mood, presets.EMOTIONS)

    def test_every_segment_mood_is_a_real_emotion(self):
        for name, preset in self.all.items():
            for segment in preset.segments:
                if segment.mood:
                    with self.subTest(preset=name, segment=segment.id):
                        self.assertIn(segment.mood, presets.EMOTIONS)

    def test_pacing_makes_sense(self):
        for name, preset in self.all.items():
            with self.subTest(preset=name):
                low = preset.pacing_value("min_clip_seconds")
                high = preset.pacing_value("max_clip_seconds")
                self.assertGreater(low, 0)
                self.assertGreater(high, low)
                self.assertIn(
                    preset.pacing_value("snap"),
                    ("beat", "half-bar", "bar", "two-bar"),
                )

    def test_audio_mode_is_one_the_renderer_knows(self):
        for name, preset in self.all.items():
            with self.subTest(preset=name):
                self.assertIn(
                    preset.audio.get("mode"),
                    ("music", "mix", "original", "silent"),
                )

    def test_marriage_follows_ceremony_order(self):
        marriage = self.all["marriage"]
        ids = marriage.segment_ids
        self.assertLess(ids.index("haldi"), ids.index("varmala"))
        self.assertLess(ids.index("varmala"), ids.index("pheras"))
        self.assertLess(ids.index("pheras"), ids.index("vidaai"))
        self.assertIn("vidaai", marriage.required_segments)

    def test_to_dict_round_trips(self):
        for name, preset in self.all.items():
            with self.subTest(preset=name):
                rebuilt = presets._build(preset.to_dict())
                self.assertEqual(rebuilt.segment_ids, preset.segment_ids)
                self.assertEqual(rebuilt.emotion_arc, preset.emotion_arc)
                json.dumps(preset.to_dict())


class SegmentMatching(unittest.TestCase):
    def setUp(self):
        self.marriage = presets.load("marriage")

    def test_exact_id(self):
        self.assertEqual(self.marriage.resolve_segment("varmala"), "varmala")

    def test_hash_prefix_is_stripped(self):
        self.assertEqual(self.marriage.resolve_segment("#varmala"), "varmala")

    def test_unique_prefix(self):
        self.assertEqual(self.marriage.resolve_segment("var"), "varmala")

    def test_keyword(self):
        self.assertEqual(self.marriage.resolve_segment("garland"), "varmala")

    def test_unknown_is_an_error_naming_the_options(self):
        with self.assertRaises(presets.PresetError) as caught:
            self.marriage.resolve_segment("quidditch")
        self.assertIn("varmala", str(caught.exception))

    def test_guess_from_a_file_name(self):
        self.assertEqual(self.marriage.guess_segment("CAM1_haldi_002.mp4"), "haldi")
        self.assertEqual(self.marriage.guess_segment("vidaai-final.mov"), "vidaai")

    def test_guess_returns_empty_when_unsure(self):
        self.assertEqual(self.marriage.guess_segment("MVI_0021.mp4"), "")

    def test_mood_of_a_segment(self):
        self.assertEqual(self.marriage.mood_of("vidaai"), "emotional")
        self.assertEqual(self.marriage.mood_of("dance"), "fun")
        self.assertEqual(self.marriage.mood_of("nope"), "")


class CustomPresetFolder(unittest.TestCase):
    """A new event type must be addable as a file, with no code change."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        presets.load_all.cache_clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        presets.load_all.cache_clear()

    def write(self, name, payload):
        (self.tmp / f"{name}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_a_dropped_in_file_becomes_a_preset(self):
        self.write("naming_ceremony", {
            "name": "naming_ceremony",
            "title": "Naming ceremony",
            "description": "A namkaran.",
            "target_minutes": 3.0,
            "segments": [
                {"id": "prayer", "mood": "ritual"},
                {"id": "naming", "mood": "happy", "required": True},
                {"id": "family", "mood": "happy"},
            ],
            "emotion_arc": ["calm", "ritual", "happy"],
        })
        loaded = presets.load("naming_ceremony", str(self.tmp))
        self.assertEqual(loaded.title, "Naming ceremony")
        self.assertEqual(loaded.required_segments, ["naming"])
        self.assertEqual(loaded.target_duration, 180.0)
        # Unspecified sections fall back to the defaults.
        self.assertEqual(loaded.pacing_value("snap"), presets.DEFAULT_PACING["snap"])

    def test_bare_string_segments_are_accepted(self):
        self.write("simple", {
            "name": "simple",
            "target_minutes": 2.0,
            "segments": ["start", "middle", "end"],
        })
        loaded = presets.load("simple", str(self.tmp))
        self.assertEqual(loaded.segment_ids, ["start", "middle", "end"])
        self.assertEqual(loaded.segment("start").title, "Start")

    def test_a_broken_file_is_skipped_not_fatal(self):
        self.write("good", {"name": "good", "segments": ["a"], "target_minutes": 1})
        (self.tmp / "broken.json").write_text("{ this is not json", encoding="utf-8")
        loaded = presets.load_all(str(self.tmp))
        self.assertIn("good", loaded)
        self.assertNotIn("broken", loaded)

    def test_an_unknown_emotion_in_the_arc_is_rejected(self):
        self.write("bad", {
            "name": "bad",
            "segments": ["a"],
            "target_minutes": 1,
            "emotion_arc": ["happy", "hungry"],
        })
        with self.assertRaises(presets.PresetError) as caught:
            presets.load_all(str(self.tmp))
        self.assertIn("hungry", str(caught.exception))

    def test_a_preset_with_no_segments_is_rejected(self):
        self.write("empty", {"name": "empty", "segments": [], "target_minutes": 1})
        with self.assertRaises(presets.PresetError):
            presets.load_all(str(self.tmp))

    def test_duplicate_segment_ids_are_rejected(self):
        self.write("dupe", {
            "name": "dupe", "target_minutes": 1,
            "segments": ["a", "b", "a"],
        })
        with self.assertRaises(presets.PresetError):
            presets.load_all(str(self.tmp))

    def test_unknown_name_lists_the_alternatives(self):
        self.write("good", {"name": "good", "segments": ["a"], "target_minutes": 1})
        with self.assertRaises(presets.PresetError) as caught:
            presets.load("nope", str(self.tmp))
        self.assertIn("good", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
