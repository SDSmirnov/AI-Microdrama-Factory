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
from lib.core.prompts import NO_LABEL_TEXT, actor_line
from lib.core.utils import DEFAULT_OUTPUT_DIR, DEFAULT_REF_DIR, orientation, safe_name
from lib.llm.base import BaseLLM
from lib.studio.artist.render_utils import _ref_label

logger = logging.getLogger(__name__)



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
                    except Exception as e:
                        logger.warning(f"⚠️  Unreadable {json_path.name}: {e}")

                # Image before annotation — model sees visual before reading label
                ref_content.append(img)
                ref_content.append(_ref_label(ref_name, ref_type, desc))
                loaded_refs.append(ref_name)
                logger.info(f"  ✓ Loaded ref: {ref_name}")
            except Exception as e:
                logger.warning(f"  ⚠️  Error loading {img_path}: {e}")
        else:
            logger.warning(f"  ⚠️  Ref not found: {img_path}")

    return ref_content, loaded_refs, opened_imgs


# Panels with fidelity below this score are too broken for I2I — use full T2I regeneration instead.
_REGEN_FIDELITY_THRESHOLD = 3

# A SCALE/framing defect is structurally unfixable by an I2I edit: the edit
# inherits the source crop. Measured 2026-11-11 on panel 6 with three image
# models - told "Reframe to a low-angle Medium Shot (MS) from the waist up",
# EVERY model kept the source full-body crop, and the scale error survived
# every attempt. So a scale defect must go through a full T2I re-render
# (no source frame to inherit), not an edit.
_SCALE_DEFECT_PATTERNS = (
    "shot scale",
    "wrong scale",
    "scale error",
    "size/scale",
    "relative size",
    "instead of the requested",
    "framing",
    "camera angle",
    "wide shot",
    "medium shot",
    "close-up",
    "close up",
    "full body",
    "full-body",
    "crop",
)


def _wants_reframe(correction: str) -> bool:
    """Does this refinement request a change of framing / camera / scale?

    Such a request contradicts "preserve composition and framing exactly",
    so that lock must be dropped for it.
    """
    if not correction:
        return False
    low = correction.lower()
    if any(w in low for w in ("reframe", "re-frame", "change the framing",
                              "change framing", "change the camera",
                              "change camera", "wider shot", "tighter shot",
                              "pull back", "push in", "crop")):
        return True
    return any(p in low for p in _SCALE_DEFECT_PATTERNS)


def _is_scale_defect(correction: str) -> bool:
    """Is this refinement request specifically about shot scale / framing?

    Those need a T2I re-render, not an I2I edit.
    """
    if not correction:
        return False
    low = correction.lower()
    return any(p in low for p in _SCALE_DEFECT_PATTERNS) or \
        any(w in low for w in ("reframe", "re-frame", "change the framing",
                               "change framing", "change the camera"))


def _regenerate_t2i(
    llm: BaseLLM,
    scene: dict,
    panel: dict,
    visual_desc: str,
    char_refs: list,
    aspect_ratio: str,
    prompts: dict = None,
    anchor_context: str = '',
    correction: str = '',
    config: dict = None,
) -> bytes:
    """Full T2I regeneration for panels too broken for I2I editing."""
    disposition = panel.get('visual_disposition', '')
    lighting_context = " | ".join(filter(None, [
        scene.get('camera_master', ''),
        scene.get('lighting_master', ''),
        panel.get('lights_and_camera', ''),
    ]))
    actors_info = [
        actor_line(a, a.get('name', ''))
        for a in panel.get('state', {}).get('actors', []) if a.get('in_frame')
    ]
    actors_line = ' '.join(actors_info)
    single_panel_spec = f"Render a SINGLE {aspect_ratio} {orientation(aspect_ratio)} image. One panel only — no grid."
    style_block = "\n\n".join(filter(None, [
        (prompts or {}).get('style', ''),
        (prompts or {}).get('imagery', '').replace('{grid_layout}', single_panel_spec),
        (prompts or {}).get('setting', ''),
    ]))
    prompt = (
        (f"{style_block}\n\n" if style_block else "")
        + f"Generate a SINGLE {orientation(aspect_ratio)} {aspect_ratio} cinematic panel. "
        f"Location: {scene.get('location', '')}. "
        f"Scene: {scene.get('pre_action_description', '')}. "
        + (f"Actors: {actors_line}. " if actors_line else "")
        + f"Visual: {visual_desc}. "
        + (f"Disposition: {disposition}. " if disposition else "")
        + (f"\n{anchor_context}\n" if anchor_context else "")
        + (f"Camera/Lighting: {lighting_context}. " if lighting_context else "")
        + "CONSISTENCY RULE: Maintain IDENTICAL face, hair, clothing, and body proportions as shown in the reference images. "
        + "NO CAPTIONS. NO TEXT OVERLAYS. NO WATERMARKS. NO TEARS. NO SPITTING. " + NO_LABEL_TEXT
        # The QA's own correction must survive the re-render. It used to be
        # DISCARDED here, which is why a re-render could not fix a scale
        # error: the new image was rendered from the same (wrong) spec with
        # no mention of what to change.
        + (f"\nCORRECTION TO APPLY (mandatory): {correction.strip()}"
           if correction and correction.strip() else "")
    )
    from lib.studio.artist import _panel_image_size
    return llm.make_image(prompt, refs=char_refs, aspect_ratio=aspect_ratio,
                          image_size=_panel_image_size(config))


