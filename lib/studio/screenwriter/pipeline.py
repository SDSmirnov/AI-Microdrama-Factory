"""Pipeline driver: scenes per episode with checkpoints, merged into animation_metadata.json."""
import json
import logging
import os
import tempfile
from pathlib import Path

from lib.core.state import ProjectState
from lib.core.utils import DEFAULT_OUTPUT_DIR
from lib.llm.base import BaseLLM
from lib.studio.screenwriter.episodes import (
    _extract_episode_exit,
    analyze_episodes_master,
)
from lib.studio.screenwriter.reversal import apply_reversal_pass
from lib.studio.screenwriter.scenes import analyze_scenes_for_episode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Checkpoint writer
# ---------------------------------------------------------------------------
def _write_episode_checkpoint(episode_counter: int, scenes: list, output_dir: Path):
    """Atomically write all refined scenes for an episode to its checkpoint file."""
    out_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}_refined.json"
    content = json.dumps({'scenes': scenes}, ensure_ascii=False, indent=2)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=output_dir, suffix='.json.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Single scene processing
# ---------------------------------------------------------------------------
def process_single_scene(
    episode_counter: int,
    scene_id: int,
    scene: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    all_scenes: list,
    output_dir: Path = None,
) -> dict:
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    scene['scene_id'] = scene_id
    scene['episode_id'] = episode_counter
    for idx, panel in enumerate(scene.get('panels', []), 1):
        panel['panel_index'] = idx
        panel.setdefault('is_reversed', False)
        panel.setdefault('motion_prompt_reversed', '')
        panel.setdefault('motion_intent', '')
        panel.setdefault('voiceover', '')
        panel.setdefault('voiceover_settings', {})
        panel.setdefault('emotional_beat', '')
        panel.setdefault('hook_type', 'none')
        panel.setdefault('text_safe_composition', True)
        panel.setdefault('panel_type', 'narrative')
        panel.setdefault('transition_to_next', 'hard_cut')
        panel.setdefault('sound_design', 'silence')
        panel.setdefault('location_references', [])
        panel.setdefault('visual_disposition', '')

    if config.get('animation', {}).get('reversal_pass', True):
        scene = apply_reversal_pass(scene, prompts, config, llm)
    else:
        # Reversal pass disabled: clear is_reversed so downstream animation/render
        # treats all panels as forward clips.
        for panel in scene.get('panels', []):
            panel['is_reversed'] = False
            panel['motion_prompt_reversed'] = ''
        logger.info(f"      ⏭  Scene {scene['scene_id']}: reversal pass disabled — all panels treated as forward")

    all_scenes.append(scene)
    return scene


