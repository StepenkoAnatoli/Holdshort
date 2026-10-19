"""Bounded reading of a stream of chunks.

read_bounded accepts any iterable whose items are bytes-like (bytes, bytearray,
memoryview) or str (encoded as UTF-8), never raises on such input, and never
returns more than limit bytes.

SPEC.md is the specification; tests/test_bounded.py is the harness.
"""

BINARY = "binary"
TEXT = "text"

__all__ = ["BINARY", "TEXT", "chunk_kind", "join_parts", "read_bounded"]


def chunk_kind(chunk):
    """Classify one chunk.

    Returns BINARY for a bytes-like chunk, TEXT for a str chunk and None for
    anything else (a chunk the promise does not cover).
    """
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return BINARY
    if isinstance(chunk, str):
        return TEXT
    return None


def join_parts(parts):
    """Join the pieces taken from the chunks, in order, into one bytes object."""
    return b"".join(parts)


def read_bounded(chunks, limit):
    """Read chunks in order and return at most limit bytes of them, joined.

    chunks: an iterable of chunks (see chunk_kind). A str chunk is encoded as
    UTF-8, a character UTF-8 cannot encode (a lone surrogate) becoming b"?",
    and its bytes count like any other chunk's.
    limit: an int; a negative limit reads as 0.

    Reading stops as soon as limit bytes are taken, so the iterable may be
    endless provided it yields that many bytes. A chunk of any other kind is
    outside the promise and raises TypeError.
    """
    limit = max(0, limit)
    parts = []
    taken = 0
    for chunk in chunks:
        kind = chunk_kind(chunk)
        if kind is None:
            raise TypeError(f"read_bounded: unsupported chunk type {type(chunk).__name__}")
        if kind == TEXT:
            parts.append(chunk.encode("utf-8", "replace"))
            continue
        piece = bytes(chunk)[:limit - taken]
        parts.append(piece)
        taken += len(piece)
        if taken >= limit:
            break
    return join_parts(parts)
