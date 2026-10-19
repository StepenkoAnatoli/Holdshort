<!-- Lineage: the shared pack proposal Item 2 describes, in the format of ../README.md; its two defects take the shapes calibration runs 1-3 graded (a rejection that breaks a "nothing rejects" promise, a bound skipped on an unexpected input) on a synthetic module, so that no host's code travels. -->

# Shared synthetic subject pack

Version 1 (`pack_version` "1" in `manifest.json`, pack name `shared-bounded-reader`). This is the kit's **shared
synthetic subject pack**: every host runs it, so its pin, fix and review cells compare across hosts (proposal Item 2;
onboarding requires it). The subject is synthetic on purpose: `src/bounded.py`, about sixty lines of standard-library
Python whose `read_bounded(chunks, limit)` promises that it "accepts any iterable whose items are bytes-like (bytes,
bytearray, memoryview) or str (encoded as UTF-8), never raises on such input, and never returns more than limit bytes",
with a chunk classifier (`chunk_kind`) and a joiner (`join_parts`). It resembles a real module in its shape only.

## The two defects

Both are S3; `manifest.json` holds their ground truth (`findings`) and the rules a review is graded by.

- **D-1** (S3, the rejection; present at `review0` only): `read_bounded` raises `TypeError` on a `memoryview` chunk,
  a bytes-like chunk its promise says it reads; the cause is in `chunk_kind`, which does not take a memoryview for a
  bytes-like chunk, so `read_bounded` treats it as unsupported.
- **D-2** (S3, the skipped bound; present at `review0` and `base0`): a stream holding `str` chunks makes `read_bounded`
  return more than `limit` bytes; the cause is in `read_bounded`, which appends an encoded `str` chunk without counting
  it against `limit`.

The pin and fix cases are D-2's, on `base0`, which does not carry D-1, so a fix candidate cannot stumble on it; the
review case is graded on both, on `review0`. The accepted fix of each is one or two lines, in the commit after its base.

## Files

- `manifest.json`: the pack manifest in the format of `../README.md`, with the three commit ids `make-repo.sh` builds
  and `source_hashes` of every other file here.
- `make-repo.sh`: builds the pack repository from the trees (below), with fixed identity, dates, messages and file
  modes, so the commit ids are the manifest's on every host; it exits 1 when they differ from the manifest beside it.
- `.gitattributes`: keeps every file here byte for byte as committed (a CRLF checkout would change the ids).
- `README.md`: this file.
- `trees/review/` (D-1 and D-2 present, commit `review0`), `trees/base/` (D-2 present, `base0`) and `trees/accepted/`
  (neither, `accepted0`), each the whole subject as a candidate's checkout holds it, never a nested repository:
  `SPEC.md` (the promise, the chunk kinds, the bound), `src/bounded.py`, `src/__init__.py`, `tests/test_bounded.py`
  (the shipped harness, 12 cases, green on every tree and naming nothing of either fix), `tests/run.py` (the runner:
  loads test files by path, exit 0 green, 1 red), `.gitignore` (bytecode caches); `trees/accepted/` also holds
  `tests/test_pin.py`, D-2's accepted two-row pin.

## How a host runs it

Python 3 is the only dependency: no `--link`, nothing to install.

1. **Build** the repository outside the kit's tree and outside the checkout root, for example beside the checkout
   root, and copy the manifest unchanged beside it:
   `bash tools/calibration/subject-pack/shared/make-repo.sh <pack dir>/repo` and
   `cp tools/calibration/subject-pack/shared/manifest.json <pack dir>/`. The script prints `review0`, `base0` and
   `accepted0` with their ids and checks them against the manifest. With the copy unchanged, `repository` stays
   `repo` and `subject_pack.manifest_sha256` is the same on every host; a host that builds the repository elsewhere
   writes that path into its copy's `repository`, and its protocol records the changed hash.
2. **Protocol and fill**: `subject_pack` names `shared-bounded-reader`, version `1`, kind `shared` and the manifest's
   hash; the run config's `host.pack_dir` is `<pack dir>`, and the protocol records the pack directory it was built in.
3. **Checkouts**: `bash tools/calibration/historyless-checkout.sh --pack <pack dir> <pack dir>/repo <case base>
   <checkout> <branch>` with the case's base from `manifest.json`, every checkout outside the kit's tree as well as the
   pack directory (`trees/accepted/` holds the accepted fix). The guards cover the pack directory only:
   `historyless-checkout.sh --pack` and the launch refusal of `run.template.js` compare each path with `pack_dir`,
   never with this directory in the kit, so a checkout root inside the kit's `trees/` passes both. The host checks the
   kit's path itself: no checkout root, adjudication checkout or checkout is the kit's checkout, inside it, or holds it.
4. **Grade**: `bash tools/calibration/grade.sh <pack dir>/manifest.json pin|fix <checkout>`; the run grades the review
   cells. The kit's own test runs exactly this on the accepted pin and fix (PASS) and on wrong ones (FAIL).

## What it does not discriminate

It discriminates the bounded T1 shape only: one small module, one function and two helpers, defects of one or two
lines each, a stated promise and a shipped harness. It says nothing about work across modules, tests that need
fixtures or services, design judgement, or tasks of tier T2 and above; a host that needs those qualified runs its own
host pack on its own code.

## When it is rewritten

When it leaks (a candidate names D-1 or D-2, or writes the accepted fix, without reproducing the defect; the pack's text
turns up in a model's output) and whenever the kit's pack format changes. A rewrite is a new `pack_version`, with new
trees and so new commit ids; the trees of a released version are never edited in place, because earlier protocols name
its ids and its manifest hash. Cells on different versions do not compare.
