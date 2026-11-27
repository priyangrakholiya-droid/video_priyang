import shutil
import tempfile
import unittest
from pathlib import Path

from video_editor.project import (
    EMOTIONS,
    PRESETS,
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

    def test_create_lays_out_every_folder(self):
        project = self.make()
        for step in ("source", "selected", "arranged", "music", "emotion", "final"):
            self.assertTrue(project.dir(step).is_dir(), step)
        for emotion in EMOTIONS:
            self.assertTrue((project.dir("emotion") / emotion).is_dir(), emotion)
        for segment in PRESETS["marriage"]:
            self.assertTrue((project.dir("selected") / segment).is_dir(), segment)

    def test_create_refuses_to_overwrite(self):
        self.make()
        with self.assertRaises(ProjectError):
            self.make()

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ProjectError):
            self.make(preset="birthday-party")

    def test_save_and_load_round_trip(self):
        project = self.make()
        project.clips = [
            Clip(
                id="c001",
                source="/footage/a.mp4",
                source_name="a.mp4",
                source_in=1.0,
                source_out=5.0,
                segment="haldi",
            )
        ]
        project.mark_done("select")
        project.save()

        reloaded = Project.load(self.root)
        self.assertEqual(reloaded.name, "Test Wedding")
        self.assertEqual(reloaded.preset, "marriage")
        self.assertEqual(reloaded.target_duration, 300.0)
        self.assertTrue(reloaded.is_done("select"))
        self.assertFalse(reloaded.is_done("render"))
        self.assertEqual(len(reloaded.clips), 1)
        self.assertEqual(reloaded.clips[0].duration, 4.0)

    def test_load_without_manifest_is_an_error(self):
        with self.assertRaises(ProjectError):
            Project.load(self.tmp / "nope")

    def test_ids_do_not_collide(self):
        project = self.make()
        ids = []
        clips = []
        for _ in range(3):
            project.clips = clips
            new_id = project.next_clip_id()
            ids.append(new_id)
            clips.append(
                Clip(id=new_id, source="x", source_name="x", source_in=0, source_out=1)
            )
        self.assertEqual(ids, ["c001", "c002", "c003"])

    def test_ordered_clips_puts_unarranged_last(self):
        project = self.make()
        project.clips = [
            Clip(id="c001", source="x", source_name="x", source_in=0, source_out=1),
            Clip(id="c002", source="x", source_name="x", source_in=0, source_out=1, order=2),
            Clip(id="c003", source="x", source_name="x", source_in=0, source_out=1, order=1),
        ]
        self.assertEqual([c.id for c in project.ordered_clips()], ["c003", "c002", "c001"])

    def test_render_duration_prefers_the_beat_snapped_length(self):
        clip = Clip(
            id="c001", source="x", source_name="x", source_in=0.0, source_out=5.0
        )
        self.assertEqual(clip.render_duration, 5.0)
        clip.beat_duration = 5.96
        self.assertEqual(clip.render_duration, 5.96)

    def test_durations_never_go_negative(self):
        clip = Clip(
            id="c001", source="x", source_name="x", source_in=9.0, source_out=4.0
        )
        self.assertEqual(clip.duration, 0.0)


if __name__ == "__main__":
    unittest.main()
