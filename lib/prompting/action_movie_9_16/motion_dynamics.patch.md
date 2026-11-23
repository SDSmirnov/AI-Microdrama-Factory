<!-- append -->
## APPENDIX D — COMBAT CHOREOGRAPHY FOR I2V

> This appendix extends (does not replace) the **PEOPLE — COMBAT** table in the main reference. Use the main table for simple single-strike clips. Use this appendix for any clip containing combinations, blocks, spinning kicks, jump kicks, or prop-based fighting.

---

### D1 — Kinetic Chain: Mandatory Pre-Strike Milestones

Power in any strike originates at the ground and travels through sequential body segments. Skipping any segment produces "arm punch" — a weightless limb moving without ground connection. All four milestones must appear in order before the striking limb reaches the target.

| Segment | Visual Milestone | Sub-second window |
|---|---|---|
| **Origin** | Rear heel lifts; ball of foot pivots, torquing the floor | 0–0.05s before strike |
| **Amplification** | Pelvis swivels toward target; hip rotates; core compresses | 0.05–0.10s |
| **Transfer** | Shoulder follows hip; elbow lifts and drives forward | 0.08–0.12s |
| **Culmination** | Wrist/ankle locks; fist or shin/foot reaches peak velocity at target | 0.12–0.25s (punches) / 0.35–1.0s (kicks) |

**Weight-transfer cues by technique:**

| Technique | Load distribution | Shift on follow-through |
|---|---|---|
| Lead hook | 70% on lead foot | Stays on lead foot; pivot deepens |
| Rear hook / cross | 70% on rear foot | Shifts forward to lead as fist extends |
| Low kick (rear leg) | 70% on rear foot | Hip drives forward, weight briefly 60/40 lead |
| Ushiro-mawashi-geri | Standing leg pivots 180° on ball of foot | Heel of standing foot points toward target at pivot completion |

**D1 — Ground-First Rule**
Every punch and kick must show ground contact changing before any limb moves. Describe the foot/heel pivot, then the limb.
> *Bad: "He throws a jab toward her face."*
> *Good: "Lead heel drives into the floor, hip rotates — jab extends toward her face in 0.2s."*

**D2 — Hip-Leads-Shoulder Rule**
Hip rotation precedes shoulder by 0.05–0.08s. Never describe the shoulder rotating before the hip.
> *Bad: "His shoulder rotates driving the cross toward her chin."*
> *Good: "Hip drops and drives forward; shoulder unloads behind it — cross toward her chin."*

---

### D2 — Per-Technique Timing Library (Extended)

> Note: execution times below are for trained martial artists. Add 30–50% for untrained characters (H7 fatigue/anxiety modifiers still apply on top).

| Technique | Discipline | Chamber/Load (s) | Execution (s) | Retraction/Settle (s) | Total (s) | Fills 6s? |
|---|---|---|---|---|---|---|
| Jab | Boxing | 0.05 | 0.15–0.25 | 0.15–0.30 | 0.35–0.6 | No — needs combo or reaction |
| Cross | Boxing | 0.10 | 0.20–0.35 | 0.20–0.40 | 0.50–0.85 | No — needs setup |
| Hook | Boxing | 0.15 | 0.25–0.40 | 0.30–0.60 | 0.70–1.15 | No — needs reaction |
| Uppercut | Boxing | 0.15 | 0.20–0.35 | 0.30–0.50 | 0.65–1.0 | No |
| Mae-Geri (front kick) | Karate | 0.15 (chamber knee) | 0.35–0.50 | 0.30–0.50 | 0.80–1.15 | No |
| Mawashi-Geri (roundhouse) | Karate | 0.15–0.20 | 0.50–0.80 | 0.50–1.00 | 1.15–2.0 | No — needs reaction |
| Roundhouse (shin) | Muay Thai | 0.15–0.20 | 0.80–1.20 | 0.50–1.00 | 1.45–2.4 | Yes (borderline) |
| Roundhouse | Taekwondo | 0.20–0.30 | 1.20–1.80 | 0.50–1.00 | 1.90–3.1 | Yes |
| Ushiro-Mawashi-Geri (spinning heel) | Karate/TKD | 0.20 (pivot + back-turn) | 0.60–0.90 (spin + heel arc) | 0.50–0.80 (land) | 1.30–1.9 | No — needs impact reaction |
| Low kick (leg/shin) | Muay Thai/MMA | 0.10–0.15 | 0.30–0.50 | 0.30–0.50 | 0.70–1.15 | No |
| Jump roundhouse | TKD/Karate | 0.30 (dip + launch) | 0.50–0.80 (air + rotation) | 0.60–0.90 (absorb) | 1.40–2.0 | No — needs reaction |
| Block / hard parry | All | 0.05 | 0.15–0.30 | 0.10–0.20 | 0.30–0.55 | No — pair with counter |
| Slip / weave | Boxing | 0.05 | 0.10–0.20 | 0.10–0.15 | 0.25–0.40 | No — pair with counter |

