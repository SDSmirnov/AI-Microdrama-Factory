<!-- replace: ## HOOK TYPES -->
## HOOK TYPES

| hook_type | When to use |
|-----------|-------------|
| `scene_open` | P1 — opens the scene |
| `geography` | Establishes or re-establishes who is where: positions, cover, distances, exits |
| `engage` | The action that starts or restarts an exchange — draw, breach, first strike, sprint |
| `exchange` | Attack and response within one continuous arc |
| `impact` | A hit, fall, crash or detonation and its immediate consequence |
| `reposition` | A character changes cover, level or distance |
| `close_call` | Near capture, near miss, near collision |
| `dialogue_exchange` | Panels carrying back-and-forth dialogue |
| `revelation` | A character learns or realizes something |
| `emotional_beat` | A face carries the weight, minimal or no dialogue |
| `scene_close` | PN — closes the scene |

<!-- replace: ## SCALE GUIDANCE -->
## SCALE GUIDANCE

- P1: WS or MS — every combatant and their cover visible from the first frame
- `geography`, `reposition`: WS or MS — full bodies, the route and the destination in frame
- `engage`, `exchange`: MS — both parties or the mover's whole body readable
- `impact`: MS for the consequence; ECU only for the single detail that decides the outcome
- `close_call`: MS or CU
- Dialogue panels: CU on the speaking face; MS when someone moves to change the power balance
- Never more than two consecutive CU/ECU panels inside an action or chase sequence — the viewer loses the map
- PN: scale matches where the source leaves the scene

<!-- append -->
## ACTION SEQUENCE ARCHITECTURE

Applies when the episode type is `action` or `chase`.

**One arc per panel.** Wind-up + strike + the target's reaction is ONE panel. A draw + shot + recoil is ONE panel. Do not spend three panels on three seconds of real time.

**Durations.** Action and chase panels run 3–6s; take the long end only when the panel holds several beats. A panel that covers a short SEQUENCE of setups (push through the door, then the reveal of the room) is a multi-shot panel — Pass 2 breaks it down.

**Geography cadence.** At least every third panel is `geography` or `reposition` at WS/MS. After any move that changes cover, the next panel shows the new arrangement.

**Screen direction.** A pursuit keeps one direction of travel across consecutive panels. Opponents in a fight keep their sides of the frame until a `reposition` panel moves them.

**Camera movement.** Use the declared types only: `Handheld-shake` for close combat, `Truck` or `Pan` to follow a runner or vehicle, `Tilt` for a reveal from weapon to face, `Dolly-in` on a decision, `Static` for the beat after an impact.

**`motion_intent`** names the mover, the verb and the distance or target: "Reyes vaults the counter and drops behind it, 2 m from the door".

**`dialogue_seed`** in action panels is a bark, a command, or empty. Do not invent lines the source does not have.
