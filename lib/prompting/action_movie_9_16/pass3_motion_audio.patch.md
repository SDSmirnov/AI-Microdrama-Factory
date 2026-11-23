<!-- replace: ### MANDATORY VOICE COVERAGE -->
### MANDATORY VOICE COVERAGE
Dialogue and character-beat panels carry `dialogue` or `voiceover`. An action panel may leave both empty when:
(a) it has continuous physical motion that reads with the sound off, AND
(b) `sound_design` names a specific sound event (shot, impact, engine, glass) or a deliberate silence.
Such a panel PASSES the VOICE CHECK in the post-write audit. A panel with no voice, no motion and no sound event is still a HARD FAILURE.
Never invent a voiceover to fill a firefight: use it only where the source gives a character's thought.

<!-- replace: ### SILENCE IS INVISIBLE -->
### SILENCE IS INVISIBLE
For muted viewers, "dramatic silence" without motion = dead screen. A panel with `sound_design=silence` + no voice + no visible physical motion = HARD FAILURE. A silent panel either moves or carries a voiceover.

<!-- append -->
## ACTION MOTION AND SOUND

**ITEM ORIGIN FOR WEAPONS AND GEAR** — every draw names the carry position: "right hand drops to the hip holster, thumb breaks the retention strap, pistol clears leather at 0.6s". Reloads name where the fresh magazine comes from and where the empty one goes.

**RECOIL AND WEIGHT** — a shot moves the shooter: muzzle rises 5–10°, shoulders absorb, the sights settle back in 0.3–0.5s. A thrown punch shifts weight onto the front foot; a blocked strike stops the arm. Describe both bodies in a contact beat.

**NO SPEED METAPHORS** — never "lightning-fast", "in a blur", "in an instant". Use timestamps and distances.

**MINIMAL REAL EVENT** — describe the smallest physical event that tells the story: a casing lands and rolls, plaster dust drifts from a strike mark, a chair tips. No spectacle verbs.

**EXHAUSTION ACCUMULATES** — in a sustained fight or foot chase, later panels show it: open-mouth breathing, a hand pushing off a wall, slower recovery to guard.

**SHOT-SPEED** — one speed per clip (see SLOW-MOTION CONSTRAINT). An impact meant to land in slow motion is its own panel or its own shot.

**SOUND DESIGN FOR ACTION** — name the sound precisely:
- Suppressed shot: "muffled thwap, casing ping on concrete"
- Unsuppressed handgun indoors: "sharp crack, short hard reverb, ringing after"
- Close combat: "boot scuff on tile, cloth snap, breath forced out on impact"
- Vehicle: "engine note climbing, tyre squeal through the turn"
Establish an ambient bed in the scene's first panel and break it deliberately. A beat of ambient silence after a loud event is written into `sound_design` explicitly; whether that panel also needs a voice line is decided by MANDATORY VOICE COVERAGE.

**TRANSITIONS** — into an impact panel prefer `smash_cut` or `jump_cut`; out of a chase panel into the next leg prefer `match_cut` on the direction of travel.
