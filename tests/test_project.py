import json
import shutil
import tempfile
import unittest
from pathlib import Path

from video_editor.presets import EMOTIONS
from video_editor.project import (
    SCHEMA,
    STEP_DIRS,
    Clip,
    Project,
    ProjectError,
    slugify,
)


class Slugify(unittest.TestCase):
    def test_makes_safe_folder_names(self):
        self.assertEqual(slugify("Priya & Rahul Engagement!"), "priya-rahul-engagement")
        self.assertEqual(slugify("  spaces   here  "), "spaces-here")
        self.assertEqual(slugify("///"), "project")
        self.assertEqual(slugify(""), "project")


class ClipMaths(unittest.TestCase):
    def make(self, **kwargs):
        defaults = dict(
            id="c001", source="/footage/a.mp4", source_name="a.mp4",
            source_in=10.0, source_out=18.0,
        )
        defaults.update(kwargs)
        return Clip(**defaults)

    def test_duration(self):
        self.assertEqual(self.make().duration, 8.0)

    def test_never_negative(self):
        self.assertEqual(self.make(source_in=9.0, source_out=4.0).duration, 0.0)

    def test_render_duration_prefers_the_beat_snapped_length(self):
        clip = self.make()
        self.assertEqual(clip.render_duration, 8.0)
        clip.beat_duration = 7.5
        self.assertEqual(clip.render_duration, 7.5)

    def test_render_out_follows_the_snapped_length(self):
        clip = self.make()
        self.assertEqual(clip.render_out, 18.0)
        clip.beat_duration = 6.0
        self.assertEqual(clip.render_out, 16.0)

    def test_a_clip_holds_no_file_path(self):
        # Schema 2: a clip is a reference, never a copy. Nothing on this
        # object may point at an extracted piece of video.
        self.assertFalse(hasattr(self.make(), "file"))


class ProjectLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "proj"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, **kwargs):
        defaults = dict(name="Test Wedding", preset="marriage", target_duration=300.0)
        defaults.update(kwargs)
        return Project.create(self.root, **defaults)

    def test_create_lays_out_the_step_folders(self):
        project = self.make()
        for step in STEP_DIRS:
            self.assertTrue(project.dir(step).is_dir(), step)

    def test_create_makes_no_media_folders(self):
        # There must be nowhere for footage to be copied to.
        project = self.make()
        names = {p.name for p in project.root.iterdir() if p.is_dir()}
        self.assertEqual(names, set(STEP_DIRS.values()))

    def test_create_refuses_to_overwrite(self):
        self.make()
        with self.assertRaises(ProjectError):
            self.make()

    def test_unknown_preset_is_rejected(self):
        from video_editor.presets import PresetError

        with self.assertRaises(PresetError):
            self.make(preset="definitely-not-an-event")

    def test_preset_supplies_the_target_when_none_is_given(self):
        project = Project.create(self.root, name="X", preset="party")
        self.assertEqual(project.target_duration, 180.0)  # party = 3 minutes

    def test_save_and_load_round_trip(self):
        project = self.make()
        project.clips = [
            Clip(
                id="c001", source="/footage/a.mp4", source_name="a.mp4",
                source_in=1.0, source_out=5.0, segment="haldi", origin="auto",
                score=0.8,
            )
        ]
        project.mark_done("select")
        project.save()

        reloaded = Project.load(self.root)
        self.assertEqual(reloaded.name, "Test Wedding")
        self.assertEqual(reloaded.preset_name, "marriage")
        self.assertEqual(reloaded.target_duration, 300.0)
        self.assertTrue(reloaded.is_done("select"))
        self.assertFalse(reloaded.is_done("render"))
        self.assertEqual(len(reloaded.clips), 1)
        self.assertEqual(reloaded.clips[0].duration, 4.0)
        self.assertEqual(reloaded.clips[0].origin, "auto")

    def test_load_without_manifest_is_an_error(self):
        with self.assertRaises(ProjectError):
            Project.load(self.tmp / "nope")

    def test_saving_clips_writes_the_edit_plan(self):
        project = self.make()
        project.clips = [
            Clip(id="c001", source="/a.mp4", source_name="a.mp4",
                 source_in=0.0, source_out=4.0, order=1)
        ]
        project.save()
        plan_file = project.root / "edit.json"
        self.assertTrue(plan_file.is_file())
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        self.assertEqual(plan["clips"][0]["id"], "c001")
        self.assertEqual(plan["clips"][0]["starts_at"], 0.0)

    def test_edit_plan_lays_clips_end_to_end(self):
        project = self.make()
        project.clips = [
            Clip(id="c001", source="/a.mp4", source_name="a.mp4",
                 source_in=0.0, source_out=4.0, order=1),
            Clip(id="c002", source="/a.mp4", source_name="a.mp4",
                 source_in=20.0, source_out=26.0, order=2),
        ]
        plan = project.edit_plan()
        self.assertEqual([c["starts_at"] for c in plan["clips"]], [0.0, 4.0])
        self.assertEqual(plan["runtime"], 10.0)

    def test_ids_do_not_collide(self):
        project = self.make()
        clips = []
        for _ in range(3):
            clips.append(
                Clip(id=project.next_clip_id(clips), source="x", source_name="x",
                     source_in=0, source_out=1)
            )
        self.assertEqual([c.id for c in clips], ["c001", "c002", "c003"])

    def test_ordered_clips_puts_unarranged_last(self):
        project = self.make()
        project.clips = [
            Clip(id="c001", source="x", source_name="x", source_in=0, source_out=1),
            Clip(id="c002", source="x", source_name="x", source_in=0, source_out=1, order=2),
            Clip(id="c003", source="x", source_name="x", source_in=0, source_out=1, order=1),
        ]
        self.assertEqual(
            [c.id for c in project.ordered_clips()], ["c003", "c002", "c001"]
        )

    def test_next_step_walks_the_pipeline(self):
        project = self.make()
        self.assertEqual(project.next_step(), "select")
        project.mark_done("select")
        project.mark_done("arrange")
        self.assertEqual(project.next_step(), "music")

    def test_summary_is_json_serialisable(self):
        project = self.make()
        project.clips = [
            Clip(id="c001", source="x", source_name="x", source_in=0, source_out=3,
                 order=1, segment="haldi", emotion="fun")
        ]
        summary = project.summary()
        json.dumps(summary)  # must not raise
        self.assertEqual(summary["clips"], 1)
        self.assertEqual(summary["by_emotion"], {"fun": 1})
        self.assertEqual(summary["by_segment"], {"haldi": 1})

    def test_emotion_arc_comes_from_the_preset(self):
        project = Project.create(self.root, name="X", preset="baby_shower")
        self.assertEqual(
            project.emotion_arc, ["calm", "happy", "fun", "romantic", "emotional"]
        )
        for mood in project.emotion_arc:
            self.assertIn(mood, EMOTIONS)


