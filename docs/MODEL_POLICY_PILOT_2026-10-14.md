# Holdshort model-policy pilot — 14 October 2026

All three requested models matched the frozen expected decisions on twelve
synthetic cases. The pilot demonstrates basic policy following for the supplied
examples; it does not establish a best model, production qualification, cost
savings, or reliable automatic model switching.

Status: exploratory evidence. No evaluation contract was ratified or changed.

## Results

| Requested model | Requested reasoning | Routes | First failing gate | HumanGate | Prior-result classification |
| --- | --- | --- | --- | --- | --- |
| GPT-6 Luna (`gpt-6-luna`) | Medium | 12/12 | 12/12 | 12/12 | 1/1 |
| GPT-6.1 Sol (`gpt-6.1-sol`) | Medium | 12/12 | 12/12 | 12/12 | 1/1 |
| GPT-6 Astra (`gpt-6-astra`) | Medium | 12/12 | 12/12 | 12/12 | 1/1 |

All answers also marked the simulated decisions as advisory, without claiming
actual execution. There were three real Codex subagent runs, one per requested
model; the simulation's `dispatch_performed: false` does not mean there were no
model requests. None of the twelve hypothetical tasks was executed through the
repository's live provider adapter.

The native spawn requests accepted the specified model aliases and Medium
reasoning. Resolved immutable model revisions and independently observed
per-agent usage were not exposed to the coordinator. Model labels in this report
therefore identify requested configurations, not verified immutable deployments.

## Method

The source revision was `6898c59b1a4951924e631d95079549f74e9a083f`. The packet,
expected answers, cases and metrics were frozen before the three spawn requests.
Each agent started without this conversation's history and received the same
instruction to read one identical packet, use no further tools, and return a
compact JSON decision projection. The answer key was not supplied to contestants.
No retries, corrective feedback, or additional contestant turns were used.

The common packet contained the canonical skill, eligibility gates and autonomous
host policy. Synthetic defaults explicitly supplied authorization, qualification,
freshness, verification, accounting and economics facts except where a case
overrode them. This prevents an omitted prerequisite from changing the intended
first failing gate.

The six existing examples were S03, S04, S06, S08, S01 and S05. Six new cases
covered a missing verifier, deadline equality, cash equality and call headroom, explicit
merge review, high consequence without a human request, and an unverified prior
result followed by a blocked continuation. There were eight blocked decisions
and four direct decisions per model.

The frozen scoring fields were route, first failing gate, HumanGate, outcome and
the simulated execution claim. Only X06 asked for an outcome classification;
the other eleven outcome fields were expected to be null. Rationale text was
retained for qualitative review but was not assigned a numeric score after the
responses arrived.

## Findings

1. **No routing or HITL mismatch on these cases.** All models blocked unavailable
   prerequisites at the intended gate. All respected the explicitly requested
   merge review, and none invented a human checkpoint for the high-consequence
   task or verification failure.
2. **X03 leaves reservation ownership ambiguous.** Luna wrote "four total calls";
   Sol referred to six total slots; Astra said the two new calls fit. The case
   does not say whether the two existing reservations already cover the two
   planned calls. Four is plausible if they do; six is plausible if they belong
   to other work. Both interpretations fit the six-call limit, so the expected
   route is unchanged. The initial qualitative review overstated this as a Luna
   arithmetic error; that interpretation was corrected and the correction was
   appended to the observation record. Future cases must bind each reservation
   explicitly to its task. This case does not prove exact call-limit equality.
3. **The existing evaluator checks too little for broad policy claims.**
   `check_skill_adherence.py score` checks route agreement only. It does not score
   gate order, HumanGate, outcome classification, explanation arithmetic, or
   delegation objects. This pilot adds a separate reproducible evidence scorer
   without changing the existing evaluator or any ratified threshold.
4. **Delegation and escalation coverage is incomplete.** The Python tests named
   D01 and E01 describe delegation or escalation but assert `direct` for their
   eligible-candidate legs. Their success does not prove those other routes.
   This pilot likewise exercises only direct and blocked decisions; speculative
   routing and machine-readable Brief/SpeculativeSet compliance remain untested.
5. **Per-model accounting and latency instrumentation are missing.** No reliable
   token or dollar measurements were available for these three agents. Future
   comparisons need independently captured per-agent usage and completion times
   before making cost or speed claims.
6. **The archive initially exposed a newline portability problem.** The frozen
   packet digest used normalized LF text, but the frozen Windows answer-key
   digest used CRLF bytes. The replay scorer reconstructs those original forms
   explicitly. The frozen inputs and answer key were preserved.

## Time and usage

The coordinator observed the launch batch at `2026-10-13 23:57:56 UTC` and had all
three responses by `2026-10-13 23:59:15 UTC` (02:57:56–02:59:15 on 14 October in
Asia/Jerusalem). The resulting 79-second observation window includes scheduling,
packet retrieval and coordinator observation delay. It is an upper bound for the
batch, not a precise inference latency or a per-model speed ranking.

| Measurement | Luna | Sol | Astra |
| --- | --- | --- | --- |
| Precise per-agent elapsed time | Unknown | Unknown | Unknown |
| Input / cached input / output / reasoning tokens | Unknown | Unknown | Unknown |
| Provider dollar cost | Unknown | Unknown | Unknown |
| Resolved model revision | Unknown | Unknown | Unknown |

The earlier session-wide usage snapshot cannot be allocated to these models or
tasks. Unknown measurements remain null in the saved record; zero is not used
as a substitute. No credential, private session text, or unrelated project data
was included in the public evidence.

## Reproduce the scoring

From the repository root:

```bash
python docs/evidence/2026-10-14/model-policy-pilot/score.py
```

This verifies the frozen packet and answer-key digests, validates the response
structures, and recomputes field agreement. It makes no model calls. Exit 0
means the archived answers match the frozen fields, 1 means a mismatch, and 2
means malformed or unverifiable evidence. A replay pass is not a new model run.

The [evidence directory](evidence/2026-10-14/model-policy-pilot/) contains the
frozen protocol, packet, answer key, each model's original JSON response,
recomputed scores, coordinator observation metadata, and the replay scorer.
Source and response text digests are normalized to UTF-8/LF except for the
explicitly preserved original CRLF answer-key digest.

## What this supports

The three requested configurations all followed this small, supplied policy
packet well enough to produce the expected decisions. The reservation ambiguity
shows why accounting inputs need explicit ownership and quantitative explanations
need independent verification.

One response per model on related, open-book cases is insufficient to choose a
model for production routing. The packet contains familiar policy examples and
is not an unseen holdout. Follow-up work should use independently frozen unseen
cases, repeated runs, positive examples of every route, executable acceptance
checks, and per-agent telemetry. A later Ultra experiment should be reported
separately so extra reasoning and coordination are not conflated with model
choice. Existing live-dispatch accounting issues #47 and #48 remain open.
