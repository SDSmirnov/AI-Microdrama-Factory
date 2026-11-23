<!-- replace: ## EPISODE STRUCTURE -->
## EPISODE STRUCTURE

**One continuous film.** Each episode = one sequence from the source text, broken into 1–3 scenes. Episodes are production units: a long fight or chase continues across episode boundaries without a new hook, a re-establishing reset, or an invented cliffhanger.

Each episode has an `episode_type` naming its dominant SEQUENCE TYPE:

| episode_type | What it covers | Panel duration | Dominant scales | Rhythm |
|---|---|---|---|---|
| `action` | gunfight, hand-to-hand combat, ambush, breach, physical confrontation | 3–6s | WS, MS, ECU | re-establish positions after every exchange |
| `chase` | foot or vehicle pursuit, escape | 3–6s | WS, MS | pursuer/pursued alternation; geography every 3 panels |
| `dialogue` | interrogation, negotiation, argument, confession | 6–{{VIDEO_MAX_SECONDS}}s | CU, ECU, MS for power shifts | slow; the pause before the answer matters |
| `reveal` | discovery or twist that reframes the story | 5–{{VIDEO_MAX_SECONDS}}s | CU, MS, ECU at the reveal | builds to one decisive panel, then the reaction |
| `transition` | location change or time skip | 2–4s | WS, MS (environment only) | match cuts between panels |

A mixed episode uses the type that covers most of its panels. Never use "standard" or "pov" as `episode_type` in this style.

A sequence that changes location (corridor → stairwell → street) becomes one scene per location, in order. Each scene carries its own `location` and `initial_disposition`.

Panel count per scene is chosen by you based on pacing (allowed: __PANEL_COUNT_OPTIONS__):
4–6 panels = brief beat, travel or a single exchange; 9 panels = standard sequence (default); 10–12 panels = sustained engagement or dense dialogue.

Episode boundaries follow the source text:
- A physical sequence ends — the fight is over, the chase stops, the breach is complete
- A location is vacated, or time jumps
- A natural chapter or scene break

Do NOT force episodes to end on cliffhangers. Do NOT open a mid-sequence episode with an establishing shot of people at rest.

Your full response must cover the entire source text from beginning to end. There is no fixed total count: generate as many episodes as the text requires.

__TRANSITIONS_INSTRUCTION__

<!-- replace: ## POV SWITCHING — LITERARY MULTI-CHARACTER NARRATIVES -->
## POV SWITCHING — LITERARY MULTI-CHARACTER NARRATIVES

Action novels and thrillers switch narrative perspective mid-chapter: several episodes follow Detective Jack, then switch to Criminal Joe for several episodes, then return to Jack. Perspective changes are tracked through `pov_character`, independently of the sequence type.

**pov_character field:**
- `episode_type` carries the SEQUENCE TYPE (action / chase / dialogue / reveal / transition) — never "pov" or "standard".
- Set `pov_character: "[name]"` for any episode that follows a single character's perspective.
- Set `pov_character: ""` for ensemble or neutral-perspective episodes (e.g. a firefight with several equal-weight characters).

**The continuity problem:** the scene generator for EP7 (Jack returns) receives only EP6's `visual_continuity_rules`. Jack's physical state from EP2 (what he's wearing, any injuries, what he's carrying) is 5 episodes stale. Without explicit propagation, the scene generator will hallucinate Jack's state.

**Solution — CHARACTER STATE LEDGER:** every episode's `visual_continuity_rules` carries the full ledger of all named characters, including those who are offscreen. When Jack doesn't appear in EP3–EP6, those episodes copy his ledger entry verbatim. When EP7 receives EP6's continuity rules, Jack's entry is current.

**EPISODE ENTRY STATE on POV switch or return:**

*POV SWITCH* — this episode follows a different character than the immediately preceding episode:
```
POV SWITCH TO [name]:
  [name] state from CHARACTER STATE LEDGER (EP[N]): [clothing | injuries | carried props | last location]
  World state inherited from EP[prev] EXIT STATE: [active lighting, environmental conditions]
  P1 opens on: [specific physical conditions this scene must establish]
```

*POV RETURN* — returning to a character absent for ≥2 episodes:
```
POV RETURN TO [name] (absent since EP[N]):
  [name] state from CHARACTER STATE LEDGER: [clothing | injuries | carried props]
  Known changes since EP[N] per source text: [what happened to them in the interim, if stated]
  World state: [relevant context from previous episode EXIT STATE]
  P1 opens on: [specific physical conditions, reconciling ledger state with current world]
```

*Same-POV continuation* (normal case): use the standard EPISODE ENTRY STATE format — confirm each item from the previous EXIT STATE.

<!-- append -->
## ACTION SEQUENCE BLUEPRINT

These rules extend the scene_instructions format for `action` and `chase` episodes.

**SPATIAL MASTER.** `initial_disposition` is the tactical map for the scene. For every character state: position relative to a named room landmark (ENTRANCE WALL, FAR WALL, LEFT WALL, RIGHT WALL, or a named piece of furniture), what cover they are behind and what that cover is made of, and who has a clear sight line to whom. Give distances between opposing parties in metres. Compass directions are forbidden — downstream passes use entrance-relative names only. No character changes position later without an ACTION line that physically moves them.

**Per-panel fields.** In ACTION, name the mover, the movement and the distance ("Reyes crosses 3 m from the pillar to the overturned desk, low"). In STATE, record what changed tactically: cover taken or lost, weapon drawn / fired / empty / dropped, distance closed or opened, injury received.

**Scale words.** Use WS (not "WIDE"), MS, MCU, CU, ECU.

**Hook types.** In this style the panel headers use: scene_open / geography / engage / exchange / impact / reposition / close_call / dialogue_exchange / revelation / emotional_beat / scene_close. This list replaces the HOOK TYPE options given above.

**Geography cadence.** Open the scene on a WS or MS that shows every combatant and their cover. Return to a WS or MS that re-establishes positions at least every third panel, and after every move that changes cover.

**Weapons and injuries persist.** Carry every weapon state and wound in PROP STATE LEDGER and CHARACTER STATE LEDGER. A character hit in one episode is still hurt in the next and moves accordingly. Ammunition is finite when the source counts it.

**No clean violence the source does not have, and none it does have removed.** Misses, stumbles, jams and exhaustion stay if the source has them.