class SchemaMigration(unittest.TestCase):
    """A schema 1 project must still open, minus its copied-clip fields."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "old"
        self.root.mkdir(parents=True)
        legacy = {
            "schema": 1,
            "name": "Old Project",
            "slug": "old-project",
            "preset": "marriage",
            "segments": ["haldi", "pheras"],
            "target_duration": 300.0,
            "sources": ["/footage/a.mp4"],
            "clips": [
                {
                    "id": "c001",
                    "source": "/footage/a.mp4",
                    "source_name": "a.mp4",
                    "source_in": 5.0,
                    "source_out": 12.0,
                    "file": "02_selected/haldi/c001_clip.mp4",
                    "label": "old clip",
                    "order": 1,
                    "segment": "haldi",
                    "emotion": "fun",
                    "emotion_scores": {},
                    "beat_duration": None,
                    "head_hash": None,
                    "tail_hash": None,
                    "notes": "",
                }
            ],
            "music": {},
            "final": {"file": "06_final/old.mp4"},
            "steps_done": ["select", "arrange"],
        }
        (self.root / "project.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_opens_and_upgrades(self):
        project = Project.load(self.root)
        self.assertEqual(project.data["schema"], SCHEMA)
        self.assertEqual(len(project.clips), 1)
        clip = project.clips[0]
        self.assertEqual(clip.duration, 7.0)
        self.assertEqual(clip.segment, "haldi")
        self.assertEqual(clip.origin, "manual")

    def test_the_copied_file_field_is_dropped(self):
        project = Project.load(self.root)
        self.assertNotIn("file", project.data["clips"][0])

    def test_the_old_final_block_becomes_output(self):
        project = Project.load(self.root)
        self.assertEqual(project.data["output"]["file"], "06_final/old.mp4")

    def test_a_newer_schema_is_refused(self):
        (self.root / "project.json").write_text(
            json.dumps({"schema": 99, "name": "future"}), encoding="utf-8"
        )
        with self.assertRaises(ProjectError):
            Project.load(self.root)


if __name__ == "__main__":
    unittest.main()