def refine_panel(
    scene_id: int,
    panel_id: int,
    frame_type: str,
    metadata: Dict,
    config: Dict,
    llm: BaseLLM,
    quality_prompts: Dict[str, dict] = None,
    project: Project = None,
    prompts: Dict = None,
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

    references = list(set(panel.get('references', []) + panel.get('location_references', [])))
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
    # A shot-scale/framing defect is ALSO structurally unfixable by an I2I
    # edit (the edit inherits the source crop — measured 2026-11-11, all
    # three image models kept the full-body crop through a reframe
    # instruction). Those panels must be re-rendered from scratch.
    if not force_regen and _is_scale_defect(panel_specific):
        force_regen = True
        logger.info(
            "🔄 Refinement requests a shot-scale/framing change — full T2I "
            "regeneration (an I2I edit cannot change the source crop)."
        )

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

    anchor_context = ''
    regen_refs = char_refs
    if project:
        from lib.studio.artist import _panel_blocking_context, _with_sketch
        # an I2I edit's image 1 is the panel itself, so only a full regeneration gets the sketch
        anchor_context, sketch = _panel_blocking_context(scene, panel, project, aspect_ratio, with_sketch=force_regen)
        regen_refs = _with_sketch(char_refs, sketch)

    img_bytes = None
    try:
        if force_regen:
            logger.info(
                f"🔄 Fidelity={fidelity} < {_REGEN_FIDELITY_THRESHOLD} — full T2I regeneration "
                f"(using {len(loaded_refs)} refs)..."
            )
            img_bytes = _regenerate_t2i(llm, scene, panel, visual_desc, regen_refs, aspect_ratio, prompts=prompts, anchor_context=anchor_context, correction=panel_specific, config=config)
        else:
            logger.info(f"🎨 I2I refinement (fidelity={fidelity}, using {len(loaded_refs)} refs)...")
            disposition = panel.get('visual_disposition', '')
            lighting_context = " | ".join(filter(None, [
                scene.get('camera_master', ''),
                scene.get('lighting_master', ''),
                panel.get('lights_and_camera', ''),
            ]))
            actors_info = [
                actor_line(a, a.get('name', ''))
                for a in panel.get('state', {}).get('actors', []) if a.get('in_frame')
            ]
            actors_line = ' '.join(actors_info)
            correction = panel_specific.strip() or (
                "Refine character appearances to match the provided references. "
                "Fix face, hair, clothing, accessories, and location details. "
                + (f"Actors: {actors_line}. " if actors_line else "")
                + f"Panel description: {visual_desc}"
                + (f" Spatial disposition: {disposition}" if disposition else "")
                + (f"\n{anchor_context}" if anchor_context else "")
            )
            single_panel_spec = f"Render a SINGLE {aspect_ratio} {orientation(aspect_ratio)} image. One panel only — no grid."
            imagery_rules = (prompts or {}).get('imagery', '').replace('{grid_layout}', single_panel_spec)
            # The "preserve composition" lock is CONDITIONAL. It used to be
            # appended unconditionally, which directly contradicted a QA
            # request to reframe ("Reframe to a low-angle Medium Shot (MS)
            # from the waist up" + "preserve composition and framing
            # exactly" = an impossible instruction). Measured 2026-11-11:
            # every model kept the source crop through a reframe instruction
            # and the scale error survived every attempt.
            #
            # A SCALE/framing change also cannot be fixed by an I2I edit at
            # all - the edit inherits the source crop. Those panels must be
            # re-rendered from scratch (see force_regen below).
            wants_reframe = _wants_reframe(correction)
            preserve_lock = (
                "" if wants_reframe else
                " Preserve composition, framing, camera angle, lighting mood, "
                "and character poses exactly."
            )
            correction = (
                (f"{imagery_rules}\n\n" if imagery_rules else "")
                + correction
                + (f" Required camera/lighting: {lighting_context}." if lighting_context else "")
                + preserve_lock
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
                img_bytes = _regenerate_t2i(llm, scene, panel, visual_desc, regen_refs, aspect_ratio, prompts=prompts, correction=panel_specific, config=config)
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
