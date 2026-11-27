import unittest

from video_editor.probe import hash_distance
from video_editor.project import Clip
from video_editor.steps.arrange import (
    arrange_by_emotion,
    chain_by_match,
    join_cost,
)


def make_clip(clip_id, head, tail, **kwargs):
    return Clip(
        id=clip_id,
        source="x.mp4",
        source_name="x.mp4",
        source_in=0.0,
        source_out=2.0,
        head_hash=head,
        tail_hash=tail,
        **kwargs,
    )


class HashDistance(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(hash_distance(0b1011, 0b1011), 0)

    def test_counts_differing_bits(self):
        self.assertEqual(hash_distance(0b0000, 0b1011), 3)

    def test_symmetric(self):
        self.assertEqual(hash_distance(123456, 654321), hash_distance(654321, 123456))


class JoinCost(unittest.TestCase):
    def test_matching_frames_cost_nothing(self):
        a = make_clip("a", head=0, tail=0b1111)
        b = make_clip("b", head=0b1111, tail=0)
        self.assertEqual(join_cost(a, b), 0)

    def test_missing_hashes_fall_back_to_average(self):
        a = make_clip("a", head=0, tail=None)
        b = make_clip("b", head=0b1111, tail=0)
        self.assertEqual(join_cost(a, b), 32)


class ChainByMatch(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertEqual(chain_by_match([]), [])
        one = [make_clip("a", 1, 2)]
        self.assertEqual([c.id for c in chain_by_match(one)], ["a"])

    def test_chains_on_matching_edges(self):
        # a ends on 0b0011 -> b starts on 0b0011 -> b ends 0b1100 -> c starts 0b1100
        a = make_clip("a", head=0b0000, tail=0b0011)
        b = make_clip("b", head=0b0011, tail=0b1100)
        c = make_clip("c", head=0b1100, tail=0b0000)
        chain = chain_by_match([c, a, b], first=a)
        self.assertEqual([x.id for x in chain], ["a", "b", "c"])

    def test_respects_an_explicit_opener(self):
        a = make_clip("a", head=0b0000, tail=0b0011)
        b = make_clip("b", head=0b0011, tail=0b1100)
        chain = chain_by_match([a, b], first=b)
        self.assertEqual(chain[0].id, "b")

    def test_every_clip_appears_exactly_once(self):
        clips = [make_clip(f"c{i}", head=i * 7, tail=i * 13) for i in range(8)]
        chain = chain_by_match(clips)
        self.assertEqual(len(chain), 8)
        self.assertEqual({c.id for c in chain}, {c.id for c in clips})

    def test_a_smooth_chain_beats_the_input_order(self):
        # Deliberately shuffled, with clean pairings available.
        clips = [
            make_clip("one", head=0b0000_0000, tail=0b1111_0000),
            make_clip("two", head=0b1111_0000, tail=0b0000_1111),
            make_clip("three", head=0b0000_1111, tail=0b1010_1010),
        ]
        shuffled = [clips[2], clips[0], clips[1]]
        chain = chain_by_match(shuffled)
        costs = [join_cost(chain[i - 1], chain[i]) for i in range(1, len(chain))]
        original = [join_cost(shuffled[i - 1], shuffled[i]) for i in range(1, 3)]
        self.assertLessEqual(sum(costs), sum(original))


class FakeProject:
    """Just enough project for arrange_by_emotion: it only needs the arc."""

    def __init__(self, arc):
        self.emotion_arc = list(arc)


class ArrangeByEmotion(unittest.TestCase):
    ARC = ["calm", "happy", "fun", "romantic", "ritual", "emotional"]

    def test_follows_the_arc(self):
        clips = [
            make_clip("sad", 1, 2, emotion="emotional"),
            make_clip("quiet", 3, 4, emotion="calm"),
            make_clip("party", 5, 6, emotion="fun"),
        ]
        order = [c.emotion for c in arrange_by_emotion(FakeProject(self.ARC), clips)]
        self.assertEqual(order, ["calm", "fun", "emotional"])

    def test_a_different_preset_gives_a_different_order(self):
        # The arc is preset data, so a preset that ends on fun must order
        # these the other way round.
        clips = [
            make_clip("party", 5, 6, emotion="fun"),
            make_clip("sad", 1, 2, emotion="emotional"),
        ]
        arc = ["calm", "emotional", "fun"]
        order = [c.emotion for c in arrange_by_emotion(FakeProject(arc), clips)]
        self.assertEqual(order, ["emotional", "fun"])

    def test_unscored_clips_go_last(self):
        clips = [
            make_clip("none", 1, 2),
            make_clip("happy", 3, 4, emotion="happy"),
        ]
        chain = arrange_by_emotion(FakeProject(self.ARC), clips)
        self.assertEqual([c.id for c in chain], ["happy", "none"])


if __name__ == "__main__":
    unittest.main()
