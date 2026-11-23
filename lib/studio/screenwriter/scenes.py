"""One scene through the four passes with continuity enforcement; one episode scene by scene."""
import json
import logging

from lib.core.utils import PANEL_COUNT_OPTIONS
from lib.llm.base import BaseLLM
from lib.studio import ledger, panel_lint, room_blocking
from lib.studio.screenwriter.enforce import (
    _enforce_ledger,
    _enforce_lint,
    _enforce_positions,
    canonical_contract,
    canonical_panel_refs,
    canonical_refs,
    unknown_ref_issues,
)
from lib.studio.screenwriter.episodes import (
    _episode_type_block,
    _extract_episode_exit,
    _get_location_anchors,
    _scope_refs_to_scene,
)
from lib.studio.screenwriter.passes import (
    _merge_scene_passes,
    _pass1_architecture,
    _pass1a_state,
    _pass1b_disposition,
    _pass2_visual,
    _pass3_motion_audio,
    _resolve_effective_char_info,
)

logger = logging.getLogger(__name__)


def generate_scene_4pass(
    scene_spec: dict,
    episode_context: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict,
    continuity_block: str,
    episode_type_block: str,
    prev_episode_exit: dict = None,
) -> dict | None:
    """
    Orchestrate 4-pass scene generation.
    Falls back to None on failure (caller should use legacy single-call path).
    prev_episode_exit: _extract_episode_exit of the previous scene (this episode's or the last episode's).
      visual_end → Pass 1; state → Pass 1A; Pass 1A is then checked against it by the ledger.
    """
    scene_id = scene_spec.get('scene_local_id', 1)
    logger.info(f"    🎬 4-pass generation: scene {scene_id}")

    character_info = _scope_refs_to_scene(character_info, ' '.join(
        scene_spec.get(k) or '' for k in ('location', 'initial_disposition', 'scene_instructions')))
    location_anchors = _get_location_anchors(character_info)
    if location_anchors:
        logger.debug(f"      📐 Anchors loaded: {list(location_anchors.keys())}")
    else:
        logger.warning("      ⚠️  No room anchor_points found — spatial positions may be inaccurate. Run room-anchors first.")

    p1 = _pass1_architecture(
        scene_spec, episode_context, prompts, config, llm,
        continuity_block, episode_type_block,
        prev_episode_exit=prev_episode_exit,
    )
    if not p1:
        return None
    logger.info(f"      ✅ Pass 1 done ({len(p1.get('panels', []))} panel stubs)")

    canonical_contract(scene_spec, character_info)

    def run_1a(correction=''):
        return canonical_refs(_pass1a_state(scene_spec, p1, prompts, config, llm, character_info, location_anchors,
                                            episode_context=episode_context, prev_episode_exit=prev_episode_exit,
                                            correction=correction), character_info)

    p1a = _enforce_lint(run_1a(), run_1a, lambda r: unknown_ref_issues(r, character_info), 'Pass 1A refs')
    p1a = _enforce_ledger(p1a, run_1a, scene_spec, prev_episode_exit, ledger.vehicle_names(character_info))
    if p1a:
        logger.info(f"      ✅ Pass 1A done ({len(p1a.get('panels', []))} states)")
    else:
        logger.warning("      ⚠️  Pass 1A skipped — proceeding without state")

    def run_1b(correction=''):
        return _pass1b_disposition(scene_spec, p1, p1a, prompts, llm, location_anchors, correction=correction,
                                   available_refs=character_info)

    aspect = (config.get('image_generation') or {}).get('aspect_ratio', '9:16')
    p1b = _enforce_positions(p1a, run_1b(), run_1b, scene_spec, character_info, aspect)
    if p1b:
        logger.info(f"      ✅ Pass 1B done ({len(p1b.get('panels', []))} camera/disposition entries)")
    else:
        logger.debug("      ⏭  Pass 1B skipped (no anchors or prompt) — Pass 2 will self-compute camera")

    # Substitute active variation refs for base character refs in Pass 2 char block
    effective_char_info = _resolve_effective_char_info(character_info, p1a)

    def run_2(correction=''):
        return _pass2_visual(scene_spec, p1, p1a, prompts, config, llm, effective_char_info, location_anchors,
                             episode_context=episode_context, p1b_result=p1b, correction=correction)

    p2 = run_2()
    if not p2:
        return None
    p2 = _enforce_lint(p2, run_2, lambda r: panel_lint.visual_issues(r, p1a, scene_id), 'Pass 2')
    logger.info(f"      ✅ Pass 2 done ({len(p2.get('panels', []))} visuals)")

    def run_3(correction=''):
        return _pass3_motion_audio(scene_spec, p1, p1a, p2, prompts, config, llm,
                                   episode_context=episode_context, correction=correction)

    p3 = run_3()
    if not p3:
        return None
    p3 = _enforce_lint(p3, run_3, lambda r: panel_lint.motion_issues(r, scene_id), 'Pass 3')
    logger.info(f"      ✅ Pass 3 done ({len(p3.get('panels', []))} motion/audio entries)")

    merged = _merge_scene_passes(scene_spec, p1, p1a, p2, p3, p1b_result=p1b)
    canonical_panel_refs(merged, character_info)
    room_blocking.annotate([merged], character_info.get, aspect)
    logger.info(f"      ✅ Merged: {len(merged.get('panels', []))} panels")
    return merged


