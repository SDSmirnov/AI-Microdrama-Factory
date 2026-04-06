## MOTION DYNAMICS — PHYSICAL TIMING REFERENCE FOR I2V PROMPTING

Every I2V clip is **~6 seconds**. Physical movement follows three phases that must all fit inside that window:
`Anticipation → Action → Settle/Inertia`
If any phase is missing from the prompt, the model fills the gap with a visual freeze.

### MOTION CLASS SUMMARY

| Class | Definition | Action Time | Inertia | Clip Strategy |
|---|---|---|---|---|
| **Micro** | One muscle group (blink, press, smile) | < 0.5s | 0.05–0.3s | Always needs fill: add anticipation + secondary action |
| **Normal** | Single purposeful action (pick up, open door, sit) | 0.5–3.0s | 0.3–1.5s | Add settle description; pair with reaction if < 2s |
| **Fast** | Peak-force burst (punch, shot, fall, explosion) | 0.1–1.0s | 0.5–3.0s | Triple structure: Prep (1.5s) + Action (<0.5s) + Recovery (4s) |
| **Macro** | Compound spatial (cross room, car turn, full reload) | 3.0–10s+ | 0.5–3.0s | Cut mid-action or choose entry/exit only |

---

### PEOPLE — FACIAL & MICRO

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Blink (natural) | 0.1–0.4 | 0.05 | No — add idle |
| Smile onset (genuine) | 0.5–1.0 | 0.8–1.5 hold | No — add secondary |
| Surprised gasp | 0.3–0.6 | 1.0–1.5 | No — add reaction |
| Sustained sobbing | 2.0–4.0 | 1.5–2.0 | Yes |
| Single spoken word | 0.3–0.8 | 0.2 | No — pair with gesture |

### PEOPLE — HANDS & ARMS

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Reach and grasp cup | 0.8–1.2 | 0.4–0.6 | No — add look/sip |
| Point (accent gesture) | 0.5–0.8 | 0.5–1.0 | No — add idle |
| Wave (3 cycles) | 1.5–2.5 | 0.8–1.2 | No — add approach/reaction |
| Pour liquid from bottle | 1.5–3.0 | 0.5–1.2 | Yes (borderline) |
| Open wallet / clasp purse | 1.2–2.5 | 0.5–0.8 | Yes |
| Write a word on paper | 0.8–1.8 | 0.3 | No — add look-up |

### PEOPLE — BODY & LOCOMOTION

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Sit down | 1.5–2.5 | 0.5–1.0 | No — add posture adjust |
| Stand from chair | 1.0–2.0 | 0.5–1.0 | No — add look/step |
| Pick up object from floor | 2.0–3.0 | 0.5–1.5 | Yes |
| Jump (vertical, small) | 0.5–1.2 (air) | 1.5–2.5 landing | Yes |
| Fall / stumble | 0.8–1.8 | 0.5–1.5 recovery | Yes |
| Walk — normal (1.4 m/s) | — | 0.2–0.4/step | Yes (looping); 4×4m room ≈ 2.8s; corridor 5m ≈ 3.6s |
| Walk — slow/sad (0.8 m/s) | — | 0.4–0.6/step | Yes; 5m ≈ 6.3s — fits exactly |
| Walk — urgent (1.8+ m/s) | — | 0.1–0.3/step | Yes; fills 6s over ~10m |

### PEOPLE — COMBAT

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Jab punch | < 0.3 | 0.5–1.0 retract | No — needs prep + reaction |
| Hook / roundhouse kick | 0.4–0.7 | 1.0–2.0 balance | No — needs prep |
| Wrestling grapple | 2.0–5.0 | 1.0–2.0 | Yes |
| Block / parry | 0.3–0.6 | 0.3–0.8 | No — add counter |
| Fall from punch (impact to ground) | 0.8–1.5 | 1.0–2.0 settle | Yes |

---

### ANIMALS

| Category | Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|---|
| Cat | Butt-wiggle anticipation | 1.5–3.0 | 0.0 | No — precedes pounce |
| Cat | Pounce / strike | 0.2–0.5 | 1.5–2.0 | No — needs prep |
| Cat | Land from height (righting) | 0.5–1.5 | 1.0–2.0 | No — add stalk |
| Dog | Tail wag (excited, full cycle) | 1.5–4.0 | 0.5–1.0 | Yes |
| Dog | Shake off water | 1.5–3.0 | 0.5–0.8 | Yes |
| Bird | Takeoff (pigeon-size) | 1.0–2.0 | 1.0–2.0 ascent | Yes |
| Bird | Landing (hawk) | 0.8–1.5 | 2.0–3.0 settle | Yes |
| Big cat | Full sprint stride cycle | 0.3–0.5/stride | 0.2–0.4 | Yes (looping) |

