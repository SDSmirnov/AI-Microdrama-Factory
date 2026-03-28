### RULE 7 — SOURCE COVERAGE AND NARRATIVE FIDELITY
Verify that the generated panels faithfully cover the source text for this episode:
  - Every spoken line present in `rewritten_condensed_narrative` must appear in at least one panel's `dialogue`.
  - Every named physical action in `rewritten_condensed_narrative` must appear in at least one panel's `motion_prompt`.
  - No panel may contain actions, revelations, or dialogue ADDED beyond the source.
  - The scene must end where the source ends — not with invented escalation.
  - Each panel's `emotional_beat` and `hook_type` must align with the actual story beat it covers.
If any of these fail: regenerate the affected panel(s) with corrected coverage.
