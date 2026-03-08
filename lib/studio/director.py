"""
Director — Continuity Enforcer.

Port of 06_continuity_enforcer.py using a BaseLLM backend.
"""
import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PIL import Image

from lib.core.schemas import UPDATED_REF_SCHEMA, SCENE_REWRITE_SCHEMA
from lib.core.utils import DEFAULT_OUTPUT_DIR, DEFAULT_REF_DIR, atomic_write, safe_name
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

CASTING_RULES = """
## Reference Generation
- **Shot Type**: Close-up portrait for characters, medium view for objects, full view for locations and rooms
- **Expression for characters**: Neutral, professional
- **Lighting**: Uniform studio lighting
- **Background**: Solid neutral backdrop
- **Quality**: 8K resolution, sharp focus

## **IMPORTANT Background RULES**
- For characters - use EMPTY BACKGROUND
- For locations/places - use SHOW EMPTY SPACE WITHOUT PEOPLE
- For objects - use BLANK BACKGROUND
- For vehicles and rooms - use BLANK BACKGROUND, SHOW THEM EMPTY, WITHOUT PEOPLE

## Important for rooms:
- For every room generate a single 2-panel image, panels stacked vertically:
  - TOP: View from the door
  - BOTTOM: View to the door

## Important for vehicles:
- For every vehicle generate a single 3-panel image, panels stacked vertically:
  - TOP: View outside
  - MIDDLE: View inside from the entrance, wide shot
  - BOTTOM: View inside to the entrance, wide shot
"""


def _backup_refs(ref_dir: Path, extra_files: list = None) -> Path:
    """Copy all ref JSON + PNG files (and any extra_files) into ref_dir/backup-YYYYMMDDHHmm/."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    backup_dir = ref_dir / f"backup-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for pattern in ("*.json", "*.png"):
        for f in ref_dir.glob(pattern):
            shutil.copy2(f, backup_dir / f.name)
            count += 1
    for f in (extra_files or []):
        f = Path(f)
        if f.exists():
            shutil.copy2(f, backup_dir / f.name)
            count += 1
    logger.info(f"📦 Backed up {count} files → {backup_dir}")
    return backup_dir


def collect_reference_usage(metadata: Dict) -> Dict[str, List[str]]:
    """Collect all panel descriptions where each reference (character or location) is mentioned."""
    ref_usage: Dict[str, List[str]] = {}
    for scene in metadata.get('scenes', []):
        for panel in scene.get('panels', []):
            context = (
                f"Scene {scene['scene_id']}, Panel {panel['panel_index']}: "
                f"Start: {panel['visual_start']} | End: {panel['visual_end']} | "
                f"Camera: {panel.get('lights_and_camera', '')}"
            )
            for ref in panel.get('references', []) + panel.get('location_references', []):
                if ref not in ref_usage:
                    ref_usage[ref] = []
                ref_usage[ref].append(context)
    return ref_usage


def enrich_and_regenerate_reference(
    ref_name: str,
    usage_contexts: List[str],
    llm: BaseLLM,
    ref_dir: Path = DEFAULT_REF_DIR,
    dry_run: bool = True,
):
    """Enrich reference description and regenerate the portrait image."""
    sname = safe_name(ref_name)
    json_path = ref_dir / f"{sname}.json"
    png_path = ref_dir / f"{sname}.png"

    if not json_path.exists():
        logger.warning(f"⚠️  JSON for {ref_name} not found, skipping.")
        return

    ref_data = json.loads(json_path.read_text(encoding='utf-8'))
    if len(usage_contexts) > 20:
        logger.info(f"  ℹ️  Truncating context for {ref_name}: {len(usage_contexts)} usages → 20")
    logger.info(f"🔍 Enriching: {ref_name} (used in {len(usage_contexts)} panels)")

    prompt = f"""
    You are a Lead Production Designer.
    We have an original visual description for the entity "{ref_name}":
    <ORIGINAL_DESC>
    {ref_data['visual_desc']}
    </ORIGINAL_DESC>

    However, the storyboard artist added specific new details in various scenes.
    Here is how "{ref_name}" is actually described in the scenes:
    <SCENE_USAGES>
    {chr(10).join(usage_contexts[:20])}
    </SCENE_USAGES>

    TASK:
    Merge the ORIGINAL_DESC with all specific physical details invented in the SCENE_USAGES (e.g., specific desk color, exact props, specific lighting fixtures, specific clothing details).
    Do NOT include actions or temporary states. ONLY permanent visual design features.
    Generate a massive, highly detailed visual description that perfectly aligns with what the scenes require.

    {CASTING_RULES}
    """

    updated_desc = llm.make_json(prompt, UPDATED_REF_SCHEMA)

    if not updated_desc:
        return

    ref_data['visual_desc'] = updated_desc['visual_desc']
    ref_data['video_visual_desc'] = updated_desc['video_visual_desc']
    atomic_write(json_path, json.dumps(ref_data, ensure_ascii=False, indent=2))

    if dry_run:
        logger.info(f"  ⏭️  Dry-run: skipping PNG regeneration for {ref_name} (run `make refs` to render)")
        return

    logger.info(f"  🎨 Regenerating PNG for {ref_name}...")
    ref_prompt = (
        f"CINEMATIC REFERENCE FOR {ref_data.get('type', 'Entity')}: {ref_name}. "
        f"{ref_data['visual_desc']}. \n\n{CASTING_RULES}"
    )

    refs = []
    opened_imgs = []
    if ref_data.get('style_reference') and ref_data['style_reference'] != ref_name:
        style_path = ref_dir / f"{safe_name(ref_data['style_reference'])}.png"
        if style_path.exists():
            refs.append(f"## Visual Style reference for {ref_data['style_reference']}")
            img = Image.open(style_path)
            opened_imgs.append(img)
            refs.append(img)

    try:
        img_bytes = llm.make_image(ref_prompt, refs=refs,
                                   aspect_ratio=os.getenv('AI_REF_ASPECT_RATIO', '9:16'),
                                   image_size='1K')
        if img_bytes:
            png_path.write_bytes(img_bytes)
            logger.info(f"    ✅ PNG saved: {png_path}")
        else:
            logger.error(f"    ❌ Empty image response for {ref_name}")
    except Exception as e:
        logger.error(f"    ❌ Failed to render {ref_name}: {e}")
    finally:
        for img in opened_imgs:
            img.close()


def align_scene_prompts(scene: Dict, all_refs_data: Dict, llm: BaseLLM) -> Dict:
    """Rewrite panel visual_start/visual_end to match approved references."""
    logger.info(f"🎬 Aligning Scene {scene['scene_id']}...")

    scene_refs = set()
    for panel in scene['panels']:
        scene_refs.update(panel.get('references', []))

    if not scene_refs:
        return scene

    ref_context = {}
    for ref in scene_refs:
        ref_key = safe_name(ref)
        if ref_key in all_refs_data:
            ref_context[ref] = all_refs_data[ref_key]['video_visual_desc']

    camera_master = scene.get('camera_master', '')
    lighting_master = scene.get('lighting_master', '')
    master_block = ""
    if camera_master or lighting_master:
        master_block = f"""
    Scene camera master: {camera_master}
    Scene lighting master: {lighting_master}
    Enforce these across all panels — correct lights_and_camera when it contradicts the master.
