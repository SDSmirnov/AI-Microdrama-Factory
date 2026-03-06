"""
Editor — Panel Refinement.

Port of panel_refinement.py using a BaseLLM backend.
Dead code (return before image API call at line 358) has been removed.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from lib.core.project import Project
from lib.core.utils import DEFAULT_OUTPUT_DIR, DEFAULT_REF_DIR, load_metadata, safe_name
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)



def load_quality_report(report_path: Path = DEFAULT_OUTPUT_DIR / "quality_report.json") -> Dict[str, str]:
    """Load refinement prompts keyed by 'scene_id_panel_id'."""
    if not report_path.exists():
        logger.warning(f"⚠️  Quality report not found: {report_path}")
        return {}

    data = json.loads(report_path.read_text(encoding='utf-8'))
    quality_prompts = {}
    for item in data.get('panels', []):
        key = f"{item['scene_id']}_{item['panel_id']}"
        quality_prompts[key] = item.get('refinement_prompt', '')
    return quality_prompts


def find_scene_panel(metadata: Dict, scene_id: int, panel_id: int) -> Optional[Dict]:
    for scene in metadata.get('scenes', []):
        if scene['scene_id'] == scene_id:
            for panel in scene.get('panels', []):
                if panel['panel_index'] == panel_id:
                    return {'scene': scene, 'panel': panel}
    return None


def load_character_references(references: List[str], ref_dir: Path = DEFAULT_REF_DIR) -> Tuple[List, List[str], List[Image.Image]]:
    """
    Load PIL images and text blocks for each reference.
    Returns (content_list, loaded_names, opened_imgs) — caller must close opened_imgs after use.
    """
    ref_content = []
    loaded_refs = []
    opened_imgs = []

    for ref_name in references:
        img_path = ref_dir / f"{safe_name(ref_name)}.png"
        json_path = ref_dir / f"{safe_name(ref_name)}.json"

        if img_path.exists():
            try:
                img = Image.open(img_path)
                opened_imgs.append(img)
                desc = ""
                if json_path.exists():
                    try:
                        data = json.loads(json_path.read_text(encoding='utf-8'))
                        desc = data.get('visual_desc', '')
                    except Exception:
                        pass

                ref_content.append(f"## Visual Reference: \"{ref_name}\"\n{desc}\n")
                ref_content.append(img)
                loaded_refs.append(ref_name)
                logger.info(f"  ✓ Loaded ref: {ref_name}")
            except Exception as e:
                logger.warning(f"  ⚠️  Error loading {img_path}: {e}")
        else:
            logger.warning(f"  ⚠️  Ref not found: {img_path}")

    return ref_content, loaded_refs, opened_imgs


def refine_panel(
    scene_id: int,
    panel_id: int,
    frame_type: str,
    metadata: Dict,
    prompts: Dict,
    config: Dict,
    llm: BaseLLM,
    quality_prompts: Dict[str, str] = None,
    project: Project = None,
) -> bool:
    panels_dir = project.panels_dir if project else DEFAULT_OUTPUT_DIR / "panels"
    refined_dir = project.refined_dir if project else DEFAULT_OUTPUT_DIR / "refined"

    data = find_scene_panel(metadata, scene_id, panel_id)
    if not data:
        logger.error(f"❌ Panel {panel_id} not found in scene {scene_id}")
        return False

    scene = data['scene']
    panel = data['panel']

    logger.info(f"\n{'='*60}")
    logger.info(f"🔧 Refinement: Scene {scene_id}, Panel {panel_id}, Frame: {frame_type}")
    logger.info(f"{'='*60}")

    panel_filename = f"{scene_id:03d}_{panel_id:02d}_{frame_type}.png"
    original_path = panels_dir / panel_filename

    if not original_path.exists():
        logger.error(f"❌ Panel file not found: {original_path}")
        return False

    references = panel.get('references', [])
    if not references:
        panel_type = panel.get('panel_type', 'narrative')
        if panel_type == 'atmosphere_insert':
            logger.info(
                f"ℹ️  Scene {scene_id} panel {panel_id} is atmosphere_insert — "
                f"no character refs by design. Regenerate via 'storyboard' instead."
            )
        else:
            logger.warning(
                f"⚠️  Scene {scene_id} panel {panel_id}: no references specified, "
                f"cannot refine. Add refs to metadata or regenerate via 'storyboard'."
            )
        return False

    ref_content, loaded_refs, opened_ref_imgs = load_character_references(references)
    if not ref_content:
        logger.warning("⚠️  Could not load any references")
        return False

    original_img = Image.open(original_path)

    style_prompt = prompts.get('style', '')
    imagery_prompt = prompts.get('imagery', '')
    setting_context = prompts.get('setting', '')
    if frame_type == 'end':
        visual_desc = panel.get('visual_end', '')
    elif frame_type == 'start':
        visual_desc = panel.get('visual_start', '')
    else:  # static
        visual_desc = panel.get('visual_start', panel.get('visual_end', ''))

    panel_specific = ""
    if quality_prompts:
        key = f"{scene_id}_{panel_id}"
        if key in quality_prompts:
            panel_specific = f"\n## IMPORTANT PANEL-SPECIFIC INSTRUCTIONS\n{quality_prompts[key]}\n"

    refinement_prompt = f"""{style_prompt}

