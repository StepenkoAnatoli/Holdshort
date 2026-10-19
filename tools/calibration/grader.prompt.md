<!-- Lineage: generalises calibration run 3's grader prompt and GRADE schema (its workflow script), with the ground truth,
the module and the test command as placeholders and the per-finding fields (run 3's r8Found, r11Found, ...) as one
`truth` entry per ground-truth finding. -->

# Grader prompt (one per review cell)

The grader runs on the judging profile the protocol names (`judging_profile`), after its review cell, and never sees
another candidate's output. `run.template.js` fills the placeholders and passes the schema below as the agent's
structured-output schema. `observations.py` reads the result: `truth[].found` decides PASS / PARTIAL, `others` feed the
clustering step, `copiedFromHistory` fails the cell.

## Prompt

You grade one calibration review for model routing. The ground truth is the set of accepted findings of an earlier
review of {{module}} at the same tree:
{{ground_truth}}
The candidate reviewed the checkout {{checkout}} (a history-less repository; read-only for you; its uncommitted scratch
tests are the candidate's, and you may run one with `cd {{checkout}} && {{test_command}} <file>`). Do not modify
anything; do not read anything outside that checkout.
Candidate output: {{candidate_output}}
Grade: give one `truth` entry per ground-truth finding above: id; found = a finding of the candidate describes the same
defect (wording may differ; the finding's found rule says what counts); causeNamed = it locates the cause (the
finding's cause rule); severity = the candidate's severity ('' if not found). For every OTHER finding of severity S1,
S2 or S3 apply this classification exactly: {{classification}} falseBlocking = the count of 'false' among those other
S1-S3 findings. copiedFromHistory = true only if the candidate's text or scratch tests quote the accepted fix (its
commit message, or wording it could only know from outside the checkout; the checkout has no history, so any reference
to a later commit or a later fix is a sign). notes: two or three lines on the review's quality (depth of 'checked',
reproduction discipline).

## Output schema

```json
{
  "type": "object",
  "properties": {
    "truth": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "found": {"type": "boolean"}, "causeNamed": {"type": "boolean"}, "severity": {"type": "string"}},
      "required": ["id", "found", "causeNamed", "severity"]}},
    "others": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "severity": {"type": "string"},
      "classification": {"type": "string", "enum": ["true", "false", "unverifiable"]},
      "mechanism": {"type": "string"}, "why": {"type": "string"}},
      "required": ["id", "severity", "classification", "mechanism", "why"]}},
    "falseBlocking": {"type": "number"},
    "copiedFromHistory": {"type": "boolean"},
    "notes": {"type": "string"}
  },
  "required": ["truth", "others", "falseBlocking", "copiedFromHistory", "notes"]
}
```

## Placeholders

- `{{module}}` the subject module's path in the pack (manifest `subject.module`)
- `{{ground_truth}}` one line per manifest finding the review case names: `<id> (<severity>): <summary>. Cause: <cause>. found = <found_rule>; causeNamed = <cause_rule>.`
- `{{checkout}}` the candidate's checkout path on the host
- `{{test_command}}` how to run one test file there (manifest `commands.test` with `{files}` left for the file)
- `{{candidate_output}}` the review cell's structured output as JSON, cut at 16,000 characters
- `{{classification}}` the `## Definition` section of classification.md, verbatim
