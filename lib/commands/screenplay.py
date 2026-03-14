"""Screenplay commands: screenplay, scenes, consistency, summary, split-book."""
import argparse
import json
import logging
import sys
from pathlib import Path

from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import Project, load_project
from lib.core.prompts import PROMPTING_DIR
from lib.core.state import ProjectState
from lib.core.utils import atomic_write
from lib.studio.artist import export_image_prompt, load_character_refs
from lib.studio.director import run_continuity_pass
from lib.studio.screenwriter import (
    analyze_scenes_master, merge_scenes, process_single_scene, run_scenes_pipeline,
    _write_episode_checkpoint,
)

logger = logging.getLogger(__name__)


def cmd_screenplay(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    load_character_refs(project)

    resume = getattr(args, 'resume', False)
    state = ProjectState.load(project.state_path())

    text = Path(args.novel).read_text(encoding='utf-8')
    data = analyze_scenes_master(
        text, prompts, config, llm,
        max_workers=project.max_workers,
        character_info=project.character_info,
        output_dir=project.output_dir,
        state=state,
        resume=resume,
    )
    if not data or 'scenes' not in data:
        logger.error("❌ Failed to generate screenplay.")
        sys.exit(1)

    data.setdefault('config', config)
    meta_path = project.output_dir / "animation_metadata.json"
    atomic_write(meta_path, json.dumps(data, ensure_ascii=False, indent=2))
    for scene in data['scenes']:
        export_image_prompt(scene, scene['scene_id'], prompts, config, project)
    logger.info(f"\n✅ Done. JSONs in {project.output_dir}/, prompts in {project.image_prompts_dir}/")


def cmd_scenes(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    load_character_refs(project)

    episodes_path = project.output_dir / "animation_episodes.json"
    if not episodes_path.exists():
        logger.error("❌ animation_episodes.json not found. Run 'screenplay' first.")
        sys.exit(1)

    episodes_data = json.loads(episodes_path.read_text(encoding='utf-8'))
    episodes_list = episodes_data.get('episodes', [])

    scene_arg = args.scene if hasattr(args, 'scene') else 'all'
    if scene_arg != 'all':
        try:
            target = int(scene_arg)
        except ValueError:
            logger.error(f"❌ Invalid scene number: {scene_arg!r}. Expected an integer.")
            sys.exit(1)
        episodes = [e for e in episodes_list if e.get('episode_id') == target]
    else:
        episodes = episodes_list

    resume = getattr(args, 'resume', False)
    state = ProjectState.load(project.state_path())

    all_scenes = run_scenes_pipeline(
        episodes, episodes_list, prompts, config, llm,
        output_dir=project.output_dir,
        character_info=project.character_info,
        state=state,
        resume=resume,
    )
    logger.info(f"\n✅ Done. {len(all_scenes)} scene(s) processed.")
    if not all_scenes:
        return

    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"❌ Corrupt animation_metadata.json: {e}. Back up and delete the file before retrying.")
            sys.exit(1)
    else:
        metadata = {}

    new_ep_ids = {s.get('episode_id') for s in all_scenes if s.get('episode_id')}
    metadata['scenes'] = merge_scenes(metadata, all_scenes, new_ep_ids, project.panels_dir)
    metadata.setdefault('config', config)
    atomic_write(meta_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    logger.info(f"✅ animation_metadata.json updated: {len(metadata['scenes'])} total scene(s)")


def cmd_consistency(args):
    project = Project()
    project.ensure_dirs()
    llm = _make_vision_llm(args.llm, project)
    dry_run = args.dry_run
    if dry_run:
        logger.info("ℹ️  Dry-run mode: ref JSONs will be enriched but PNGs will NOT be regenerated. Run `make refs` to render.")
    out = run_continuity_pass(llm, ref_dir=project.ref_dir, max_workers=project.max_workers, output_dir=project.output_dir, dry_run=dry_run)
    logger.info(f"✅ animation_metadata.json updated in-place: {out}")


def cmd_summary(args):
    project, _, _ = load_project(style=args.style)
    llm = _make_llm(args.llm, project)

    novel_text = Path(args.novel).read_text(encoding='utf-8')

    meta_path = project.output_dir / "animation_metadata.json"
    scenes_block = ""
    cliffhanger_info = ""
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        scenes = metadata.get('scenes', [])
        scene_summaries = []
        for scene in scenes:
            panels = scene.get('panels', [])
            panel_texts = []
            for p in panels:
                hook = p.get('hook_type', '')
                parts = [f"[{hook}]" if hook else "", p.get('visual_start', ''), p.get('visual_end', '')]
                dlg = p.get('dialogue', '') or p.get('voiceover', '') or p.get('caption', '')
                if dlg:
                    parts.append(f"[{dlg}]")
                panel_texts.append(" → ".join(t for t in parts if t))
            scene_summaries.append(
                f"Scene {scene['scene_id']} [{scene.get('location', '')}]:\n"
                + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(panel_texts))
            )
        scenes_block = "\n\n".join(scene_summaries)
        # Extract cliffhanger info from the final panel of the last scene
        if scenes:
            last_p = (scenes[-1].get('panels', [None]))[-1]
            if last_p:
                cliffhanger_info = (
                    f"hook_type: {last_p.get('hook_type', 'unknown')}\n"
                    f"visual_end: {last_p.get('visual_end', '')}\n"
                    f"emotional_beat: {last_p.get('emotional_beat', '')}"
                )

    refs_block = ""
    ref_dir = project.ref_dir
    if ref_dir.exists():
        refs = []
        for rj in sorted(ref_dir.glob("*.json")):
            try:
                d = json.loads(rj.read_text(encoding='utf-8'))
                name = d.get('name') or rj.stem
                desc = d.get('visual_description') or d.get('description') or ''
                state = d.get('state') or d.get('current_state') or ''
                refs.append(f"- {name}: {desc}" + (f" [{state}]" if state else ""))
            except Exception:
                pass
        refs_block = "\n".join(refs)

    prompt = f"""You are a production continuity writer.
Given the source text of the current chapter and the visual scenes produced for it,
write a **Chapter Summary** that will be used as context when generating the NEXT chapter.

The summary must cover:
1. **Plot state** — what happened, key events, unresolved conflicts
2. **Character states** — who is where, what changed for each character, emotional arc
3. **Visual continuity** — established looks, key locations, lighting/color palette, camera style
4. **Narrative thread** — the cliffhanger or setup that carries into the next chapter
5. **Production notes** — any visual motifs, recurring symbols, tone to maintain
6. **Cliffhanger chain** — classify the episode-ending cliffhanger by type and recommend what type to use NEXT to avoid audience fatigue. Types: physical_threat (use sparingly — fatigue risk), revelation (needs logical setup), emotional_rupture (betrayal/unexpected silence), interrupted_action (lowest intensity, safest for routine transitions). Rotate — never repeat the same type twice in a row.

Be precise, concise, and production-ready. Write in Russian.
This summary will be injected verbatim into the next chapter prompt.

---
## SOURCE TEXT (current chapter)

{novel_text}

---
## PRODUCED SCENES

{scenes_block or "(no scenes data available)"}

---
## EPISODE-ENDING CLIFFHANGER (final panel)

{cliffhanger_info or "(no cliffhanger data available)"}

---
## CHARACTER REFERENCES

{refs_block or "(no character refs available)"}

RETURN JSON, CONTENTS IN RUSSIAN:
{{
    "current_logline": "logline state from the start to the moment",
    "plot_state": "what happened, key events, unresolved conflicts",
    "character_states": "who is where, what changed for each character, emotional arc",
    "visual_continuity": "established looks, key locations, lighting/color palette, camera style",
    "narrative_thread": "the cliffhanger or setup that carries into the next chapter",
    "production_notes": "any visual motifs, recurring symbols, tone to maintain",
    "cliffhanger_chain": {{
        "last_type": "one of: physical_threat | revelation | emotional_rupture | interrupted_action",
        "last_description": "one sentence: what exactly the cliffhanger showed",
        "avoid_next": "the type(s) to avoid in the next episode to prevent fatigue",
        "recommend_next": "the recommended cliffhanger type for the next episode and why"
    }},
    "summary_notes": "detailed summary for context"
}}
"""

    result = llm.make_json(prompt)
    if not result:
        logger.error("❌ LLM returned empty summary")
        sys.exit(1)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"✅ Summary written to {out_path}")


