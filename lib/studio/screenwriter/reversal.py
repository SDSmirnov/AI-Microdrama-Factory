"""Reversal pass: reversed motion and an explicit start frame for panels filmed backwards."""
import json
import logging

from lib.core.schemas import (
    REVERSAL_SCHEMA,
)
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reversal pass
# ---------------------------------------------------------------------------
def apply_reversal_pass(scene: dict, prompts: dict, config: dict, llm: BaseLLM) -> dict:
    reversed_panels = [p for p in scene.get('panels', []) if p.get('is_reversed', False)]
    if not reversed_panels:
        return scene

    logger.info(f"    🔄 Reversal pass: {len(reversed_panels)} panel(s) flagged in scene {scene.get('scene_id', '?')}")

    setting_context = prompts.get('setting', '')
    panels_context = json.dumps(reversed_panels, ensure_ascii=False, indent=2)
    scene_trajectories = scene.get('scene_trajectories', [])
    trajectories_context = (
        f"\nSCENE TRAJECTORIES (emotional arcs — use to ensure visual_start_explicit matches "
        f"the declared emotional state at the reversal panel):\n"
        f"{json.dumps(scene_trajectories, ensure_ascii=False, indent=2)}\n"
    ) if scene_trajectories else ""
    duration = config['format'].get('panel_duration_s', 6)
    hold_s   = 0.4  # hold at both ends of forward clip for clean retrograde head/tail
    prompt = f"""
You are a Master Cinematographer choreographing RETROGRADE MOTION clips for AI video generation.

RETROGRADE MOTION: the AI renders a forward clip; the clip is inverted frame-by-frame in post
so the viewer perceives time running backwards. Every physical choice you make must be designed
to produce a specific perceptual result when played in retrograde.

  - visual_start = what the viewer sees at t=0 after retrograde inversion (the hidden / before-state)
  - visual_end   = what the viewer sees at the end after retrograde inversion (the revealed / after-state)

You must generate TWO things per panel:

1. motion_prompt_reversed — describes the FORWARD clip the AI will render.
   The forward clip runs from visual_end state → visual_start state.
   In retrograde playback the viewer perceives visual_start → visual_end.

2. visual_start_explicit — a fully explicit rewrite of visual_end (which becomes the first
   frame visible to the viewer after retrograde inversion). Required because the original
   visual_end may be vague or lack technical camera details.
   Must include: shot type (ECU/CU/MS/MLS/LS), camera angle, character position in frame,
   key props, lighting state. Zero implicit references.

━━━ RETROGRADE MOTION DESIGN PRINCIPLES ━━━

Hold frames (mandatory):
  Begin the forward clip with a {hold_s}s STATIC HOLD at visual_end state — frozen, no motion.
  End  the forward clip with a {hold_s}s STATIC HOLD at visual_start state — frozen, no motion.
  These become clean head/tail in retrograde and prevent jarring cuts.

Choose retrograde-effective action types:
  ENTRY  (retrograde reveals): forward clip = character walks AWAY from camera to distance / exits
         through door → retrograde shows smooth approach / entry. Best for character arrivals.
  RISE   (retrograde reveals): forward clip = character sits DOWN into chair → retrograde = rising.
  DRAW   (retrograde reveals): forward clip = weapon/object returned to holster/pocket → retrograde = draw.
  ASSEMBLE (retrograde reveals): forward clip = object breaks apart / liquid spills →
         retrograde = assembly / pour. Exploits retrograde physics (particles, liquids).
  CONCEAL (retrograde reveals): forward clip = cloth draped over object, lights dimmed →
         retrograde = cloth lifts, lights come up.
  CLOSE  (retrograde reveals): forward clip = door/curtain swings SHUT → retrograde = it opens.

Retrograde physics — design for them explicitly:
  Fabric:   settling drape / fabric dropping onto surface → retrograde: fabric lifts and billows.
  Liquid:   pour into container → retrograde: liquid rises out. Use slow, controlled pours.
  Smoke/breath: exhale cloud expanding → retrograde: cloud contracts back to lips.
  Gravity:  object placed on table with slight bounce → retrograde: object lifts off.
  Hair:     hair falls forward over face → retrograde: hair sweeps back dramatically.

Body mechanics (mandatory precision):
  - Name the exact limb at every beat: "reaches with RIGHT hand", "steps with LEFT foot"
  - State face direction every beat: "facing camera", "3/4 profile left", "back to camera"
  - Sequence every movement beat explicitly: weight shift → reach → grip → step → pivot
  - Full travel for entries/exits: from full-frame presence to partial frame edge (or vice versa)
  - Velocity gradient: start at low speed, hold steady — abrupt starts/stops destroy retrograde illusion

Forbidden patterns (break retrograde illusion):
  ✗ Blinking or eye movements (asymmetric in retrograde)
  ✗ Talking / mouth movement (speech retrograde reads as alien)
  ✗ Multiple simultaneous moving elements (chaos — pick one primary motion)
  ✗ Rapid cuts or camera moves (must be continuous, locked or single slow push/pull)
  ✗ Ambient crowd motion in background (people retrograde looks absurd)

━━━ EXAMPLE ━━━

  visual_start: "Closed office door, empty hallway."
  visual_end:   "Secretary inside room, door open, colleagues laughing in background."

  → motion_prompt_reversed (forward: inside → outside, retrograde-designed):
    "RETROGRADE ENTRY. MS locked camera from room corner, warm overhead light.
    0s–0.4s: HOLD — Secretary stands center-frame just inside doorway, coat fully settled,
    right hand at side, colleagues blurred mid-laugh over her right shoulder. Static freeze.
    0.4s: She turns head LEFT toward door, shifts weight onto LEFT foot — slow, deliberate.
    1.2s: Reaches forward with RIGHT hand, index finger extended, grips door handle.
    2s: Steps backward across threshold with RIGHT foot — torso crosses doorframe centerline.
    2.8s: LEFT foot follows; she is now fully in hallway, face turned INTO the room,
    left hand trailing on door edge.
    3.8s: She pulls door steadily CLOSED — door swings toward camera in smooth arc.
    5.2s: Door clicks shut; hallway empty, closed door fills frame.
    5.2s–5.6s: HOLD — closed door, empty hallway, no motion. Static freeze."

  → visual_start_explicit:
    "MS locked shot from room corner — Secretary center-frame just inside doorway, coat
    fully settled, right hand at side, colleagues soft-focus over her right shoulder,
    warm office overhead lighting, door fully open to left of frame."

━━━ RULES ━━━
- motion_prompt_reversed: 120+ words, explicit timestamps, all verbs forward-plausible
- Label clip type at the top: "RETROGRADE ENTRY", "RETROGRADE RISE", "RETROGRADE DRAW", etc.
- Do NOT invent visual elements beyond the two provided states
- Preserve all lighting and camera details from lights_and_camera
- Duration: {duration}s total (including {hold_s}s holds at each end)

{setting_context}
{trajectories_context}
PANELS TO PROCESS:
{panels_context}
"""

    result = llm.make_json(prompt, REVERSAL_SCHEMA)

    if result:
        # result may be a list (schema is array) or dict with list
        items = result if isinstance(result, list) else result.get('items', [])
        reversed_map = {item['panel_index']: item for item in items}
        for p in scene.get('panels', []):
            if p.get('is_reversed', False) and p['panel_index'] in reversed_map:
                item = reversed_map[p['panel_index']]
                p['motion_prompt_original'] = p['motion_prompt']
                p['motion_prompt'] = item['motion_prompt_reversed']
                original_start = p['visual_start']
                original_end   = p['visual_end']
                p['visual_start'] = item.get('visual_start_explicit') or original_end
                p['visual_end']   = original_start
                logger.info(f"      ✅ Panel {p['panel_index']}: motion_prompt_reversed generated")
            elif p.get('is_reversed', False):
                logger.info(f"      ⚠️  Panel {p['panel_index']}: no motion_prompt_reversed returned by LLM")
    else:
        logger.error(f"      ❌ Reversal LLM call returned empty for scene {scene.get('scene_id', '?')}")

    return scene