# ---------------------------------------------------------------------------
# Sequential scenes pipeline (used by cli.py `scenes` subcommand)
# ---------------------------------------------------------------------------
def run_scenes_pipeline(
    episodes: list,
    episodes_list: list,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    output_dir: Path,
    character_info: dict = None,
    state: ProjectState | None = None,
    resume: bool = False,
) -> list:
    """
    Process a filtered list of episodes sequentially:
      analyze → reversal → write checkpoint per episode.
    Returns all_scenes (list of scene dicts, mutated in place by process_single_scene).

    With resume=True and a ProjectState, episodes whose reversal checkpoint is already
    marked done are loaded from disk instead of re-running.
    """
    all_episodes: list = []
    continuity_map = {ep['episode_id']: episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else '' for i, ep in enumerate(episodes_list)}
    active_questions_map = {ep['episode_id']: episodes_list[i - 1].get('active_questions', {}) if i > 0 else {} for i, ep in enumerate(episodes_list)}

    prev_episode_exit: dict | None = None  # exit context (visual_end + state) from previous episode
    for ep in episodes:
        ep_id = ep['episode_id']
        # Phase 1 skip: raw analysis already done — load raw checkpoint
        if resume and state and state.episode_raw_done(ep_id):
            raw_path = output_dir / f"animation_episode_scenes_{ep_id:03d}.json"
            if raw_path.exists():
                try:
                    loaded = json.loads(raw_path.read_text(encoding='utf-8'))
                    all_episodes.append((ep_id, loaded))
                    prev_episode_exit = _extract_episode_exit(loaded)
                    logger.info(f"⏭  Episode {ep_id}: raw checkpoint loaded (skipping LLM analysis)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_id}: raw checkpoint unreadable ({exc}), re-analyzing")
        prev_rules = continuity_map.get(ep_id, '')
        analyze_scenes_for_episode(
            ep_id, json.dumps(ep, ensure_ascii=False, indent=2),
            prompts, config, llm, all_episodes,
            character_info=character_info,
            prev_continuity_rules=prev_rules,
            prev_active_questions=active_questions_map.get(ep_id, {}),
            prev_episode_exit=prev_episode_exit,
        )
        # Update exit context from the episode we just analyzed
        if all_episodes and all_episodes[-1][0] == ep_id:
            prev_episode_exit = _extract_episode_exit(all_episodes[-1][1])

    ep_scenes_map: dict = {}
    scene_counter = 0
    for ep_counter, data in sorted(all_episodes, key=lambda x: x[0]):
        ep_scenes_map[ep_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scenes_map[ep_counter].append((scene_counter, scene))

    all_scenes: list = []
    for ep_counter, scene_list in sorted(ep_scenes_map.items()):
        # Phase 2 skip: checkpoint already done — load from disk
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: reversal checkpoint loaded (skipping)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: checkpoint unreadable ({exc}), re-running")

        ep_processed: list = []
        for sc_id, scene in scene_list:
            ep_processed.append(process_single_scene(
                ep_counter, sc_id, scene, prompts, config, llm, all_scenes,
                output_dir=output_dir,
            ))
        if ep_processed:
            try:
                _write_episode_checkpoint(ep_counter, ep_processed, output_dir)
                if state:
                    state.mark_episode_refined_done(ep_counter)
            except Exception as e:
                logger.warning(f"⚠️  Could not write checkpoint for episode {ep_counter}: {e}")

    return all_scenes


# ---------------------------------------------------------------------------
# Scene merge / upsert
# ---------------------------------------------------------------------------
def merge_scenes(
    old_metadata: dict,
    new_scenes: list,
    new_ep_ids: set,
    panels_dir: Path,
) -> list:
    """
    Upsert new_scenes into old_metadata['scenes'], preserving scene_ids where possible
    so that panels/<NNN>_*.png filenames remain valid.

    - If the number of scenes for the replaced episodes is unchanged, old scene_ids are reused.
    - If the count changed, new sequential IDs are assigned and orphaned panel files are logged.
    Returns the merged, sorted list of scenes.
    """
    old_scenes = old_metadata.get('scenes', [])
    kept = [s for s in old_scenes if s.get('episode_id') not in new_ep_ids]
    old_ep_scene_ids = sorted(
        s['scene_id'] for s in old_scenes if s.get('episode_id') in new_ep_ids
    )
    merged = sorted(kept, key=lambda s: s.get('scene_id', 0))

    if len(new_scenes) == len(old_ep_scene_ids):
        for scene, sid in zip(new_scenes, old_ep_scene_ids):
            scene['scene_id'] = sid
        merged = sorted(merged + new_scenes, key=lambda s: s.get('scene_id', 0))
    else:
        if old_ep_scene_ids:
            logger.warning(
                f"Scene count changed for episode(s) {sorted(new_ep_ids)}: "
                f"{len(old_ep_scene_ids)} old → {len(new_scenes)} new. "
                f"Panels for old scene_ids {old_ep_scene_ids} may be orphaned."
            )
            orphaned = sorted(
                p for sid in old_ep_scene_ids
                for p in panels_dir.glob(f"{sid:03d}_*.png")
            )
            if orphaned:
                logger.warning(
                    f"  Orphaned panel files ({len(orphaned)}): "
                    + ", ".join(p.name for p in orphaned)
                )
        next_id = (max(s['scene_id'] for s in merged) + 1) if merged else 1
        for scene in new_scenes:
            scene['scene_id'] = next_id
            next_id += 1
            merged.append(scene)

    return merged


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def analyze_scenes_master(
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict = None,
    output_dir: Path = None,
    state: ProjectState | None = None,
    resume: bool = False,
    episodes_only: bool = False,
) -> dict:
    """
    Full pipeline: episodes → scenes → reversal → save JSONs.
    Returns {'scenes': [...]}.

    With resume=True and a ProjectState, each completed phase is skipped and
    loaded from its checkpoint file:
      - Phase 1 (episodes):  skipped if state.episodes_done()  → load animation_episodes.json
      - Phase 2 (raw/ep):    skipped if state.episode_raw_done(N) → load animation_episode_scenes_NNN.json
      - Phase 3 (reversal/ep): skipped if state.episode_refined_done(N) → load *_refined.json
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: episode breakdown ────────────────────────────────────────────
    episodes_path = output_dir / "animation_episodes.json"
    if resume and state and state.episodes_done() and episodes_path.exists():
        try:
            episodes = json.loads(episodes_path.read_text(encoding='utf-8'))
            logger.info("⏭  Phase 1: episode breakdown loaded from checkpoint (skipping LLM)")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"⚠️  Episode checkpoint unreadable ({exc}), re-generating")
            episodes = None
    else:
        episodes = None

    if episodes is None:
        episodes = analyze_episodes_master(text, prompts, config, llm, character_info=character_info)
        if not episodes:
            raise RuntimeError(
                "analyze_episodes_master returned None or empty — check LLM response and API key"
            )
        episodes_path.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding='utf-8')
        if state:
            state.mark_episodes_done(len(episodes.get('episodes', [])))
    logger.debug(episodes)

    if episodes_only:
        logger.info("✅ animation_episodes.json written — stopping (episodes-only mode).")
        return None

    all_scenes: list = []
    all_episodes: list = []

    episodes_list = episodes.get('episodes', [])
    continuity_map = {ep['episode_id']: episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else '' for i, ep in enumerate(episodes_list)}
    active_questions_map = {ep['episode_id']: episodes_list[i - 1].get('active_questions', {}) if i > 0 else {} for i, ep in enumerate(episodes_list)}

    # ── Phase 2: raw scene analysis (sequential — prev_episode_exit threaded) ────
    failed_episodes = []
    prev_episode_exit: dict | None = None

    for i, episode in enumerate(episodes_list):
        episode_counter = episode.get('episode_id', i + 1)
        if resume and state and state.episode_raw_done(episode_counter):
            raw_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}.json"
            if raw_path.exists():
                try:
                    data = json.loads(raw_path.read_text(encoding='utf-8'))
                    all_episodes.append((episode_counter, data))
                    prev_episode_exit = _extract_episode_exit(data)
                    logger.info(f"⏭  Episode {episode_counter}: raw checkpoint loaded (skipping LLM analysis)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {episode_counter}: raw checkpoint unreadable ({exc}), re-analyzing")
        try:
            analyze_scenes_for_episode(
                episode_counter, json.dumps(episode, ensure_ascii=False, indent=2),
                prompts, config, llm, all_episodes,
                character_info=character_info,
                prev_continuity_rules=continuity_map.get(episode_counter, ''),
                prev_active_questions=active_questions_map.get(episode_counter, {}),
                prev_episode_exit=prev_episode_exit,
            )
            if all_episodes and all_episodes[-1][0] == episode_counter:
                prev_episode_exit = _extract_episode_exit(all_episodes[-1][1])
                # Checkpoint immediately — don't wait for the batch write after the loop
                raw_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}.json"
                raw_path.write_text(json.dumps(all_episodes[-1][1], ensure_ascii=False, indent=2), encoding='utf-8')
                if state and not state.episode_raw_done(episode_counter):
                    state.mark_episode_raw_done(episode_counter)
                logger.info(f"  💾 Episode {episode_counter}: raw checkpoint written")
        except Exception as e:
            logger.error(f"❌ Episode {episode_counter} scene analysis failed: {e}")
            failed_episodes.append(episode_counter)

    if failed_episodes:
        total = len(episodes_list)
        logger.warning(f"⚠️  {len(failed_episodes)}/{total} episode(s) failed analysis: {failed_episodes}")
        if len(failed_episodes) >= total:
            raise RuntimeError(f"All {total} episodes failed scene analysis — aborting pipeline")

    all_episodes = sorted(all_episodes, key=lambda e: e[0])

    # Assign global scene IDs. Raw checkpoints were already written per-episode above.
    scene_counter = 0
    ep_scene_groups: dict = {}  # {episode_counter: [(scene_id, scene), ...]}

    for episode_counter, data in all_episodes:
        logger.info(f"Processing episode: {episode_counter} scene start: {scene_counter}")
        ep_scene_groups[episode_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scene_groups[episode_counter].append((scene_counter, scene))

    # ── Phase 3: reversal pass (sequential — cross-episode order preserved) ──────
    failed_scenes = []
    for ep_counter in sorted(ep_scene_groups):
        # Skip if checkpoint already committed
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: reversal checkpoint loaded (skipping)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: checkpoint unreadable ({exc}), re-running")

        ep_processed: list = []
        for sc_id, scene in ep_scene_groups[ep_counter]:
            try:
                ep_processed.append(process_single_scene(
                    ep_counter, sc_id, scene, prompts, config, llm,
                    all_scenes, output_dir,
                ))
            except Exception as e:
                logger.error(f"❌ Scene {sc_id} processing failed: {e}")
                failed_scenes.append(sc_id)
        if ep_processed:
            try:
                _write_episode_checkpoint(ep_counter, ep_processed, output_dir)
                if state:
                    state.mark_episode_refined_done(ep_counter)
            except Exception as e:
                logger.warning(f"⚠️  Could not write checkpoint for episode {ep_counter}: {e}")

    all_scenes = sorted(all_scenes, key=lambda s: s['scene_id'])
    return {'scenes': all_scenes}
