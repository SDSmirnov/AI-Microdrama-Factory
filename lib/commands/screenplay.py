"""Screenplay commands: screenplay, scenes, consistency, summary."""
import argparse
import json
import logging
import sys
from pathlib import Path

from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import Project, load_project
from lib.core.utils import atomic_write, load_metadata
from lib.studio.artist import export_image_prompt, load_character_refs
from lib.studio.director import run_continuity_pass
from lib.studio.screenwriter import SYSTEM_PROMPT, analyze_scenes_master, merge_scenes, run_scenes_pipeline

logger = logging.getLogger(__name__)


def cmd_screenplay(args):
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
    load_character_refs(project)

    text = Path(args.novel).read_text(encoding='utf-8')
    data = analyze_scenes_master(
        text, prompts, config, llm,
        max_workers=project.max_workers,
        character_info=project.character_info,
        output_dir=project.output_dir,
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
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
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

    all_scenes = run_scenes_pipeline(
        episodes, episodes_list, prompts, config, llm,
        output_dir=project.output_dir,
        character_info=project.character_info,
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
    project, _, _ = load_project(use_custom=False)
    llm = _make_llm(args.llm, project)

    novel_text = Path(args.novel).read_text(encoding='utf-8')

    meta_path = project.output_dir / "animation_metadata.json"
    scenes_block = ""
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        scenes = metadata.get('scenes', [])
        scene_summaries = []
        for scene in scenes:
            panels = scene.get('panels', [])
            panel_texts = []
            for p in panels:
                parts = [p.get('visual_start', ''), p.get('visual_end', '')]
                dlg = p.get('dialogue', '') or p.get('voiceover', '') or p.get('caption', '')
                if dlg:
                    parts.append(f"[{dlg}]")
                panel_texts.append(" → ".join(t for t in parts if t))
            scene_summaries.append(
                f"Scene {scene['scene_id']} [{scene.get('location', '')}]:\n"
                + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(panel_texts))
            )
        scenes_block = "\n\n".join(scene_summaries)

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

Be precise, concise, and production-ready. Write in English.
This summary will be injected verbatim into the next chapter prompt.

---
## SOURCE TEXT (current chapter)

{novel_text}

---
## PRODUCED SCENES

{scenes_block or "(no scenes data available)"}

---
## CHARACTER REFERENCES

{refs_block or "(no character refs available)"}
"""

    result = llm.generate(prompt)
    if not result:
        logger.error("❌ LLM returned empty summary")
        sys.exit(1)

    out_path = Path(args.output)
    out_path.write_text(result, encoding='utf-8')
    logger.info(f"✅ Summary written to {out_path}")


def register(sub):
    p = sub.add_parser('screenplay', help='Full screenplay + keyframe pipeline')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--custom-prompts', action='store_true')
    p.set_defaults(func=cmd_screenplay)

    p = sub.add_parser('scenes', help='Generate keyframes for episode(s)')
    p.add_argument('scene', nargs='?', default='all', help='Episode number or "all"')
    p.add_argument('--custom-prompts', action='store_true')
    p.set_defaults(func=cmd_scenes)

    p = sub.add_parser('consistency', help='Run continuity enforcer')
    p.add_argument('--dry-run', action=argparse.BooleanOptionalAction, default=True,
                   help='Skip image regeneration (default: on); use --no-dry-run to render refs')
    p.set_defaults(func=cmd_consistency)

    p = sub.add_parser('summary', help='Generate context summary for the next chapter')
    p.add_argument('novel', help='Path to the current chapter text file (e.g. s01e01.txt)')
    p.add_argument('--output', default='chapter_summary.txt',
                   help='Output path for the summary (default: chapter_summary.txt)')
    p.set_defaults(func=cmd_summary)