---

### MECHANISMS & DOORS

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Push open standard interior door | 1.5–3.0 | 0.5–1.0 swing | Yes |
| Pull open heavy exterior door | 2.0–4.0 | 0.8–1.5 | Yes (borderline) |
| Auto sliding door (full cycle) | 2.5–4.0 | 2.0–3.0 dwell | Yes |
| Elevator door closing cycle | 4.0–5.5 | 0.5–1.0 lock | Yes |
| Heavy vault door | 5.0–10.0 | 1.0–2.0 | No — too long, cut |
| Turn key in lock | 1.0–2.5 | 0.3–0.7 | Yes |
| Industrial robot arm (pick-place) | 0.8–1.5 | 0.5–1.0 vibrate | No — add next move |

---

### WEAPONS & BALLISTICS

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Handgun shot + recoil | 0.1 | 0.4–0.8 reset | No — needs aim (1.5s) + aftermath (3.5s) |
| Aim rifle / draw sights | 0.5–1.5 | 0.3 | No — pair with shot |
| Emergency pistol reload | 1.5–2.2 | 0.8–1.5 | No — add re-aim |
| Assault rifle reload | 3.0–5.0 | 0.8–1.5 | Yes |
| Sword draw (from scabbard) | 1.5–3.0 | 0.5–1.0 pose | Yes |
| Heavy sword/axe swing | 1.0–1.8 | 1.5–2.5 recovery | Yes |
| Grenade throw | 0.8–1.2 | 2.0–4.0 explosion | Yes |
| Shockwave pass (explosion) | 0.5–1.5 | 2.0–4.0 debris | Yes |

---

### VEHICLES & TRANSPORT

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Car hard brake (30→0 mph) | 1.5–2.5 | 0.5–1.0 nose-dive | Yes |
| Car emergency stop (60→0) | 4.0–5.5 | 1.0–2.0 rebound | Yes |
| Car acceleration (0→30) | 3.0–5.0 | 0.5–1.0 | Yes |
| 90° city turn | 2.0–4.0 | 0.5–1.5 body roll | Yes |
| Drift / skid | 2.0–4.0 | 2.0–3.0 settle | Yes |
| Aircraft landing touchdown | 3.0–5.0 | 2.0–4.0 braking | Yes |
| Boat heavy wave pitch | 2.0–4.0/cycle | 1.5–2.5 roll | Yes |

---

### INTERFACES & DIGITAL

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Button press (physical) | 0.1–0.3 | 0.1–0.4 spring | No — add reaction |
| Screen tap | < 0.1 | 0.05–0.1 haptic | No — add UI response |
| Screen swipe | 0.3–0.8 | 0.1–0.3 scroll | No — add content settle |
| PIN / passcode entry | 2.0–4.0 | 0.5–1.0 unlock | Yes |
| Face/fingerprint scan | 1.5–2.5 | 0.5–1.0 unlock | No — add check reaction |

---

### ARCHITECTURE & ENVIRONMENT

| Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|
| Light switch ON (fade-in) | 0.5–2.0 | 0.5–1.5 eye adjust | Yes |
| Manual curtain open | 2.0–4.0 | 0.5–1.0 swing | Yes |
| Small object fall (from table) | 0.3–1.2 | 0.2–0.6 bounce | Yes |
| Glass shattering | 0.5–1.0 | 2.0–4.0 shards | Yes |
| Ceiling fan start (0→full speed) | 3.0–6.0 | 10.0+ | No — show only ramp-up |

---

### WATER, FIRE, PARTICLES & ATMOSPHERE

