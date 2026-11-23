<!-- replace: ## EPISODE STRUCTURE -->
## EPISODE STRUCTURE

**One short film.** The whole source becomes a single film with a beginning, a middle and an ending. A short-story-length source yields roughly 3–5 scenes (3–5 minutes of screen time); a longer source yields more. Each episode holds 1–3 scenes, so use as few episodes as the film needs. Episodes are production units only — there are no hooks, recaps or cliffhangers at their boundaries.

**Shape.** Map the source onto setup → confrontation → resolution without adding or reordering events. The opening scene establishes place, people and the threat inside the first panels. The film ends where the source ends; its last panel is a closing image, not a hook for a next part.

Each episode has an `episode_type` naming its dominant SEQUENCE TYPE:

| episode_type | What it covers | Panel duration | Dominant scales | Rhythm |
|---|---|---|---|---|
| `action` | gunfight, hand-to-hand combat, ambush, breach, physical confrontation | 4–8s | WS, MS, ECU inserts | hold the wide; re-establish positions after every exchange |
| `chase` | foot or vehicle pursuit, escape | 4–8s | WS, MS | pursuer/pursued alternation; geography every 3 panels |
| `dialogue` | interrogation, negotiation, argument, confession | 6–{{VIDEO_MAX_SECONDS}}s | two-shot MS, over-the-shoulder CU, ECU for the tell | slow; the pause before the answer matters |
| `reveal` | discovery or twist that reframes the story | 5–{{VIDEO_MAX_SECONDS}}s | MS, CU, WS or ECU at the reveal | builds to one decisive panel, then the reaction |
| `transition` | location change or time skip | 3–5s | WS (environment only) | match cuts between panels |

A mixed episode uses the type that covers most of its panels. Never use "standard" or "pov" as `episode_type` in this style.

A sequence that changes location becomes one scene per location, in order. Each scene carries its own `location` and `initial_disposition`.

Panel count per scene (allowed: __PANEL_COUNT_OPTIONS__): 4 panels = a brief beat or a single exchange; 9 panels = standard sequence (default); 12 panels = a sustained engagement or dense dialogue.

**Silence is a valid choice.** Where the source has no speech and no stated thought, write "— silence —" in DIALOGUE SEED and assign NO voiceover. This overrides the instruction further below to give silent panels a mood voiceover.

Your full response must cover the entire source text from beginning to end.

__TRANSITIONS_INSTRUCTION__
