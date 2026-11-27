import unittest

from video_editor.timecode import (
    TimecodeError,
    format_duration,
    format_timecode,
    parse_minutes,
    parse_timecode,
)


class ParseTimecode(unittest.TestCase):
    def test_plain_seconds(self):
        self.assertEqual(parse_timecode("90"), 90.0)
        self.assertEqual(parse_timecode("0"), 0.0)
        self.assertAlmostEqual(parse_timecode("12.5"), 12.5)

    def test_minutes_and_seconds(self):
        self.assertEqual(parse_timecode("1:30"), 90.0)
        self.assertEqual(parse_timecode("10:00"), 600.0)

    def test_full_timecode(self):
        self.assertEqual(parse_timecode("00:01:30"), 90.0)
        self.assertAlmostEqual(parse_timecode("00:01:30.5"), 90.5)
        self.assertEqual(parse_timecode("01:00:00"), 3600.0)

    def test_unit_form(self):
        self.assertEqual(parse_timecode("1h2m3s"), 3723.0)
        self.assertEqual(parse_timecode("90s"), 90.0)
        self.assertEqual(parse_timecode("2m"), 120.0)

    def test_whitespace_is_forgiven(self):
        self.assertEqual(parse_timecode("  1:30 "), 90.0)

    def test_rejects_rubbish(self):
        for bad in ("", "   ", "abc", "1:2:3:4", "-5"):
            with self.subTest(bad=bad):
                with self.assertRaises(TimecodeError):
                    parse_timecode(bad)

    def test_rejects_out_of_range_parts(self):
        with self.assertRaises(TimecodeError):
            parse_timecode("00:99:00")
        with self.assertRaises(TimecodeError):
            parse_timecode("00:01:99")


class FormatTimecode(unittest.TestCase):
    def test_round_trip(self):
        for seconds in (0.0, 1.5, 90.5, 3723.25):
            with self.subTest(seconds=seconds):
                self.assertAlmostEqual(
                    parse_timecode(format_timecode(seconds)), seconds, places=3
                )

    def test_shape(self):
        self.assertEqual(format_timecode(90.5), "00:01:30.500")
        self.assertEqual(format_timecode(0), "00:00:00.000")

    def test_millisecond_carry(self):
        # 59.9999 must not format as :59.1000
        self.assertEqual(format_timecode(59.9999), "00:01:00.000")

    def test_negative_is_an_error(self):
        with self.assertRaises(ValueError):
            format_timecode(-1)


class FormatDuration(unittest.TestCase):
    def test_readable(self):
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(95), "1m 35s")
        self.assertEqual(format_duration(300), "5m 00s")


class ParseMinutes(unittest.TestCase):
    def test_minutes_to_seconds(self):
        self.assertEqual(parse_minutes("5"), 300.0)
        self.assertEqual(parse_minutes("2.5"), 150.0)
        self.assertEqual(parse_minutes("5m"), 300.0)

    def test_colon_form_means_time(self):
        self.assertEqual(parse_minutes("1:30"), 90.0)

    def test_rejects_zero_and_junk(self):
        for bad in ("0", "-3", "", "soon"):
            with self.subTest(bad=bad):
                with self.assertRaises(TimecodeError):
                    parse_minutes(bad)


if __name__ == "__main__":
    unittest.main()
