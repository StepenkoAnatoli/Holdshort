"""D-2's pin: a str chunk's UTF-8 bytes count against limit like any other chunk's, and once limit bytes are taken
read_bounded reads no further chunk.

The first row cuts a text chunk inside the UTF-8 bytes of a non-ASCII character: limit 2 falls between the two bytes
of "é", so the result ends with the first of them. The second reads a stream of two text chunks that fails if it is
pulled once more: the second chunk is cut after the first's bytes were taken (two of its three fit, so the cut is at
the room left, not at the limit), the limit is reached, and read_bounded never pulls again.
"""
import unittest

from src.bounded import read_bounded


def texts_then_no_more(*texts):
    """The texts in order, then an AssertionError on the next pull."""
    yield from texts
    raise AssertionError("read_bounded pulled a chunk after limit bytes were taken")


class TextCountsAgainstTheLimit(unittest.TestCase):
    def test_rows(self):
        rows = [
            ("héllo", ["héllo"], 2, b"h\xc3"),
            ("ab, cde, then no more", texts_then_no_more("ab", "cde"), 4, b"abcd"),
        ]
        for name, chunks, limit, want in rows:
            with self.subTest(chunks=name, limit=limit):
                got = read_bounded(chunks, limit)
                self.assertLessEqual(len(got), limit)
                self.assertEqual(got, want)