def cmd_reverse_refine(args):
    """Refine + reversal pass on an already-generated raw episode JSON, then upsert into metadata."""
    try:
        ep_num = int(args.scene)
    except (ValueError, TypeError):
        logger.error("❌ SCENE must be an integer episode number.")
        sys.exit(1)

    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    load_character_refs(project)

    raw_path = project.output_dir / f"animation_episode_scenes_{ep_num:03d}.json"
    if not raw_path.exists():
        logger.error(f"❌ {raw_path} not found. Run 'make scenes SCENE={ep_num}' first.")
        sys.exit(1)

    raw = json.loads(raw_path.read_text(encoding='utf-8'))
    scenes = raw.get('scenes', [])
    if not scenes:
        logger.error(f"❌ No scenes found in {raw_path}.")
        sys.exit(1)

    all_scenes: list = []
    prev_terminal: str | None = None
    for idx, scene in enumerate(scenes, 1):
        refined = process_single_scene(
            ep_num, idx, scene, prompts, config, llm, all_scenes,
            output_dir=project.output_dir,
            character_info=project.character_info,
            prev_scene_terminal=prev_terminal,
        )
        if refined:
            last_panel = max(
                refined.get('panels', []),
                key=lambda p: p.get('panel_index', 0),
                default=None,
            )
            if last_panel:
                prev_terminal = last_panel.get('visual_end', '')

    _write_episode_checkpoint(ep_num, all_scenes, project.output_dir)
    state = ProjectState.load(project.state_path())
    state.mark_episode_refined_done(ep_num)
    logger.info(f"✅ Wrote animation_episode_scenes_{ep_num:03d}_refined.json")

    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"❌ Corrupt animation_metadata.json: {e}.")
            sys.exit(1)
    else:
        metadata = {}

    new_ep_ids = {s.get('episode_id') for s in all_scenes if s.get('episode_id')}
    metadata['scenes'] = merge_scenes(metadata, all_scenes, new_ep_ids, project.panels_dir)
    metadata.setdefault('config', config)
    atomic_write(meta_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    logger.info(f"✅ animation_metadata.json updated: {len(metadata['scenes'])} total scene(s)")


def cmd_split_book(args):
    from lib.studio.bookbinder import split_book

    project, _, _ = load_project(style=args.style)

    prompt_path = PROMPTING_DIR / args.style / "book-shrinker.md"
    if not prompt_path.exists():
        logger.error(
            f"❌ book-shrinker.md not found for style '{args.style}' at {prompt_path}"
        )
        sys.exit(1)
    shrinker_prompt = prompt_path.read_text(encoding="utf-8")

    llm = _make_llm(args.llm, project)
    text = Path(args.novel).read_text(encoding="utf-8")
    out_dir = Path(args.output_dir)

    try:
        files = split_book(text, llm, shrinker_prompt, out_dir, season=args.season)
    except RuntimeError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)
    logger.info(f"✅ Split into {len(files)} episode file(s) in {out_dir}/")


