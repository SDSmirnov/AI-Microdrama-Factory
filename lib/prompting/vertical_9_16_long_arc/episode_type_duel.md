
## EPISODE TYPE OVERLAY: DUEL MODE — ACTIVE

**Duelers: __CHAR_A__ vs __CHAR_B__**

**TWO-FORCE LAW (overrides SINGLE POV):** Both __CHAR_A__ and __CHAR_B__ occupy equal screen weight across all arc episodes. Neither is background. Neither is peripheral. The camera is the referee between two equally matched forces.

**DUEL RHYTHM — attack / counter alternation:**
Every confrontation panel is owned by one character and answered by the next.
- Panel owned by __CHAR_A__ (attack) → immediately followed by __CHAR_B__'s reaction (counter)
- Panel owned by __CHAR_B__ (attack) → immediately followed by __CHAR_A__'s reaction (counter)
- `pivot` panels: neutral — ECU on the arena's detail or a face without clear advantage
- `arc_bridge`: BOTH characters frozen at threshold — equal frame weight, no clear winner yet

**THE REACTOR RULE (mandatory):**
The dominant close-up in every confrontation panel is the character BEING HIT — not the one striking.
The blow (word, gesture, revelation, silence) is off-screen or glimpsed at frame edge.
The REACTION IS THE DRAMA. Write the ECU on the receiver, not the attacker.

**POWER LEDGER:**
In `screenplay_instructions`, track who holds power panel-by-panel as a running tally:
e.g. `A+1 → B+1 → B+2 → A+2 → A+3 → …`
Each panel's `panel_role` must state whose move it is (A_attack / B_attack / A_counter / B_counter / neutral).
By `arc_close.p8` (consequence), the ledger must show accumulated cost for BOTH parties.
No clean victory is allowed before the cliffhanger. If either character has won by p8, the duel is wrong.

**COLD OPEN (duel variant, arc_open.P1):**
BOTH characters visible in the first frame. The power imbalance is the visual question — why is one the aggressor right now? The viewer has zero context; that question keeps them watching.
FORBIDDEN: opening on only one character, opening on environment alone without both faces.

**ARC BRIDGE (duel variant — any intermediate episode's P9):**
Both characters frozen simultaneously at the threshold of the next action.
Not one surrendering, not one about to strike — BOTH suspended.
The match_cut in `visual_end` must capture both faces or both hands in the same frame.
sound_design: silence.

**CLIFFHANGER (duel variant — arc_close.P9):**
The final image must be genuinely ambiguous about who won.
One visible detail (a hand position, a held object, a fractional expression) has two valid interpretations:
→ If it means X, __CHAR_A__ has won. → If it means Y, __CHAR_B__ has won.
The viewer rewinds specifically to settle this question.
FORBIDDEN: any frame that unambiguously shows one character victorious.

**VISUAL MOTIF (duel variant):**
The motif seeded in `arc_open` must be an object or gesture that BELONGS TO BOTH characters — something they fight over, share, or mirror.
In `arc_close.p9` (cliffhanger), one of them holds it while the other's hand is also in frame, reaching or releasing.