| Category | Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|---|
| Water | Splash (heavy object) | 0.5–1.5 | 3.0–5.0 ripples | Yes |
| Water | Single droplet impact | 0.05 | 2.0–4.0 ripples | Yes |
| Water | Liquid pour (continuous) | 1.5–3.5 | 0.5–1.2 surface | Yes |
| Water | Wave crash (small) | 1.0–3.0 | 1.0–2.5 foam | Yes |
| Fire | Flash / ignition | 0.5–1.0 | 3.0–5.0 growth | Yes |
| Fire | Steady flicker (wind) | continuous | N/A | Yes |
| Smoke | Rising plume (initial) | 2.0–4.0 | 3.0–6.0 diffuse | Yes |
| Particles | Dust kick-up (footstep) | 0.3–0.8 | 0.2–0.5 settle | Yes |
| Weather | Wind gust (peak effect) | 0.5–2.0 | 0.3–1.0 fade | Yes |
| Weather | Lightning strike | 0.1–0.3 | 0.5–2.0 afterglow | No — add thunder/reaction |
| Weather | Raindrop fall (medium) | 0.5–1.5 | 0.1 | Yes |

---

### FABRIC, VEGETATION & LIGHT

| Category | Motion | Exec (s) | Settle (s) | Fills 6s? |
|---|---|---|---|---|
| Fabric | Jacket flip / coat swing | 0.6–1.2 | 0.4–0.8 wrinkle | Yes |
| Fabric | Shirt flutter in wind (cycle) | 0.5–1.5 | 0.2–0.5 | Yes |
| Fabric | Cloth / silk falls to floor | 1.5–2.0 | 2.0–2.5 settle | Yes |
| Vegetation | Tree branch sway (cycle) | 1.5–4.0 | 0.5–1.5 damp | Yes |
| Vegetation | Single leaf fall | 1.0–2.5 | 0.3–0.7 land | Yes |
| Vegetation | Grass bend/rebound (step) | 0.2–0.6 | 0.1–0.3 | Yes |
| Light | Lamp glow brighten/fade | 1.0–3.0 | 0.2 | Yes |
| Light | Shadow pass over object | 1.5–4.0 | 0.2 | Yes |

---

### HEURISTICS FOR LLM MOTION PROMPTING

**H1 — 2-Second Core Rule**
If the primary action takes < 2s, the prompt MUST include anticipation + settle to fill 6s.
> *Bad: "She presses the button."*
> *Good: "She hesitates, finger hovering (1.5s), presses firmly (0.2s), watches the screen light up (4.3s)."*

**H2 — Combat Triple Structure**
Fast actions (punch, shot, explosion) follow: `Prep/Aim (1.5s) + Strike (<0.5s) + Recovery/Reaction (4s)`.
The recovery carries the emotional weight — describe it explicitly.

**H3 — Inertial Dampening**
Every mechanical or large-body stop needs a settle descriptor:
car stops → "subtle suspension pitch and rebound"; robot arm → "brief vibration before servo locks"; character sits → "posture adjustment and exhale."

**H4 — Environmental Persistence**
Triggered effects (splash, spark, dust) have long decay tails. Describe them:
> *"Splash erupts (0.5s); concentric rings expand and fade across remaining 5.5s."*

**H5 — Idle Loop**
Any character not performing an action needs idle micro-behaviors every 2–4s:
standing → weight shift, gaze scan, clothing adjust; seated → foot tap, pen fidget, neck roll.

**H6 — Mass Scales Time**
Heavier/larger objects accelerate and decelerate slower. A freight truck stop ≠ a bicycle stop.
Describe momentum explicitly for anything > 500kg or > 2m tall.

**H7 — Emotional Speed Multipliers**
Anger: 1.3–1.4× speed, abrupt settle. Anxiety: 1.2× speed, fumbling settle.
Fatigue: 0.5–0.6× speed, heavy/drooping settle. Sadness: 0.6× speed, gravitational settle.

**H8 — No Mechanical Tick-Cadence**
Do NOT space events at ANY uniform interval — not 1s, not 1.5s, not 2s steps. Uniform cadence of any step size produces a metronome effect that breaks organic feeling. Events must cluster around biomechanical phase transitions — anticipation → action → settle — not clock ticks.
> *Bad (1s cadence):* "At 1s… At 2s… At 3s…"
> *Bad (1.5s cadence):* "At 0s… At 1.5s… At 3s… At 4.5s…"
> *Good (organic):* "0s brow furrows → 1.5s head snaps → 2.2s gaze locks → 4.5s slow exhale."