def register(sub):
    p = sub.add_parser('screenplay', help='Full screenplay + keyframe pipeline')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--resume', action='store_true', default=False,
                   help='Skip already-completed phases (episodes/raw/refined) using pipeline_state.json')
    p.set_defaults(func=cmd_screenplay)

    p = sub.add_parser('scenes', help='Generate keyframes for episode(s)')
    p.add_argument('scene', nargs='?', default='all', help='Episode number or "all"')
    p.add_argument('--resume', action='store_true', default=False,
                   help='Skip episodes whose refined checkpoint is already done')
    p.set_defaults(func=cmd_scenes)

    p = sub.add_parser('reverse-refine', help='Refinement + reversal pass on existing raw episode JSON')
    p.add_argument('scene', type=int, help='Episode number (e.g. 2 → reads animation_episode_scenes_002.json)')
    p.set_defaults(func=cmd_reverse_refine)

    p = sub.add_parser('consistency', help='Run continuity enforcer')
    p.add_argument('--dry-run', action=argparse.BooleanOptionalAction, default=True,
                   help='Skip image regeneration (default: on); use --no-dry-run to render refs')
    p.set_defaults(func=cmd_consistency)

    p = sub.add_parser('summary', help='Generate context summary for the next chapter')
    p.add_argument('novel', help='Path to the current chapter text file (e.g. s01e01.txt)')
    p.add_argument('--output', default='chapter_summary.txt',
                   help='Output path for the summary (default: chapter_summary.txt)')
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser(
        'split-book',
        help='Split a full novel into filmable episode chunks for 3-POV vertical microdrama',
    )
    p.add_argument('novel', help='Path to the full novel text file')
    p.add_argument(
        '--output-dir', default='book-split',
        help='Output directory for episode files (default: book-split)',
    )
    p.add_argument(
        '--season', type=int, default=1,
        help='Season number for output filename prefix, e.g. 1 → s01eNNN.txt (default: 1)',
    )
    p.set_defaults(func=cmd_split_book)
