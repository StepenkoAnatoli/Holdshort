"""The harness of src/bounded.py (SPEC.md). Run: python3 tests/run.py tests/test_bounded.py"""
import itertools
import unittest

from src.bounded import BINARY, TEXT, chunk_kind, join_parts, read_bounded


class ChunkKind(unittest.TestCase):
    def test_bytes_and_bytearray_are_binary_and_str_is_text(self):
        self.assertEqual(chunk_kind(b"ab"), BINARY)
        self.assertEqual(chunk_kind(bytearray(b"ab")), BINARY)
        self.assertEqual(chunk_kind("ab"), TEXT)

    def test_anything_else_has_no_kind(self):
        for other in (3, None, [b"a"], 1.5):
            self.assertIsNone(chunk_kind(other), repr(other))


class JoinParts(unittest.TestCase):
    def test_joins_in_order(self):
        self.assertEqual(join_parts([b"a", b"", b"bc"]), b"abc")
        self.assertEqual(join_parts([]), b"")


class ReadBounded(unittest.TestCase):
    def test_bytes_under_the_limit_come_back_whole(self):
        self.assertEqual(read_bounded([b"ab", b"cd"], 10), b"abcd")

    def test_bytes_are_cut_at_the_limit(self):
        self.assertEqual(read_bounded([b"abc", b"def"], 4), b"abcd")

    def test_bytearray_chunks(self):
        self.assertEqual(read_bounded([bytearray(b"xy"), b"z"], 3), b"xyz")

    def test_an_empty_iterable_reads_nothing(self):
        self.assertEqual(read_bounded([], 5), b"")

    def test_a_zero_or_negative_limit_reads_nothing(self):
        self.assertEqual(read_bounded([b"abc"], 0), b"")
        self.assertEqual(read_bounded([b"abc"], -5), b"")

    def test_reading_stops_at_the_limit_on_an_endless_iterable(self):
        self.assertEqual(read_bounded((b"ab" for _ in itertools.count()), 5), b"ababa")

    def test_a_text_chunk_is_read_as_utf8(self):
        self.assertEqual(read_bounded(["héllo"], 16), "héllo".encode("utf-8"))

    def test_a_lone_surrogate_reads_as_a_question_mark(self):
        self.assertEqual(read_bounded(["a\ud800"], 8), b"a?")

    def test_a_chunk_outside_the_promise_raises_type_error(self):
        with self.assertRaises(TypeError):
            read_bounded([b"a", 3], 10)
