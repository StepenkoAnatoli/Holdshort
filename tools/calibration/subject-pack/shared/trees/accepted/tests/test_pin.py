"""D-2's pin: a str chunk's UTF-8 bytes count against limit like any other chunk's."""
import unittest

from src.bounded import read_bounded


class TextCountsAgainstTheLimit(unittest.TestCase):
    ROWS = [
        (["abc", "def"], 4, b"abcd"),
        ([b"ab", "cdé", b"f"], 4, b"abcd"),
    ]

    def test_rows(self):
        for chunks, limit, want in self.ROWS:
            with self.subTest(chunks=chunks, limit=limit):
                got = read_bounded(chunks, limit)
                self.assertLessEqual(len(got), limit)
                self.assertEqual(got, want)
