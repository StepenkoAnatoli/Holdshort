# Bounded reader: specification

`src/bounded.py` reads a stream of chunks into one bytes object of bounded size.

## The promise

`read_bounded(chunks, limit)` accepts any iterable whose items are bytes-like (`bytes`, `bytearray`, `memoryview`) or
`str` (encoded as UTF-8), never raises on such input, and never returns more than `limit` bytes. `limit` is an int; a
negative limit reads as 0. The result is the chunks' bytes in order, cut at `limit`.

## Chunk kinds

`chunk_kind(chunk)` classifies one chunk:

- **binary**: a `bytes`, `bytearray` or `memoryview` chunk; its bytes are read as they are. A `memoryview` that has
  been released holds no bytes to read and is outside the promise.
- **text**: a `str` chunk; it is encoded as UTF-8, and a character UTF-8 cannot encode (a lone surrogate) becomes `?`.
- **none**: anything else (an int, `None`, a list). Such a chunk is outside the promise: `read_bounded` raises
  `TypeError` on it. A `bytes` object passed as `chunks` itself iterates as ints, so it is not an iterable of chunks.

`join_parts(parts)` joins the pieces taken from the chunks, in order.

## The bound

Every chunk's bytes count against `limit`, whatever its kind: a text chunk counts by its UTF-8 bytes, and a cut may
fall inside a character. Once `limit` bytes are taken, `read_bounded` reads no further chunk, so an endless
iterable is fine as long as it yields `limit` bytes; with a limit of 0 it reads the first chunk and takes none
of it.
