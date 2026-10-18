<!-- Lineage: the shared pack proposal Item 2 describes; no run has used one yet. -->

# Shared synthetic subject pack (stub)

This directory will hold the kit's **shared synthetic subject pack**: a small self-contained module with two seeded
defects of the shapes the runs used (a rejection that breaks a "nothing rejects" promise; a bound skipped on an
unexpected input), with its specification, its tests, its accepted fix and its `manifest.json` in the format of
`../README.md`. Every host runs it, so its cells compare across hosts.

It is not built here: the calibration kit unit defines the format and leaves this directory with this README only. The
pack is a separate unit of the calibration-first onboarding work (docs/proposals/calibration-first-onboarding.md, Item 2,
"shared pack"), as are the evidence check in the regression gate (Item 4.3) and the qualification table (Item 4.4).