**H9 — Facial Understatement Rule**
Real faces use 20–30% of maximum muscle excursion in everyday emotion. Full excursion belongs to theater, not cinema.
- Anger → jaw tension + narrowed eyes; NOT flared nostrils + bared teeth
- Surprise → brow rise 0.3s then partial relax; NOT sustained wide-eyes + open mouth
- Concern → micro-furrow (0.1–0.3 cm depth); NOT full brow scrunch
- Sustained "expressive face" beyond 2s reads as acting, not feeling. Emotion should DECAY, not hold.

**H10 — Directional Target Rule**
Gaze, steps, gestures, and locomotion MUST name the target or anchor, not just a raw direction. "Forward", "left", "toward camera" are ambiguous — I2V models interpret them relative to whichever axis they choose.
- *Bad: "She steps forward."* → I2V may animate toward camera.
- *Good: "She steps toward Old Man."*
- *Bad: "He glances right."* → Ambiguous screen-space vs body-space.
- *Good: "He glances toward the door at frame-right."*
Rule: every directional verb (walk, step, lean, reach, point, turn, look) must be followed by `toward <named target>` or `to <named location>`.

**H11 — Hand Laterality Rule**
Never say "his hand" or "her right hand" — camera framing can flip apparent sides. Use two anchors: body-relative anatomical Latin (**dextra** = right, **sinistra** = left) AND screen-space entry direction.
- *Bad: "His hand reaches for the cup."* → Which hand? From which side of frame?
- *Bad: "His right hand grabs the knife."* → "Right" flips on mirrored shots.
- *Good: "His dextra hand enters frame from frame-left and grabs the cup."*
- *Good: "Her sinistra hand rises from frame-bottom and adjusts collar."*
Always pair dextra/sinistra with frame-entry direction. Works for any character regardless of handedness or stance.

---

## APPENDIX A — DIALOGUE BIOMECHANICS

### Proxemics (Hall's Zones)

| Zone | Distance | Visual/Cinematic Effect |
|---|---|---|
| **Intimate** | 0–0.45 m | Overlapping shoulders; extreme CU; whispered breath visible; tilted heads |
| **Personal** | 0.45–1.2 m | Full faces; arm-length gestures; direct eye contact |
| **Social** | 1.2–3.6 m | Full torsos; larger arm gestures; frequent gaze breaks |
| **Public** | > 3.6 m | Full body; exaggerated gestures; head-tossing; louder articulation |

### Cultural Gesture Patterns

| Culture | Frequency | Amplitude | Timing vs. Speech |
|---|---|---|---|
| Mediterranean / Latin | High (3–5/6s) | Large, elbows+shoulders | Gesture starts *before* word (anticipation 0.2s) |
| Nordic / Germanic | Low (0–1/6s) | Small, wrist only | Gesture simultaneous or *after* word |
| East Asian | Moderate (nods > hands) | Very controlled | Bowing/micro-nods replace hand gestures; hierarchical |
| Slavic / E. European | Moderate (2–3/6s) | Direct, purposeful | Sharp movements; heavy eye contact |

### Common Dialogue Gestures

| Gesture | Exec (s) | Settle (s) | Speech Context |
|---|---|---|---|
| Agreement nod | 0.3–0.5 | 0.2 | During partner's speech (listening) |
| Head shake (no) | 0.5–1.0 | 0.3 | During contradiction / refusal |
| Finger point (accent) | 0.5–0.8 | 0.5 | At semantic stress moment |
| Shoulder shrug | 0.6–1.0 | 0.4 | After statement of uncertainty |
| Gaze break (thinking) | 0.2–0.4 | — | Mid-sentence, searching for word |
| Lean forward (interest) | 0.8–1.5 | 0.5 | Start of partner's key point |
| Step back (defense) | 0.5–1.0 | 0.8 | Reaction to verbal/physical threat |
| Hand to chin (thought) | 0.3–0.6 | 0.2 | Processing a question |
| Cover mouth (shock) | 0.4–0.9 | 0.3 | Involuntary reaction |

### Turn-Taking Rules

- **Hand-off**: Speaker drops gesture + gaze returns to neutral (0.5s) → signals done.
- **Take-over**: Listener inhales visibly (0.3s) + raises chin/hand *before* speaker finishes.
- **Normal response latency**: 0.2–0.5s between end of speech and reply start.
- **Interruption**: < 0.1s latency + sharp postural shift forward + sudden hand gesture.

### Temperament → Biomechanics