**Punch pause at extension:** Every punch has a brief "jolt" at full extension (0.02–0.05s) before retraction begins. This is a distinct visual keyframe — describe it or I2V blends extension and retraction into a continuous smear.

**D3 — Chamber Mandatory Rule**
All kicks require a chambered-knee milestone before extension. Omitting it produces a "leg-lift" with no biomechanical power.
> *Bad: "She kicks toward his ribs."*
> *Good: "Knee chambers to hip height (0.15s), then snaps forward toward his ribs."*

**D4 — Retraction-Path Rule**
Punch retraction follows a different path than extension (lower, more lateral, back to guard). Describe it separately — models default to reversing the same line, producing a "backtrack" artifact.
> *Bad: "Jab extends and retracts."*
> *Good: "Jab extends straight toward his chin; retracts along a lower arc back to guard position."*

---

### D3 — Attack-Defense Simultaneity

True simultaneous block-and-strike is a perceptual illusion. The block intercepts the limb **10–30ms before** the counter-strike lands, because the block occurs closer to the defender's body. The defender reads from the **attacker's load phase**, not the extension.

| Incoming technique | Read signal | Block begins | Counter begins |
|---|---|---|---|
| Jab | Lead shoulder dips; lead heel loads | As jab extends (~0.12s in) | Block contact + 10–30ms |
| Cross | Rear hip rotates; rear shoulder drives | As cross extends (~0.15–0.25s in) | Redirect contact + 10–30ms |
| Low kick | Rear hip drops; rear knee bends outward | As rear leg lifts | Check contact → launch |
| Jump kick | Visible unweight dip before takeoff | Block positions before apex | Land-based counter after attacker's landing |

**Reaction lag:** A non-telegraphed strike triggers a 200ms neural delay (simple reaction time). A trained fighter reading a known combination drops this to ~120ms via pattern recognition. Characters who react at 0ms appear robotic.

**D5 — Read-the-Load Rule**
Defenses begin during the attacker's **load phase**, not after the limb extends. Use language: *"As [body segment] loads [technique], [defender] is already [defense in motion]."*
> *Bad: "He jabs; she blocks."* ← Bride is always late
> *Good: "As his lead shoulder dips into the jab, her forearm is already rising to meet it."*

**D6 — Staggered Contact Rule**
In simultaneous block-and-counter, the block contacts first, the counter lands a beat later. Describing both on the same frame produces a rigid, artificial freeze.
> *Bad: "She simultaneously parries and counter-punches."*
> *Good: "Her parry redirects the cross outward; her counter drives toward his jaw a half-beat after."*

---

### D4 — Combination Chaining

The **retraction/settle of strike N is the load of strike N+1**. Describe the transition body state — not just the techniques in sequence.

**Range bands** — technique selection depends on current distance:

| Range | Distance | Viable techniques |
|---|---|---|
| **Kicking** | 1.2–2.0m | All kicks; long punches at outer edge |
| **Punching** | 0.5–1.2m | All punches; elbows at inner edge |
| **Clinch / grappling** | 0–0.5m | Knees, elbows, throws; kicks impossible |

**Transition cues by combination:**

| Combination | Transition body state | Prompting language |
|---|---|---|
| Jab → Cross | Jab retraction pulls lead shoulder back, coiling rear hip | "Jab snaps back; hip counter-rotates, loading the cross." |
| Cross → Hook | Cross follow-through rotates body past center; front foot pivots | "Cross drives through; front foot pivots, weight surges to lead side, loading the hook." |
| Cross → Low kick | Cross rotation opens rear hip; rear leg loads from coiled position | "Cross unwinds; rear hip stays loaded and drops, sweeping the low kick." |
| Any punch → Kick | Rear hip rotation from punch creates natural kick chamber | "After the cross, rear hip is already coiled — knee chambers without extra setup." |
| Spinning kick → Guard | After 360° spin, lead foot plants first; core re-centers | "Spin follows through; lead foot plants, guard returns to frame-center." |

**D7 — No Dead Pause Rule**
Never insert a neutral pause between chained techniques. The retraction of one feeds directly into the load of the next.
> *Bad: "She jabs. She pauses. She throws the cross."*
> *Good: "Jab retraction counter-rotates the hip, feeding directly into the cross."*

---

### D5 — Impact Reaction Library

**Three-phase whiplash — total window: 250ms**

| Phase | Timing | Visual description |
|---|---|---|
| **Phase 1 — Fixation** | 0–50ms | Torso moves in impact direction; head stays fixed by inertia; neck straightens, losing natural curve |
| **Phase 2 — Whip** | 50–150ms | Head snaps sharply in impact direction; neck hyperextends past normal range of motion |
| **Phase 3 — Rebound** | 150–250ms | Neck recoils; head flicks back toward center (hyperflexion); jaw loosens momentarily |

**Impact zone → visual reaction:**

