## EPISODE TYPE: ACTION — PHYSICAL CONFRONTATION SEQUENCE

This episode contains a gunfight, hand-to-hand combat, ambush, breach, or sustained physical confrontation.

### SPATIAL CONTRACT

The scene's INITIAL DISPOSITION is the tactical map: every character's position relative to a named landmark, their cover, the exits, the distances between opposing parties, and who can see whom. It governs every panel. No character changes position without a `motion_prompt` that physically moves them.

### RHYTHM

Panels run 3–6s. Scale must alternate — no two consecutive panels share the same scale AND angle. Adapt this shape to the source; never force it:
- **Open [WS or MS | geography]** — every combatant visible, cover and distances readable. If the engagement is already under way, open inside it — never on people at rest.
- **Engage [MS]** — the action that starts the exchange, already in motion at frame 0: the draw, the breach, the first strike.
- **Exchange [MS]** — attack and response as ONE continuous arc: wind-up, contact, the other body's reaction.
- **Decisive detail [ECU]** — the one micro-action that turns the exchange: a grip closing on a wrist, a slide locking back empty.
- **Reposition [WS or MS | geography]** — who moved where; the new arrangement of cover and distance.
- **Consequence [MS or WS]** — the outcome readable in the whole space: who is standing, who is down and still moving, what changed.
- **Close [CU or MS]** — the current state. If the fight continues into the next scene or episode, stop mid-engagement — no artificial resolution.

### IMPACTS

- An impact is never an isolated instant: the panel holds approach, contact and immediate consequence. For a hard visual accent make it one SHOT inside a multi-shot panel.
- Motion blur on the striking element; the primary subject's face stays sharp.
- A flash, spark or fire is a light source — name it in `lights_and_camera`.
- A character who goes down keeps moving (see the fallen-character rule): cut on impact + first consequence, and open the next panel with them already trying to rise or crawl.

### SOUND

Establish an ambient bed in the first panel (traffic, rain, ventilation). Describe each weapon sound precisely. The beat after the loudest event drops to ambient silence; voice on that panel follows MANDATORY VOICE COVERAGE.

### FORBIDDEN

- Opening on characters at rest when the engagement is already in progress
- Two consecutive panels at the same scale and angle
- More than two consecutive CU/ECU panels — the viewer loses the map
- Emotional language in `motion_prompt` ("he erupts in rage")
- A weapon appearing in a hand without a stated draw or pickup
- A character changing position or cover without a `motion_prompt` that moves them
