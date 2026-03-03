"""
Director — Continuity Enforcer.

Port of 06_continuity_enforcer.py using a BaseLLM backend.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

from lib.core.schemas import UPDATED_REF_SCHEMA, SCENE_REWRITE_SCHEMA
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("cinematic_render")
REF_DIR = Path("ref_thriller")

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


def collect_reference_usage(metadata: Dict) -> Dict[str, List[str]]:
    """Collect all panel descriptions where each reference is mentioned."""
    ref_usage: Dict[str, List[str]] = {}
    for scene in metadata.get('scenes', []):
        for panel in scene.get('panels', []):
            for ref in panel.get('references', []):
                if ref not in ref_usage:
                    ref_usage[ref] = []
                context = (
                    f"Scene {scene['scene_id']}, Panel {panel['panel_index']}: "
                    f"Start: {panel['visual_start']} | End: {panel['visual_end']} | "
                    f"Camera: {panel.get('lights_and_camera', '')}"
                )
                ref_usage[ref].append(context)
    return ref_usage


def enrich_and_regenerate_reference(
    ref_name: str,
    usage_contexts: List[str],
    llm: BaseLLM,
    ref_dir: Path = REF_DIR,
):
    """Enrich reference description and regenerate the portrait image."""
    safe_name = ref_name.replace("/", "-").replace("'", " ").replace('"', '').replace(" ", "_").lower()
    json_path = ref_dir / f"{safe_name}.json"
    png_path = ref_dir / f"{safe_name}.png"

    if not json_path.exists():
        logger.warning(f"⚠️  JSON for {ref_name} not found, skipping.")
        return

    ref_data = json.loads(json_path.read_text(encoding='utf-8'))
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

    if updated_desc:
        ref_data['visual_desc'] = updated_desc['visual_desc']
        ref_data['video_visual_desc'] = updated_desc['video_visual_desc']
        json_path.write_text(json.dumps(ref_data, indent=2), encoding='utf-8')

        logger.info(f"  🎨 Regenerating PNG for {ref_name}...")
        ref_prompt = (
            f"CINEMATIC REFERENCE FOR {ref_data.get('type', 'Entity')}: {ref_name}. "
            f"{ref_data['visual_desc']}. \n\n{CASTING_RULES}"
        )

        refs = []
        if ref_data.get('style_reference') and ref_data['style_reference'] != ref_name:
            style_safe = ref_data['style_reference'].replace("/", "-").replace(" ", "_").lower()
            style_path = ref_dir / f"{style_safe}.png"
            if style_path.exists():
                from PIL import Image
                refs.append(f"## Visual Style reference for {ref_data['style_reference']}")
                refs.append(Image.open(style_path))

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
        safe_name = ref.replace("/", "-").replace(" ", "_").lower()
        if safe_name in all_refs_data:
            ref_context[ref] = all_refs_data[safe_name]['video_visual_desc']

    prompt = f"""
    You are a Script Supervisor enforcing Visual Continuity.

    Here is the FINAL, APPROVED visual design for the entities in this scene:
    <APPROVED_REFERENCES>
    {json.dumps(ref_context, indent=2)}
    </APPROVED_REFERENCES>

    Here is the current scene data:
    <CURRENT_SCENE>
    {json.dumps(scene['panels'], indent=2)}
    </CURRENT_SCENE>

    TASK:
    Rewrite 'visual_start' and 'visual_end' for each panel ONLY IF they contradict the APPROVED_REFERENCES.
    Ensure that colors, props, and materials mentioned in the scene exactly match the approved references.
    Do not change the action or cinematography, only enforce physical prop/character consistency.
    Return the full list of panels with your adjusted visual_start and visual_end.
    """

    aligned_data = llm.make_json(prompt, SCENE_REWRITE_SCHEMA)

    if aligned_data and 'panels' in aligned_data:
        aligned_map = {p['panel_index']: p for p in aligned_data['panels']}
        for panel in scene['panels']:
            if panel['panel_index'] in aligned_map:
                panel['visual_start'] = aligned_map[panel['panel_index']]['visual_start']
                panel['visual_end'] = aligned_map[panel['panel_index']]['visual_end']

    return scene


def run_continuity_pass(
    llm: BaseLLM,
    ref_dir: Path = REF_DIR,
    max_workers: int = 5,
) -> Path:
    """
    Full continuity pipeline:
    1. Collect reference usage across all scenes
    2. Enrich + regenerate reference images
    3. Align scene prompts to approved references
    4. Save animation_metadata_consistent.json
    """
    metadata_path = OUTPUT_DIR / "animation_metadata.json"
    if not metadata_path.exists():
        logger.error("❌ animation_metadata.json not found. Run screenplay first.")
        raise FileNotFoundError(metadata_path)

    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))

    logger.info("=== STEP 1: REFERENCE USAGE ANALYSIS ===")
    ref_usage = collect_reference_usage(metadata)

    logger.info("=== STEP 2: ENRICHING REFERENCES ===")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ref_name, usages in ref_usage.items():
            executor.submit(enrich_and_regenerate_reference, ref_name, usages, llm, ref_dir)

    all_refs_data = {}
    for ref_file in ref_dir.glob("*.json"):
        all_refs_data[ref_file.stem] = json.loads(ref_file.read_text(encoding='utf-8'))

    logger.info("=== STEP 3: ALIGNING SCENE PROMPTS ===")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        aligned_scenes = list(executor.map(
            lambda s: align_scene_prompts(s, all_refs_data, llm),
            metadata['scenes']
        ))

    metadata['scenes'] = aligned_scenes
    out_path = OUTPUT_DIR / "animation_metadata_consistent.json"
    out_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"✅ Done. Consistent metadata saved: {out_path}")
    return out_path
