# Claude Code calibration run 3 — preregistered protocol

Status: **preregistered; launched after this file was committed** (the run id is added once the host assigns it).
Results come later as `observations.json`, `scores.json` and `results-table.md`; nothing here is a result.

Run 3 keeps the method of runs 1 and 2 and changes what their limits named:

1. **History-less checkouts.** Each candidate works in a fresh repository whose single root commit is the tree of the
   base revision (`historyless-checkout.sh`), so the accepted fix is not an object the candidate's git could reach.
2. **A defined classification.** The grader's "true" for an other finding needs three things: the behaviour holds at
   HEAD, it is reachable through the module's public API with input its contract admits, and the spec or the module's
   promise forbids it. A contract hole no admissible input reaches is at most S4.
3. **A preregistered adjudication.** The other S1-S3 findings of every review are clustered by mechanism, each cluster
   is judged by three independent lenses (reproduce, reachability, refute), and the adjudicated verdict is the scored
   one for false blocking findings. Run 2 did this post hoc; here it is part of the protocol.

Subject: the GitHub OAuth wire module of MoonAliza, whose contract (nothing rejects; no result carries GitHub's text) and
API (an injected fetcher may hand back any Response) make reachability well defined. Review at `0e7a7f3` (U1-R8 and
U1-R11 present); pin and fix at `e68583c` against the accepted fix `348aa2d`.

Files: `protocol.json` (the frozen protocol with source hashes), `grade.sh` and `historyless-checkout.sh` (byte-identical
copies of the host's scripts; host-local paths inside).
