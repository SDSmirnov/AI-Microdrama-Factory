"""Export a scene's grid prompt as text."""
import logging

from lib.core.project import Project
from lib.core.utils import grid_dims, is_portrait
from lib.studio.artist.grids import _build_prompt_header, _grid_layout_spec

logger = logging.getLogger(__name__)


def _build_image_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the image generation prompt text for a scene."""
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')
    resolution = config['image_generation'].get('image_size', '2K')

    n = len(scene.get('panels', []))
    cols, rows, grid_ar = grid_dims(n, panel_ar)
    portrait = is_portrait(panel_ar)
    prompt = _build_prompt_header(scene, prompts, grid_layout=_grid_layout_spec(n, panel_ar, resolution))
    prompt += (
        f"**CRITICAL FORMAT:** Single image containing {n} panels (each {panel_ar}) arranged in a {cols}×{rows} grid.\n"
        + ("Each cell is a VERTICAL frame designed for mobile viewing.\n" if portrait else
           "Each cell is a HORIZONTAL frame designed for widescreen viewing.\n")
        + ("SAFE ZONE per panel: compose key subjects (faces, hands, focal action) within the middle 65% of panel height.\n"
           "Top 15% and bottom 20% of each panel must remain visually uncluttered (background only — sky, wall, floor).\n" if portrait else "")
        + config['format'].get('framing_note', (
            "Faces and close-ups are the primary dramatic instrument — this is vertical microdrama, not widescreen cinema.\n" if portrait else
            "Wide compositions and environmental context are the primary dramatic instrument.\n")
            + "Shallow depth of field. Subjects sharp, backgrounds contextual only.") + "\n"
    )
    prompt += f"\nIMPORTANT: Generate SINGLE {resolution} {grid_ar} image with {n} panels in {cols}×{rows} grid layout.\n"

    for p in scene['panels']:
        prompt += f"\nPanel {p['panel_index']}:"
        if p.get('hook_type') and p['hook_type'] != 'none':
            prompt += f" [{p['hook_type'].upper()}]"
        if p.get('emotional_beat'):
            prompt += f" [{p['emotional_beat']}]"
        prompt += "\n"
        prompt += f"  Visual: {p.get('visual_start', p.get('visual_end', ''))}\n"
        if p.get('visual_disposition'):
            prompt += f"  Disposition: {p['visual_disposition']}\n"
        if 'lights_and_camera' in p:
            prompt += f"  Camera: {p['lights_and_camera']}\n"
        if config['dialogue']['enabled'] and p.get('dialogue'):
            prompt += f"  Dialogue: {p['dialogue']}\n"
        if config['dialogue'].get('voiceover') and p.get('voiceover'):
            prompt += f"  Voiceover: {p['voiceover']}\n"
        if config['captions']['enabled'] and p.get('caption'):
            prompt += f"  Caption: {p['caption']}\n"

    return prompt


def export_image_prompt(scene: dict, scene_id: int, prompts: dict, config: dict, project: Project):
    """Write cinematic_render/image_prompts/scene_00x.md for manual image generation testing."""
    project.image_prompts_dir.mkdir(parents=True, exist_ok=True)

    chars = list({ref for panel in scene.get('panels', []) for ref in panel.get('references', [])})

    md = f"# Scene {scene_id:03d} — {scene.get('location', '')}\n\n"
    if scene.get('pre_action_description'):
        md += f"**Setup:** {scene['pre_action_description']}\n\n"

    ref_chars = [name for name in chars if name in project.character_info]
    if ref_chars:
        md += "## Character Reference Descriptions\n\n"
        md += "_Use these to maintain visual consistency when prompting the model:_\n\n"
        for name in ref_chars:
            info = project.character_info[name]
            desc = info.get('video_visual_desc') or info.get('visual_desc', '')
            md += f"### {name}\n{desc}\n\n"
        md += "---\n\n"

    md += "## Image Generation Prompt\n\n"
    md += "```\n"
    md += _build_image_prompt(scene, prompts, config)
    md += "\n```\n"

    out_path = project.image_prompts_dir / f"scene_{scene_id:03d}.md"
    out_path.write_text(md, encoding='utf-8')
    logger.info(f"  📝 Saved image prompt: {out_path}")