# ---------------------------------------------------------------------------
# Scene keyframe generation
# ---------------------------------------------------------------------------
def analyze_scenes_for_episode(
    episode_counter: int,
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    all_episodes: list,
    character_info: dict = None,
    prev_continuity_rules: str = None,
    prev_active_questions: dict = None,
    prev_episode_exit: dict = None,
):
    logger.info(f"\n🎥 MASTER CINEMATOGRAPHER: Preparing Keyframes for episode {episode_counter}...")

    # Extract episode metadata
    try:
        episode_data = json.loads(text)
        current_continuity = episode_data.get('visual_continuity_rules', '')
        episode_type = episode_data.get('episode_type', '')
        pov_character = episode_data.get('pov_character', '')
    except (json.JSONDecodeError, AttributeError):
        episode_data = {}
        current_continuity = ''
        episode_type = ''
        pov_character = ''

    continuity_block = ""
    if prev_continuity_rules:
        continuity_block += (
            f"\n## VISUAL CONTINUITY FROM PREVIOUS EPISODE — MANDATORY\n"
            f"These rules MUST be enforced in every panel of this episode:\n{prev_continuity_rules}\n"
        )
    if current_continuity:
        continuity_block += (
            f"\n## THIS EPISODE'S VISUAL STATE (carry forward to future scenes)\n{current_continuity}\n"
        )
    active_questions = episode_data.get('active_questions', {})
    if active_questions:
        q_lines = []
        for key, label in [('macro', 'MACRO'), ('episode', 'EPISODE'), ('scene', 'SCENE')]:
            val = active_questions.get(key, '')
            if val:
                q_lines.append(f"  {label}: {val}")
        planted = active_questions.get('planted_this_episode', '')
        if planted:
            q_lines.append(f"  PLANTED (pay off within 3 episodes): {planted}")
        if q_lines:
            continuity_block += (
                "\n## ACTIVE DRAMATIC QUESTIONS — keep these alive in panels\n"
                "Do NOT resolve the MACRO question. SCENE question should be visible through action/reaction:\n"
                + "\n".join(q_lines) + "\n"
            )
    if prev_active_questions:
        prev_planted = prev_active_questions.get('planted_this_episode', '')
        if prev_planted:
            continuity_block += (
                f"\n## PREVIOUSLY PLANTED QUESTIONS — must remain visibly alive or pay off this episode\n"
                f"  {prev_planted}\n"
            )

    episode_type_block = _episode_type_block(episode_type, pov_character, prompts, config)

    # Resolve scenes_spec: new format has scenes[], old format has screenplay_instructions
    scenes_spec = episode_data.get('scenes', [])
    if not scenes_spec:
        # Compat shim: old-format episode without scenes[] — synthesize a single scene
        panel_count_options = config['format'].get('panel_count_options', PANEL_COUNT_OPTIONS)
        default_count = 9 if 9 in panel_count_options else panel_count_options[-1]
        scenes_spec = [{
            'scene_local_id': 1,
            'location': episode_data.get('location', ''),
            'panel_count': default_count,
            'scene_instructions': episode_data.get('screenplay_instructions', ''),
        }]
        logger.debug(f"  Episode {episode_counter}: no scenes[] found — using compat single-scene ({default_count} panels)")

    # Strip keys that go into scene-level context to avoid confusion
    episode_context = {
        k: v for k, v in episode_data.items()
        if k not in ('scenes', 'screenplay_instructions')
    }

    all_raw_scenes = []
    for scene_spec in scenes_spec:
        scene_id = scene_spec.get('scene_local_id', 1)
        exit_ctx = _extract_episode_exit({'scenes': all_raw_scenes[-1:]}) if all_raw_scenes else prev_episode_exit
        if scene_spec.get('transition_in') == 'new_location':
            exit_ctx = None  # a declared cut elsewhere: no positions to carry
        scene = generate_scene_4pass(
            scene_spec=scene_spec,
            episode_context=episode_context,
            prompts=prompts,
            config=config,
            llm=llm,
            character_info=character_info,
            continuity_block=continuity_block,
            episode_type_block=episode_type_block,
            prev_episode_exit=exit_ctx,
        )
        if scene:
            scene['episode_id'] = episode_counter
            all_raw_scenes.append(scene)
        else:
            logger.error(f"❌ 4-pass failed for episode {episode_counter}, scene {scene_id} — skipping")

    all_episodes.append((episode_counter, {'scenes': all_raw_scenes}))
    logger.info(f"CINEMATOGRAPHER: Ready Keyframes for episode {episode_counter}")
