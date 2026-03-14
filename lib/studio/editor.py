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



def load_quality_report(report_path: Path = DEFAULT_OUTPUT_DIR / "quality_report.json") -> Dict[str, dict]:
    """Load QA data keyed by 'scene_id_panel_id'.

    Each value: {'refinement_prompt': str, 'fidelity': int, 'composition_match': int}
    """
    if not report_path.exists():
        logger.warning(f"⚠️  Quality report not found: {report_path}")
        return {}

    data = json.loads(report_path.read_text(encoding='utf-8'))
    quality_prompts = {}
    for item in data.get('panels', []):
        key = f"{item['scene_id']}_{item['panel_id']}"
        quality_prompts[key] = {
            'refinement_prompt': item.get('refinement_prompt', ''),
            'fidelity': item.get('fidelity', 10),
            'composition_match': item.get('composition_match', 10),
        }
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
                ref_type = "Character"
                if json_path.exists():
                    try:
                        data = json.loads(json_path.read_text(encoding='utf-8'))
                        desc = data.get('visual_desc', '')
                        ref_type = data.get('type', 'Character')
                    except Exception:
                        pass

                # Image before annotation — model sees visual before reading label
                ref_content.append(img)
                if ref_type in ('Location', 'Room'):
                    ref_content.append(f"↑ SCENE ENVIRONMENT: \"{ref_name}\" — match this background/location.\n{desc}\n")
                elif ref_type in ('Object', 'Vehicle', 'Interface'):
                    ref_content.append(f"↑ PROP: \"{ref_name}\" — match this object's appearance exactly.\n{desc}\n")
                else:
                    ref_content.append(f"↑ CHARACTER: \"{ref_name}\" — match face, hair, clothing exactly.\n{desc}\n")
                loaded_refs.append(ref_name)
                logger.info(f"  ✓ Loaded ref: {ref_name}")
            except Exception as e:
                logger.warning(f"  ⚠️  Error loading {img_path}: {e}")
        else:
            logger.warning(f"  ⚠️  Ref not found: {img_path}")

    return ref_content, loaded_refs, opened_imgs


# Panels with fidelity below this score are too broken for I2I — use full T2I regeneration instead.
_REGEN_FIDELITY_THRESHOLD = 3


def _regenerate_t2i(
    llm: BaseLLM,
    scene: dict,
    panel: dict,
    visual_desc: str,
    char_refs: list,
    aspect_ratio: str,
) -> bytes:
    """Full T2I regeneration for panels too broken for I2I editing."""
    prompt = (
        f"Generate a SINGLE portrait {aspect_ratio} cinematic panel. "
        f"Location: {scene.get('location', '')}. "
        f"Scene: {scene.get('pre_action_description', '')}. "
        f"Visual: {visual_desc}. "
        f"Camera/Lighting: {panel.get('lights_and_camera', '')}. "
        "Photorealistic, cinematic quality. NO CAPTIONS. NO TEXT OVERLAYS."
    )
    return llm.make_image(prompt, refs=char_refs, aspect_ratio=aspect_ratio, image_size='1K')


def refine_panel(
    scene_id: int,
    panel_id: int,
    frame_type: str,
    metadata: Dict,
    config: Dict,
    llm: BaseLLM,
    quality_prompts: Dict[str, dict] = None,
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

    if frame_type == 'end':
        visual_desc = panel.get('visual_end', '')
    elif frame_type == 'start':
        visual_desc = panel.get('visual_start', '')
    else:  # static
        visual_desc = panel.get('visual_start', panel.get('visual_end', ''))

    qa_data = (quality_prompts or {}).get(f"{scene_id}_{panel_id}", {})
    panel_specific = qa_data.get('refinement_prompt', '') if isinstance(qa_data, dict) else str(qa_data)
    fidelity = qa_data.get('fidelity', 10) if isinstance(qa_data, dict) else 10

    # Panels with very low fidelity are too broken for I2I to fix — regenerate from scratch
    force_regen = fidelity < _REGEN_FIDELITY_THRESHOLD

    refined_filename = f"{scene_id:03d}_{panel_id:02d}_{frame_type}_refined.png"
    refined_path = refined_dir / refined_filename
    refined_dir.mkdir(parents=True, exist_ok=True)

    if refined_path.exists():
        logger.info(f"⏭  Refined version already exists: {refined_path}")
        return True

    aspect_ratio = config['image_generation'].get('aspect_ratio', '9:16')
    char_refs = []
    if ref_content:
        char_refs.append("# CHARACTER/LOCATION REFERENCE LIBRARY\nUse these for accurate visual details:\n")
        char_refs.extend(ref_content)

    img_bytes = None
    try:
        if force_regen:
            logger.info(
                f"🔄 Fidelity={fidelity} < {_REGEN_FIDELITY_THRESHOLD} — full T2I regeneration "
                f"(using {len(loaded_refs)} refs)..."
            )
            img_bytes = _regenerate_t2i(llm, scene, panel, visual_desc, char_refs, aspect_ratio)
        else:
            logger.info(f"🎨 I2I refinement (fidelity={fidelity}, using {len(loaded_refs)} refs)...")
            correction = panel_specific.strip() or (
                f"Refine character appearances to match the provided references. "
                f"Fix face, hair, clothing, accessories, and location details. "
                f"Panel description: {visual_desc}"
            )
            correction = (
                "Apply cinematic beauty standard: dewy skin, sharp catchlights, volumetric rim light, "
                "luxury teal-and-orange grade. "
                + correction
                + " Preserve composition, framing, camera angle, lighting mood, and character poses exactly."
            )
            try:
                img_bytes = llm.edit_image(
                    src_img=original_img,
                    prompt=correction,
                    refs=char_refs,
                    aspect_ratio=aspect_ratio,
                    image_size='1K',
                )
            except Exception as e:
                logger.warning(f"  ⚠️  edit_image failed ({e}), falling back to T2I regeneration...")
                img_bytes = _regenerate_t2i(llm, scene, panel, visual_desc, char_refs, aspect_ratio)
    except Exception as e:
        logger.error(f"❌ Generation error: {e}", exc_info=True)
        return False
    finally:
        original_img.close()
        for img in opened_ref_imgs:
            img.close()

    try:
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
        logger.error(f"❌ Write error: {e}", exc_info=True)
        return False
