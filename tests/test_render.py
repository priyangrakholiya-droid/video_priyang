"""Tests for the render step's ffmpeg command construction.

These build no video. They capture the argument lists the step would hand to
ffmpeg and assert their shape, which is where the version-dependent mistakes
live: an input declared and never mapped, or a path a concat list resolves
differently than you expected.
"""

import tempfile
import unittest
from pathlib import Path

from video_editor.project import Clip
from video_editor.steps import render


class FakeInfo:
    duration = 60.0
    width = 1920
    height = 1080
    fps = 30.0
    resolution = "1920x1080"

    def __init__(self, has_audio=True):
        self.has_audio = has_audio


class CaptureFFmpeg(unittest.TestCase):
    """Swap out the runner so nothing is executed."""

    def setUp(self):
        self.calls = []
        self._real_run = render._run
        self._real_probe = render.probe
        render._run = lambda cmd, what: self.calls.append((cmd, what))
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        render._run = self._real_run
        render.probe = self._real_probe
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class ConcatList(CaptureFFmpeg):
    """The bug that broke ffmpeg 8: relative paths in a concat list.

    A relative entry is resolved against the directory holding the LIST, so a
    project-relative path produced <work>/<work>/part.mp4. Bare names are
    correct on every version.
    """

    def test_parts_beside_the_list_are_written_as_bare_names(self):
        work = self.tmp / "ve_render_abc"
        work.mkdir()
        parts = []
        for i in (1, 2, 3):
            p = work / f"{i:04d}_c{i:03d}.mp4"
            p.write_bytes(b"x")
            parts.append(p)

        render._concat(parts, work / "out.mp4", work)
        listing = (work / "concat.txt").read_text(encoding="utf-8")

        self.assertEqual(
            listing.strip().splitlines(),
            ["file '0001_c001.mp4'", "file '0002_c002.mp4'", "file '0003_c003.mp4'"],
        )

    def test_no_entry_contains_a_directory_separator(self):
        work = self.tmp / "nested" / "deep" / "ve_render_abc"
        work.mkdir(parents=True)
        part = work / "0001_c001.mp4"
        part.write_bytes(b"x")

        render._concat([part], work / "out.mp4", work)
        for line in (work / "concat.txt").read_text(encoding="utf-8").splitlines():
            self.assertNotIn("/", line[len("file '"):], line)

    def test_the_work_directory_is_never_repeated_in_an_entry(self):
        work = self.tmp / "ve_render_xyz"
        work.mkdir()
        part = work / "0001_c001.mp4"
        part.write_bytes(b"x")

        render._concat([part], work / "out.mp4", work)
        listing = (work / "concat.txt").read_text(encoding="utf-8")
        self.assertEqual(listing.count("ve_render_xyz"), 0)

    def test_a_part_elsewhere_falls_back_to_an_absolute_path(self):
        work = self.tmp / "work"
        work.mkdir()
        outside = self.tmp / "elsewhere.mp4"
        outside.write_bytes(b"x")

        render._concat([outside], work / "out.mp4", work)
        line = (work / "concat.txt").read_text(encoding="utf-8").strip()
        self.assertIn(outside.resolve().as_posix(), line)

    def test_the_listing_is_handed_to_ffmpeg(self):
        work = self.tmp / "work"
        work.mkdir()
        part = work / "0001_c001.mp4"
        part.write_bytes(b"x")

        render._concat([part], work / "out.mp4", work)
        cmd, what = self.calls[0]
        self.assertIn("concat", cmd)
        self.assertIn(str(work / "concat.txt"), cmd)
        self.assertIn("-safe", cmd)
        self.assertEqual(cmd[cmd.index("-safe") + 1], "0")


class NormaliseCommand(CaptureFFmpeg):
    """A clip with audio must not declare the silent fallback input.

    Declaring an unused, unbounded lavfi input is tolerated by one ffmpeg
    release and rejected by the next.
    """

    def build(self, has_audio):
        """The argument list _normalise would run for such a clip."""
        self.calls.clear()  # so a test may build more than once
        source = self.tmp / "source.mp4"
        source.write_bytes(b"x")
        render.probe = lambda p, _h=has_audio: FakeInfo(_h)
        clip = Clip(
            id="c001", source=str(source), source_name="source.mp4",
            source_in=10.0, source_out=16.0,
        )
        render._normalise(
            clip, self.tmp / "out.mp4",
            width=1280, height=720, fps=30, crf=19, preset="veryfast",
        )
        return self.calls[-1][0]

    def inputs(self, cmd):
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]

    def maps(self, cmd):
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]

    def test_a_clip_with_audio_declares_one_input(self):
        cmd = self.build(has_audio=True)
        self.assertEqual(len(self.inputs(cmd)), 1)
        self.assertNotIn("anullsrc", " ".join(cmd))

    def test_a_clip_with_audio_maps_its_own_audio(self):
        self.assertIn("0:a:0", self.maps(self.build(has_audio=True)))

    def test_a_silent_clip_gets_the_silent_input(self):
        cmd = self.build(has_audio=False)
        inputs = self.inputs(cmd)
        self.assertEqual(len(inputs), 2)
        self.assertTrue(any("anullsrc" in i for i in inputs))
        self.assertIn("1:a:0", self.maps(cmd))

    def test_shortest_only_when_bounding_the_silence(self):
        # With real audio, -t bounds the output and -shortest would only risk
        # truncating it.
        self.assertNotIn("-shortest", self.build(has_audio=True))
        self.assertIn("-shortest", self.build(has_audio=False))

    def test_every_input_is_mapped(self):
        for has_audio in (True, False):
            cmd = self.build(has_audio=has_audio)
            declared = len(self.inputs(cmd))
            referenced = {"0"}
            for m in self.maps(cmd):
                if m.startswith("["):
                    continue
                referenced.add(m.split(":")[0])
            self.assertEqual(
                len(referenced), declared,
                f"has_audio={has_audio}: {declared} inputs, mapped {referenced}",
            )

    def test_the_clip_is_cut_from_its_own_in_point(self):
        cmd = self.build(has_audio=True)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "10.000")
        self.assertEqual(cmd[cmd.index("-t") + 1], "6.000")


class TargetFormat(unittest.TestCase):
    def setUp(self):
        self._real_probe = render.probe
        render.probe = lambda p: FakeInfo(True)

    def tearDown(self):
        render.probe = self._real_probe

    def clips(self):
        return [
            Clip(id="c001", source="/a.mp4", source_name="a.mp4",
                 source_in=0.0, source_out=5.0),
            Clip(id="c002", source="/a.mp4", source_name="a.mp4",
                 source_in=9.0, source_out=14.0),
        ]

    def test_explicit_size_wins(self):
        w, h, _ = render._target_format(None, self.clips(), "1280x720", None)
        self.assertEqual((w, h), (1280, 720))

    def test_odd_dimensions_are_made_even(self):
        # H.264 refuses an odd dimension.
        w, h, _ = render._target_format(None, self.clips(), "1281x721", None)
        self.assertEqual((w % 2, h % 2), (0, 0))

    def test_a_malformed_size_is_refused(self):
        with self.assertRaises(render.RenderError):
            render._target_format(None, self.clips(), "big", None)

    def test_explicit_fps_wins(self):
        *_, rate = render._target_format(None, self.clips(), None, 24.0)
        self.assertEqual(rate, 24.0)


if __name__ == "__main__":
    unittest.main()
