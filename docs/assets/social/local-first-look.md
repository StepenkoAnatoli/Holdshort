# Local first look — video storyboard

This silent vertical explainer introduces the policy and offline contributor path.
It is not a screen recording, live-model benchmark, or demonstration of provider
billing enforcement. Its graphical terminal panel reproduces locally observed
checks: first observed on 14 October 2026, and again under the new names on
21 October 2026, when the video was re-rendered after the rename (ADR-0003).

| Time | Content |
| --- | --- |
| 0–8 s | Holdshort: model routing, clear checks, visible limits; experimental live-provider status. |
| 8–19 s | Clone the repository and run the two local checks below. Packaging passed for three skills; the decision suite passed 94 assertions across 57 fixture IDs. |
| 19–30 s | Permissions, capabilities, verification, affordability, and economics, in order. |
| 30–38 s | Synthetic cash cap of $0.10, spending of $0.06, and another task's reservation of $0.02 leave $0.02 for the new task. These are fixture values, not provider prices. |
| 38–45 s | Contributor issue #56 and the other LLM evaluation tasks; README/current limits; AI-assistance disclosure. |

Observed commands, run from the repository root:

```bash
python tools/validate_skills.py --strict
python tests/holdshort_decisions.py
```

The exported MP4 uses H.264 video, 720 × 1280 pixels, 24 frames per second,
and an AAC silent audio track. It has brief fades between five graphical panels.
Keep the text and limitations in the storyboard consistent with the repository
when creating future versions. AI assisted with the graphics and copy.