{imagery_prompt}

{setting_context}

# REFINEMENT TASK

You are given:
1. ORIGINAL IMAGE - current panel that serves as COMPOSITION REFERENCE
2. CHARACTER/LOCATION VISUAL REFERENCES - for accurate appearance details

## CRITICAL REQUIREMENTS:

### PRESERVE FROM ORIGINAL:
- Camera angle, framing, composition
- Lighting setup (direction, quality, mood)
- Character positions and poses
- Overall scene layout and depth
- Motion and dynamics (if any)

### REFINE/CORRECT:
- Character facial features (use reference images)
- Character clothing and accessories (use reference images)
- Character hair, build, and physical traits (use reference images)
- Location/environment details (use reference images)
- Object appearances (use reference images)
- Fine details consistency with references

## SCENE CONTEXT:
Location: {scene.get('location', 'Unknown')}
Setup: {scene.get('pre_action_description', '')}

## PANEL DESCRIPTION:
{visual_desc}

## INSTRUCTIONS:
Generate a refined version of the original image that:
1. Keeps EXACT same composition, framing, camera angle
2. Keeps EXACT same lighting setup and mood
3. Keeps EXACT same character positions and poses
4. CORRECTS character appearances to match reference images
5. CORRECTS location/object details to match reference images
6. Maintains visual quality and cinematic feel

{panel_specific}

DO NOT change the composition or layout - only refine the visual details!
No captions or text overlays!
"""

    refined_filename = f"{scene_id:03d}_{panel_id:02d}_{frame_type}_refined.png"
    refined_path = refined_dir / refined_filename
    refined_dir.mkdir(parents=True, exist_ok=True)

    if refined_path.exists():
        logger.info(f"⏭  Refined version already exists: {refined_path}")
        return True

    logger.info(f"🎨 Generating refined version (using {len(loaded_refs)} refs)...")

    refs = []
    if ref_content:
        refs.append("# CHARACTER/LOCATION REFERENCE LIBRARY\nUse these for accurate visual details:\n")
        refs.extend(ref_content)
    refs.append("\n# ORIGINAL COMPOSITION REFERENCE\nPreserve this exact composition, lighting, and layout:\n")
    refs.append(original_img)

    try:
        img_bytes = llm.make_image(
            refinement_prompt,
            refs=refs,
            aspect_ratio='9:16',
            image_size='1K',
        )
        if img_bytes:
            refined_path.write_bytes(img_bytes)
            logger.info(f"✅ Saved: {refined_path}")

            meta_path = refined_path.with_suffix('.json')
            meta = {
                'scene_id': scene_id,
                'panel_id': panel_id,
                'frame_type': frame_type,
                'original_file': str(original_path),
                'references_used': loaded_refs,
                'visual_description': visual_desc,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            return True
        else:
            logger.error("❌ Empty image response")
            return False

    except Exception as e:
        logger.error(f"❌ Generation error: {e}", exc_info=True)
        return False
    finally:
        original_img.close()
        for img in opened_ref_imgs:
            img.close()
