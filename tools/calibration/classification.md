<!-- Lineage: generalises calibration run 3's classification (the CLASSIFICATION text of its workflow script and the
protocol's changes_from_run_2), with the rules runs 2 and 3 produced (G-1, G-2) written as rules. -->

# Classification of an other finding

A review cell is graded against the pack's ground truth (the findings the manifest lists). Every **other** finding the
reviewer raises at S1, S2 or S3 is classified by the grader, then clustered by mechanism and adjudicated by three
lenses. This file is the definition all three apply. The `## Definition` section is inserted verbatim into the grader
and lens prompts as `{{classification}}`; the protocol records its prongs in `classification.prongs`.

## Definition

Classification of an OTHER S1-S3 finding: 'true' = (1) the code at HEAD behaves as the finding says - it holds at HEAD
(reproduce it: read the cited lines, run its scratch test or your own) AND (2) the behaviour is reachable through the
module's public API with input its contract admits (any input the module's stated API lets a caller hand it is
admissible; a path that needs editing the module itself, or a caller the specification does not define, is not) AND
(3) the specification or the module's stated promise forbids the behaviour. 'false' = any of the three fails: the claim
does not hold, or its test does not show what it says, or no admissible input reaches it, or the specification permits
it. 'unverifiable' = the material at hand cannot settle it (say what was missing). A contract hole that no admissible
input reaches is at most S4 and never a blocking finding. Fill 'mechanism' with a short canonical phrase for the
defect's mechanism and location (file:function, the condition), so recurring claims across reviewers can be clustered.

## The three prongs

| prong | question | lens field | votes real when |
|-------|----------|------------|-----------------|
| holds | does the code at HEAD behave as the finding says? | `holds` | `true` |
| reachable | does admissible input reach it through the public API? | `reachable` | not `"no"` (`"unclear"` does not refute) |
| forbidden | does the specification or the module's promise forbid it? | `forbidden` | `true` |

A lens votes real only when all three hold; a cluster is real on two votes of three. The adjudicated verdict is the
scored one: a cluster found real clears every member the grader called false; a cluster found not real makes every
S1-S3 member a false blocking finding.

## Severity and the S4 rule

S1 security or data loss; S2 wrong behaviour against the specification that the shipped tests miss; S3 a specification
gap, a rejection where a result is promised, or a wrong test; S4 a nit. A finding that fails prong 2 - a contract hole
no admissible input reaches - is at most S4, whatever severity the reviewer gave it, and is never blocking. A finding
without a reproduction the reviewer actually ran is not a finding: it belongs in the review's `checked` list.

## Rules the runs produced

**G-1 (run 2): the grader's question is defined, never "is this a real problem?".** Run 2 asked its grader whether an
other finding was "true" without defining the word; graders read it as "a real problem" and disagreed on contract holes
nobody could reach. Rule: the grader classifies by the three prongs of the Definition above, and the prompt carries the
Definition verbatim. A change to the Definition is a protocol amendment, recorded before the run that uses it.

**G-2 (run 3): the lens schema carries every prong of the classification.** Run 3's lens schema had `holds` and
`reachable` only, and its vote rule read a lens as real on those two; two clusters were adjudicated real while the
lenses' own prose said the specification permitted the behaviour. Rule: the lens output schema carries `forbidden`, a
lens votes real only on all three prongs, and the prongs the protocol declares (`classification.prongs`) equal the
prongs the lens schema carried (`scores.json` `adjudication_schema`). A review PASS that holds only because a prong was
missing is recorded as `would_fail_under_three_prong: true` beside the preregistered score, and is not an ordinary PASS.
