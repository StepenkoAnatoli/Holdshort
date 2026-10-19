<!-- Lineage: generalises calibration run 3's adjudication lens prompt and LENS schema (its workflow script), with the
`forbidden` prong added to the schema and to the vote (amendment G-2) and the subject as placeholders. -->

# Lens prompt (three per cluster)

Each cluster of other S1-S3 findings is judged by three independent lenses - reproduce, reachability, refute - on the
judging profile, in one shared history-less checkout of the review base (not a candidate's checkout). `run.template.js`
fills the placeholders, puts the lens's own `## Lens:` section in `{{lens_instruction}}`, and combines the three
verdicts by the vote rule below; `observations.py` recomputes the vote from the lens records.

## Prompt

ADJUDICATION of one review claim for a model-routing calibration (raised by one or more reviewers of {{module}}; your
verdict is one of three independent lenses, combined by majority). Work ONLY inside {{adjudication_checkout}} (a
history-less checkout of the tree under review; read-only except the one file you may create, {{scratch_file}}, left
uncommitted; never modify the source, the docs or an existing test; other adjudicators share this checkout
concurrently). Reference material as the reviewers had it: {{reference}}. Run one test file with
`cd {{adjudication_checkout}} && {{test_command}} <file>`. THE CLAIM ({{cluster_id}}: {{cluster_title}}): {{claim}}
Raised by: {{members}}; the per-candidate graders classified it: {{grader_classifications}}. Apply the run's
definition: {{classification}} {{lens_instruction}} Return: claim (the cluster id), lens, holds, reachable
('yes'|'no'|'unclear'), forbidden (true when the specification or the module's stated promise forbids the behaviour;
false when it permits it or you cannot name the rule that forbids it), severity (your own S1..S4 or 'none'),
scratchTest (the file and its decisive assertion, or ''), why (4-8 lines, concrete, file:line, naming the rule that
forbids or permits the behaviour).

## Lens: reproduce

YOUR LENS: REPRODUCE. Write and run a scratch test that drives the real functions through the module's public API with
admissible input and settles every call; holds = the behaviour the claim describes was observed; set reachable by
whether your test needed anything beyond admissible input; set forbidden by the rule the behaviour breaks, if any.

## Lens: reachability

YOUR LENS: REACHABILITY. Do not write a test unless reading cannot settle it. Trace which admissible input reaches the
state and which rule of the specification or the promise forbids the result, or name the barrier; holds = the code
reads as the claim says.

## Lens: refute

YOUR LENS: REFUTE. Assume the claim is WRONG and try to refute it from the code and the specification (a scratch test is
allowed when it is the fastest way): refuted when the code does not behave as stated, the specification permits it, or
no admissible input reaches it; default to holds=false if you cannot settle it.

## Vote rule

a lens votes real only when holds is true, reachable is not no, and forbidden is true; a cluster is real on two votes
of three. A lens that returned nothing is not a vote.

## Output schema

```json
{
  "type": "object",
  "properties": {
    "claim": {"type": "string"},
    "lens": {"type": "string"},
    "holds": {"type": "boolean"},
    "reachable": {"type": "string", "enum": ["yes", "no", "unclear"]},
    "forbidden": {"type": "boolean"},
    "severity": {"type": "string"},
    "scratchTest": {"type": "string"},
    "why": {"type": "string"}
  },
  "required": ["claim", "lens", "holds", "reachable", "forbidden", "severity", "scratchTest", "why"]
}
```

## Placeholders

- `{{module}}` the subject module's path in the pack (manifest `subject.module`)
- `{{adjudication_checkout}}` the shared history-less checkout of the review base the host made for the lenses
- `{{scratch_file}}` the one file this lens may create, named after the cluster and the lens (in the pack's test layout)
- `{{reference}}` the reference material the reviewers had (manifest `subject.reference`)
- `{{test_command}}` how to run one test file (manifest `commands.test` with `{files}` left for the file)
- `{{cluster_id}}` the cluster's id, as the clustering agent wrote it
- `{{cluster_title}}` its title
- `{{claim}}` its claim
- `{{members}}` the cluster's members, `<profile> <finding id>`
- `{{grader_classifications}}` the graders' classification of each member, in order
- `{{classification}}` the `## Definition` section of classification.md, verbatim
- `{{lens_instruction}}` the body of this lens's `## Lens:` section above
