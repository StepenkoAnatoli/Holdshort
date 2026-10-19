<!-- Lineage: generalises calibration run 3's clustering prompt and CLUSTER schema (its main workflow script) and the
cluster-assignment step of its supplementary run, with the subject as a placeholder. -->

# Clustering prompt (one per run)

After every review is graded, one agent on the judging profile groups the other S1-S3 findings of all reviews by
mechanism, so the lenses judge each distinct claim once. It does not judge truth. A supplementary run (a void cell
re-run once, protocol Item 3.2) uses the assignment prompt instead: its findings join the main run's clusters, and a
cluster the main run already adjudicated keeps its verdict.

## Prompt

Cluster these review findings (all about {{module}} at one tree) by the defect mechanism and location they describe,
so that each cluster is one distinct claim; a finding that stands alone is its own cluster. For each cluster give: id
(C-1, C-2, ...), title (one line), claim (a precise statement of the mechanism, the cited lines and the rule it is said
to break, written from the members' texts; 3-6 lines), members ('<candidate> <finding id>', exactly as given),
graderClassifications (one per member, as given). Do not judge truth. FINDINGS: {{findings}}

## Assignment prompt

Assign each of these review findings to one of the MAIN RUN's existing clusters when it describes the same mechanism
and location (reuse that cluster's id, title and claim verbatim, and list ONLY the new members), else make a new
cluster with a fresh id (C-N1, C-N2, ...). EXISTING CLUSTERS: {{existing_clusters}}. The findings are all about
{{module}} at one tree. For each cluster give: id, title, claim, members ('<candidate> <finding id>', exactly as
given), graderClassifications (one per member, as given). Do not judge truth. FINDINGS: {{findings}}

## Output schema

```json
{
  "type": "object",
  "properties": {
    "clusters": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "title": {"type": "string"}, "claim": {"type": "string"},
      "members": {"type": "array", "items": {"type": "string"}},
      "graderClassifications": {"type": "array", "items": {"type": "string"}}},
      "required": ["id", "title", "claim", "members", "graderClassifications"]}}
  },
  "required": ["clusters"]
}
```

## Placeholders

- `{{module}}` the subject module's path in the pack (manifest `subject.module`)
- `{{findings}}` the other S1-S3 findings as JSON: candidate, id, severity, the grader's classification and mechanism, the problem and evidence text (cut at 60,000 characters)
- `{{existing_clusters}}` (assignment prompt only) the main run's clusters as JSON: id, title, claim