"""

    prompt = f"""
    You are a Script Supervisor enforcing Visual Continuity.

    Here is the FINAL, APPROVED visual design for the entities in this scene:
    <APPROVED_REFERENCES>
    {json.dumps(ref_context, indent=2)}
    </APPROVED_REFERENCES>
    {master_block}
    Here is the current scene data:
    <CURRENT_SCENE>
    {json.dumps(scene['panels'], indent=2)}
    </CURRENT_SCENE>

    TASK:
    For each panel, correct ONLY what contradicts the APPROVED_REFERENCES or the scene masters:
    1. Rewrite 'visual_start' and 'visual_end' where colors, props, or materials contradict references.
    2. Rewrite 'lights_and_camera' where it contradicts camera_master or lighting_master.
    Do not change action, dialogue, or structure — only enforce physical and technical consistency.
    Return the full list of panels with adjusted visual_start, visual_end, and lights_and_camera.
    """

    aligned_data = llm.make_json(prompt, SCENE_REWRITE_SCHEMA)

    if aligned_data and 'panels' in aligned_data:
        aligned_map = {p['panel_index']: p for p in aligned_data['panels']}
        for panel in scene['panels']:
            if panel['panel_index'] in aligned_map:
                panel['visual_start'] = aligned_map[panel['panel_index']]['visual_start']
                panel['visual_end'] = aligned_map[panel['panel_index']]['visual_end']
                if lc := aligned_map[panel['panel_index']].get('lights_and_camera'):
                    panel['lights_and_camera'] = lc

    return scene


def run_continuity_pass(
    llm: BaseLLM,
    ref_dir: Path = DEFAULT_REF_DIR,
    max_workers: int = 5,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    dry_run: bool = True,
) -> Path:
    """
    Full continuity pipeline:
    1. Collect reference usage across all scenes
    2. Enrich + regenerate reference images
    3. Align scene prompts to approved references
    4. Save animation_metadata_consistent.json
    """
    metadata_path = output_dir / "animation_metadata.json"
    if not metadata_path.exists():
        logger.error("❌ animation_metadata.json not found. Run screenplay first.")
        raise FileNotFoundError(metadata_path)

    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))

    logger.info("=== STEP 1: REFERENCE USAGE ANALYSIS ===")
    ref_usage = collect_reference_usage(metadata)

    logger.info("=== STEP 1b: BACKING UP REFERENCES + METADATA ===")
    _backup_refs(ref_dir, extra_files=[metadata_path])

    logger.info("=== STEP 2: ENRICHING REFERENCES ===")
    error_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(enrich_and_regenerate_reference, ref_name, usages, llm, ref_dir, dry_run): ref_name
            for ref_name, usages in ref_usage.items()
        }
        for future in as_completed(futures):
            ref_name = futures[future]
            if exc := future.exception():
                logger.error(f"❌ Enrichment failed for {ref_name}: {exc}")
                error_count += 1
    if error_count > 0:
        logger.warning(f"⚠️  {error_count}/{len(ref_usage)} enrichment(s) failed. Proceeding with available data.")

    all_refs_data = {}
    for ref_file in ref_dir.glob("*.json"):
        all_refs_data[ref_file.stem] = json.loads(ref_file.read_text(encoding='utf-8'))

    logger.info("=== STEP 3: ALIGNING SCENE PROMPTS ===")
    aligned_scenes = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(align_scene_prompts, s, all_refs_data, llm): s for s in metadata['scenes']}
        for future in as_completed(futures):
            original_scene = futures[future]
            try:
                aligned_scenes.append(future.result())
            except Exception as e:
                logger.error(f"❌ Scene {original_scene.get('scene_id', '?')} alignment failed, keeping original: {e}")
                aligned_scenes.append(original_scene)
    aligned_scenes.sort(key=lambda s: s.get('scene_id', 0))

    metadata['scenes'] = aligned_scenes
    # Overwrite animation_metadata.json in-place — it IS the single source of truth
    out_path = metadata_path
    atomic_write(out_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    logger.info(f"✅ Done. Metadata updated in-place: {out_path}")
    return out_path
