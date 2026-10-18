"""D-2's pin: a str chunk's UTF-8 bytes count against limit like any other chunk's, and once limit bytes are taken
read_bounded reads no further chunk.

The first row cuts a text chunk inside the UTF-8 bytes of a non-ASCII character: limit 2 falls between the two bytes
of "é", so the result ends with the first of them. The second ends with 3, a chunk read_bounded would reject: it is
never read, because the two text chunks before it already reach the limit.
"""
import unittest

from src.bounded import read_bounded


class TextCountsAgainstTheLimit(unittest.TestCase):
    ROWS = [
        (["héllo"], 2, b"h\xc3"),
        (["ab", "cd", 3], 4, b"abcd"),
    ]

    def test_rows(self):
        for chunks, limit, want in self.ROWS:
            with self.subTest(chunks=chunks, limit=limit):
                got = read_bounded(chunks, limit)
                self.assertLessEqual(len(got), limit)
                self.assertEqual(got, want)