| Impact zone | Rotational force | Visual outcome |
|---|---|---|
| **Forehead (anterior)** | Low | Head moves straight back; body stays upright; minor S-curve |
| **Jaw / temple (anterolateral)** | Extreme (4× forehead) | Severe rotational whip; "jelly legs"; potential crumple |
| **Body shot (ribs/liver)** | N/A | Torso folds toward impact side; hips drop; audible breath expelled |
| **Low kick (shin/thigh)** | N/A | Struck leg buckles; weight snaps to opposite leg; stagger step |

**Crumple vs. stagger decision:**
- Center of gravity stays over base of support → **stagger** (compensatory step, wide-stance catch, hands up to brace)
- Center of gravity exits base of support → **crumple** (knee buckle, diagonal fall, one-hand floor contact)

**D8 — Whiplash Sequence Rule**
Any significant head impact must render all three phases within 0.25s. Skipping Phase 1 (fixation) makes the hit look soft; skipping Phase 3 (rebound) makes it look pasted.
> *Good: "Impact — torso lurches forward, head stays fixed (0.05s); head snaps hard toward frame-left (0.10s); rebounds back toward center as jaw loosens (0.10s)."*

---

### D6 — Jump Kick Milestones

Six keyframes must appear in sequence for any jump kick to read as physically grounded. Skipping phases 2–3 produces "teleport to air."

| Phase | Duration | Visual milestone |
|---|---|---|
| **1 — Stance** | 0.10–0.15s | Both feet planted; weight centered; brief breath hold |
| **2 — Unweight dip** | 0.15–0.20s | Hips drop, knees bend — brief crouch stores potential energy |
| **3 — Launch** | 0.10–0.15s | Both legs drive; heels leave floor; hips rise above knee level |
| **4 — Flight + rotation** | 0.50–0.90s | Limbs pulled toward body axis to accelerate spin (tighter tuck = faster rotation); kicking limb extends near apex |
| **5 — Impact / apex** | 0.10–0.15s | Heel or foot at maximum extension; body weight behind the strike |
| **6 — Landing absorption** | 0.50–0.80s | Lead foot plants first; ankles → knees → hips flex sequentially to absorb ground reaction force; brief forward lean |

**Ushiro-Mawashi-Geri specific milestones:**

| Phase | Key detail |
|---|---|
| Phase 3 (launch) | Standing foot pivots 180° on ball; heel of standing foot ends pointing toward target |
| Phase 4 (rotation) | Back faces opponent — head rotates faster than body to "spot" the target and maintain visual lock |
| Phase 5 (impact) | Knee is straight at heel contact; heel arc completes the rotation |
| Phase 6 (landing) | Spin momentum carries forward; standing leg must be described or I2V defaults to a freeze landing |

**D9 — Unweight-Dip Mandatory**
All jump kicks require a visible downward dip before launch. Omitting it produces "teleport to air."
> *Bad: "She jumps and kicks toward his head."*
> *Good: "Hips dip briefly (0.15s), knees bend — both feet drive off the floor and she's airborne."*

**D10 — Spotting Rule**
In any spinning technique, the head rotates faster than the body to re-acquire the target. Describe the "spot" (eyes snapping back to target) as a distinct beat — without it, models render a blind spin where the character's gaze is undefined mid-rotation.
> *Good: "As the 360° rotation completes, her head snaps back toward the Groom a half-beat before the heel arrives."*

---

### D7 — Props in Combat

| Prop type | COG effect | Block reach | Blocking capacity | Key prompting notes |
|---|---|---|---|---|
| **Light / soft** (bouquet, small bag, cloth) | Negligible | +15–30 cm | Absorbs light strikes; collapses on hard impact | Describe prop deformation at contact: compress, bend, fracture |
| **Long rigid** (bat, staff, cane) | Shifts toward prop-end if extended away from body | +50–100 cm | Can stop heavy strikes; prop mass absorbs force | Torso must lean opposite to prop-side or stance reads as impossible |
| **Heavy** (large bag, briefcase) | Lowers and shifts toward held side | None practical | Passive shield only; not a parry tool | Describe slower strike initiation (H6); wider base stance |
| **Two-handed** (any prop gripped with both hands) | Both arms locked | Arms occupied | Full-torso pivot required to redirect any strike | No independent arm parry; describe hip pivot as the block mechanism |

**D11 — Prop Release Rule**
If a character transitions from a prop-block into a spinning or jump kick, the prop must be explicitly released before the airborne phase. I2V otherwise renders the prop through the entire rotation.
> *Good: "The bouquet falls from her grip as she launches — both hands free for the spin."*

**D12 — Prop COG Compensation Rule**
Any prop held at arm's length requires a visible torso lean in the opposite direction. Without it, the stance reads as physically impossible and I2V produces a float artifact.
> *Bad: "She holds the heavy bag out to her sword side."*
> *Good: "She holds the heavy bag at her sword side, torso leaning slightly toward frame-left to compensate."*