| Type | Gesture Speed | Amplitude | Eye Contact | Settle Style |
|---|---|---|---|---|
| **Choleric** | Fast, sharp | Large, space-invading | Piercing, unmoving | Aggressive, abrupt |
| **Sanguine** | Rhythmic, fluid | Medium, lively | Bouncing, animated | Fluid, bouncy |
| **Phlegmatic** | Slow, deliberate | Minimal, low | Soft, patient | Slow, heavy |
| **Melancholic** | Jerky, hesitant | Small, tight | Avoidant, downward | Drooping, tired |

---

## APPENDIX B — EVERYDAY BIOMECHANICS

### Waiting / Idle Behavior (cycle: every 2–4s)

| Micro-behavior | Duration (s) | Settle (s) | Notes |
|---|---|---|---|
| Weight shift (standing) | 0.5–1.0 | 0.2 torso sway | Core idle loop element |
| Check phone (glance) | 1.0–2.5 | 0.5 replace | Includes lift → look → lower |
| Adjust clothing (tug) | 0.4–0.8 | 0.2 | Minor correction |
| Gaze scan (room survey) | 1.0–2.0 | 0.4 | Slow eye pan with head lag |
| Deep sigh / exhale | 2.0–3.0 | 1.5 shoulder drop | Stress or boredom signal |
| Idle foot tap / leg shake | 0.3–0.6/cycle | 0.1 | Seated; continuous background |

### Eating & Drinking (typical 6s sequence)

| Sub-action | Duration (s) | Settle (s) | Detail |
|---|---|---|---|
| Lift cup to lips | 0.8–1.2 | — | Deceleration near mouth |
| The sip (swallow) | 1.0–2.0 | 0.5 | Slight head tilt back 5–10° |
| Lower cup to table | 0.6–1.0 | 0.4 | Hand stays on cup 1s after |
| After-look (pause) | 1.0–3.0 | — | Gaze at cup or horizon |
> Full drink sequence: ~3.5–6.2s — fits a 6s clip as a complete unit.

### Walk Speeds & Space Traversal

| Emotional State | Speed | 6m in | 10m in | Gait Character |
|---|---|---|---|---|
| Neutral | 1.4 m/s | 4.3s | 7.1s | Even arm swing |
| Thoughtful / sad | 0.8 m/s | 7.5s | 12.5s | Shuffling, low arm swing |
| Purposeful / anxious | 1.8 m/s | 3.3s | 5.6s | High arm, forward lean |
| Running | 3.0–5.0 m/s | 1.2–2.0s | 2.0–3.3s | Full arm drive |

### Emotional Modulation of Common Actions

| Action | Neutral | Anxious (1.2–1.5×) | Tired (0.5–0.6×) | Angry (sharp) |
|---|---|---|---|---|
| Open door | 1.2s | 0.8s (fumbling) | 2.5s (dragging) | 0.4s (jerk/slam) |
| Sit down | 1.8s | 1.2s (edge of seat) | 3.0s (collapse) | 1.0s (rigid drop) |
| Pick up phone | 0.8s | 0.5s (snatch) | 1.5s (slow lift) | 0.4s (grab) |
| Turn head | 0.6s | 0.3s (snap) | 1.2s (slow roll) | 0.3s (glare) |
| Put object down | 0.8s | 1.5s (careful) | 1.0s (drops) | 0.3s (slam) |

---

## APPENDIX C — UNCANNY VALLEY PREVENTION

Applies to ALL three prompt fields: **`visual_start`/`visual_end`**, **`motion_prompt`**, **`animation_instructions`**.

---

### C1 — Facial Calibration

| Emotion | CORRECT (cinema) | WRONG (theater) |
|---|---|---|
| Anger | Jaw clenches, eyes narrow to slits, nostril tension | Teeth bared, flared nostrils, wide-open glare |
| Surprise | Brows rise 0.3s → partial relax within 1s | Eyes stay wide + mouth agape for 3s+ |
| Sadness | Chin dimples, lower lip trembles once | Face crumples, full sob grimace sustained |
| Fear | Eyes widen briefly, then blink-suppress reflex | Frozen terror face, whites of eyes showing |
| Disgust | Unilateral lip curl, nose wrinkle micro-flash | Full sneer + head recoil held |

Expressions must **decay**: a flash of surprise relaxes in 0.5–1.0s; anger holds through jaw only, face surface returns toward neutral. If the emotion persists longer, show it through **posture and micro-behavior**, not sustained facial excursion.

---

### C2 — Micro-motor Behavior (Aliveness Layer)

Characters not in active motion need involuntary micro-behaviors to avoid mannequin appearance. Add at least one per panel.

| Behavior | Cycle | Amplitude | Notes |
|---|---|---|---|
| Respiratory chest rise | 3–5s neutral; 2–3s stressed | 0.5–1.0 cm shoulder lift | Most overlooked; always add if character is still |
| Involuntary blink | Every 4–6s neutral; 2–3s anxious | Single eyelid closure | Helps with glassy-eye effect |
| Hand micro-tremor | Continuous background | 0.1–0.3 mm oscillation | Visible only in held/extended hand poses |
| Postural micro-drift | Every 2–4s | 0.2–0.5 cm weight shift | Body is never perfectly static |
| Swallow reflex | Every 15–30s neutral; 5–10s tense | Throat movement 0.5–1.0s | Add to tense/confrontational scenes |
| Gaze saccade | 2–5/s reading; 0.5–1/s conversation | Small eye movements | Prevents "staring doll" effect |

**Prompting pattern:** "While listening, she holds position — chest rises with a slow breath, fingers drift 2mm, blink at 3.5s."

---

### C3 — Breathing Mechanics

| State | Rate | Clip visibility | Prompt language |
|---|---|---|---|
| Neutral rest | 12–16/min → 1 breath / 3.75–5s | Barely visible | "Chest barely rises with slow breath" |
| Conversation | 14–18/min | Shoulders shift slightly | "Exhales through nose mid-sentence" |
| Tension / stress | 18–22/min → 2 breaths per 6s clip | Visible clavicle lift | "Shallow breath caught mid-word" |
| Post-exertion | 24–30/min | Heaving shoulders, visible | "Chest heaves, shoulders drop with each exhale" |

Do NOT write: "breathing heavily" for non-exertion scenes; "dramatic heave" unless post-sprint. Breathing is a **fill motion**, not an emotion marker.

---

### C4 — Gaze & Pupil Behavior

**Pupil dilation is INVISIBLE** in standard shots. Do not describe "pupils dilate/constrict" unless camera explicitly in EXTREME CLOSE-UP (eye fills frame).

**Natural gaze sequence in conversation:** face → eyes → mouth → hands → back to eyes. Gaze break (look away) happens 30–40% of speaking time; listeners maintain eye contact 60–70%.

**Saccade timing:**
- Processing / thinking: rapid micro-movements 2–5/s, NOT sustained blank stare
- Listening: stable with slow drift, periodic blink
- Suspicious/vigilant: gaze sweeps then locks — NOT continuous darting

**Prompting pattern:** "Eyes track from her face down to the documents, pause, then lift — brief gaze break at 2.5s as he processes."

---

### C5 — PROHIBITION LIST

The following elements are **FORBIDDEN** in `visual_start`, `visual_end`, `motion_prompt`, and `animation_instructions` **unless the screenplay explicitly scripted them**.

AI models add these automatically to emotional/tense/physical scenes. They always render uncanny at I2V resolution and frame rates.

| Forbidden Element | Why | If script requires |
|---|---|---|
| **Sweat** (dripping, beading, shiny skin, sweat-soaked clothing) | I2V renders as greasy texture artifact; destroys character consistency | Describe location only: "sweat at brow" — not dripping animation |
| **Tears** (tracks on cheek, glistening eyes, "eyes fill") | Liquid physics fail at I2V; creates smear artifact | Single tear only: "one tear traces cheekbone, pauses at jaw" |
| **Breath vapor / mouth condensation** (steamy exhale, visible breath cloud) | I2V cannot render translucent particulate; produces flicker/noise | Do not animate; use audio/voiceover only |
| **Any oral liquid** (saliva, drool, foam, spittle) | Added automatically to shouting/exertion; always uncanny | Never animate; cut away before impact |
| **"Glistening" / "flushed cheeks" / "feverish look"** | Implies fluid on skin; I2V renders as bloom artifact | Describe as "reddened", "heated", "tension visible" |
| **Sustained tears / sobbing flood** | Even if scripted: show one tear then cut; never animate continuous weeping | Scene cut after single tear established |

**Exception rule:** If an element above is a *plot-critical visual beat* (blood, specific liquid, etc.), describe it as a **static establishing detail** in `visual_start` only — do NOT include it in `motion_prompt` or `animation_instructions`.
