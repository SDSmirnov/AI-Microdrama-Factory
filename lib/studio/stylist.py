"""
Stylist — Novel analysis and custom prompt generation.

Reads templates from lib/prompting/<style>/ (with legacy prompts/ fallback),
generates custom_prompts/ overlay files for the selected style.
"""
import json
import logging
from pathlib import Path
from typing import Dict

from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTING_DIR = _PROJECT_ROOT / "lib" / "prompting"
PROMPTS_DIR = _PROJECT_ROOT / "prompts"   # legacy fallback
CUSTOM_DIR = Path("custom_prompts")

# ---------------------------------------------------------------------------
# Style presets — keyed by lib/prompting/ directory name
# ---------------------------------------------------------------------------
STYLE_PRESETS: Dict[str, Dict] = {
    "vertical_9_16_microdrama": {
        "name": "Vertical MicroDrama - Realistic Cinematic",
        "format": "single_grid_animation",
        "panels_per_scene": 9,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "needs_start_end": True,
        "needs_dialogue": True,
        "needs_captions": False,
        "camera_style": "cinematic_fpov"
    },
    "vertical_9_16_dark_romance": {
        "name": "Vertical Dark Romance - Realistic Cinematic",
        "format": "single_grid_animation",
        "panels_per_scene": 9,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "needs_start_end": True,
        "needs_dialogue": True,
        "needs_captions": False,
        "camera_style": "cinematic_fpov"
    },
    "vertical_9_16_long_arc": {
        "name": "Vertical Long Arc - Realistic Cinematic",
        "format": "single_grid_animation",
        "panels_per_scene": 9,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "needs_start_end": True,
        "needs_dialogue": True,
        "needs_captions": False,
        "camera_style": "cinematic_fpov"
    },
}

_DEFAULT_STYLE = "vertical_9_16_microdrama"


def _style_dir(style: str) -> Path:
    """Return the prompting dir for style, falling back to legacy prompts/."""
    d = PROMPTING_DIR / style
    return d if d.exists() else PROMPTS_DIR


def _load_template(filename: str, style: str) -> str:
    path = _style_dir(style) / filename
    return path.read_text(encoding='utf-8') if path.exists() else ""


def _normalize_style_key(style_name: str) -> str:
    if style_name in STYLE_PRESETS:
        return style_name
    key = style_name.lower().replace(" ", "_").replace("the_", "")
    for k in STYLE_PRESETS:
        if k in key or key in k:
            return k
    return _DEFAULT_STYLE


def analyze_novel(text: str, llm: BaseLLM) -> dict:
    """Analyze novel text and extract metadata."""
    logger.info("📖 Analyzing novel...")

    schema = {
        "type": "object",
        "properties": {
            "genre": {"type": "array", "items": {"type": "string"}},
            "setting": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "location": {"type": "string"},
                    "world_type": {"type": "string"},
                }
            },
            "pov": {"type": "string"},
            "tone": {"type": "array", "items": {"type": "string"}},
            "main_character": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                }
            },
            "special_elements": {"type": "array", "items": {"type": "string"}},
            "visual_atmosphere": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["genre", "setting", "pov", "tone", "main_character", "special_elements", "visual_atmosphere"],
    }

    prompt = f"""
Analyze this novel excerpt and extract key metadata:

1. **Genre**: What are the primary genres? (e.g., Fantasy, Sci-Fi, Historical, LitRPG, Romance, Thriller)
2. **Setting**: Time period, location, world type (realistic, fantasy, sci-fi, alternate history)
3. **POV**: First-person, Third-person limited, Third-person omniscient, Second-person
4. **Tone**: Overall atmosphere (dark, heroic, comedic, serious, romantic, gritty)
5. **Main Character**: Name and brief description of protagonist
6. **Special Elements**: Magic systems, technology, supernatural elements, game mechanics, etc.
7. **Visual Atmosphere**: Key visual themes (dark alleys, grand ballrooms, space stations, medieval castles)

Return as JSON matching the provided schema.

Novel excerpt:
{text[:100000]}
"""
    result = llm.make_json(prompt, schema)
    if not result:
        logger.error("❌ Failed to analyze novel")
    return result


def generate_custom_prompts(novel_data: dict, style_name: str, llm: BaseLLM):
    """Generate custom_prompts/ overlay files adapted to the given style."""
    logger.info(f"\n🎨 Generating prompts for style: {style_name}")

    style_key = _normalize_style_key(style_name)
    preset = STYLE_PRESETS[style_key]
    logger.info(f"  ✓ Using preset: {preset['name']}")

    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)

    novel_json = json.dumps(novel_data, ensure_ascii=False)

    # --- style.md ---
    logger.info("  📝 Generating style.md...")
    style_template = _load_template("style.md", style_key)
    style_prompt = f"""
Based on this novel metadata: {novel_json}
And target visual style: {preset['name']}

Generate a complete style.md file following this template structure:
{style_template}

Fill ALL placeholders with specific values appropriate for {preset['name']} style.

For {preset['name']}:
- Camera equipment and techniques specific to this medium
- Rendering style (photorealistic, cel-shaded, ink and halftone, painted, etc.)
- Appropriate atmosphere keywords from the novel's tone
- Color grading matching both style and novel atmosphere
- Technical specs: resolution={preset['resolution']}, aspect_ratio={preset['aspect_ratio']}

Return ONLY the filled markdown content, no explanations.
"""
    style_md_text = _generate_text(llm, style_prompt)
    (CUSTOM_DIR / "style.md").write_text(style_md_text, encoding='utf-8')

    # --- casting.md ---
    logger.info("  📝 Generating casting.md...")
    casting_template = _load_template("casting.md", style_key)
    casting_prompt = f"""
Based on novel: {novel_json}
Visual style: {preset['name']}

Generate casting.md following template:
{casting_template}

Adjust character description format for {preset['name']}:
- Realistic cinematic: photorealistic actor descriptions
- Anime: anime character design (hair style, eye shape, costume details)
- Comic: bold features, distinctive visual traits, iconic costume
- Graphic novel: artistic, expressive features

Return filled markdown.
"""
    (CUSTOM_DIR / "casting.md").write_text(_generate_text(llm, casting_prompt), encoding='utf-8')

    # --- scenery.md ---
    logger.info("  📝 Generating scenery.md...")
    scenery_template = _load_template("scenery.md", style_key)
    scenery_prompt = f"""
Novel metadata: {novel_json}
Style: {preset['name']}
Format: {preset['format']}
Panels per scene: {preset['panels_per_scene']}

Generate scenery.md from template:
{scenery_template}

Key adjustments:
- If needs_start_end={preset['needs_start_end']}: Include START/END frame instructions
- If needs_start_end=False: Focus on single key moment per panel
- Panel duration: {"6-8s for animation" if preset['needs_start_end'] else "N/A (static)"}
- Camera POV: {preset['camera_style']}
- Composition: Match {preset['name']} conventions

Return filled markdown.
"""
    (CUSTOM_DIR / "scenery.md").write_text(_generate_text(llm, scenery_prompt), encoding='utf-8')

    # --- imagery.md ---
    logger.info("  📝 Generating imagery.md...")
    imagery_template = _load_template("imagery.md", style_key)
    imagery_prompt = f"""
Style: {preset['name']}
Format: {preset['format']}
Resolution: {preset['resolution']}
Aspect ratio: {preset['aspect_ratio']}
Panels: {preset['panels_per_scene']}

Generate imagery.md from template:
{imagery_template}

Specify:
- Grid structure: single image with {preset['panels_per_scene']} panels in grid layout
- Exact row × column count for {preset['panels_per_scene']} panels
- Composition rules specific to {preset['name']}
- Visual consistency requirements
- Special rendering instructions (film grain, halftone dots, cel shading, etc.)

Return filled markdown.
"""
    (CUSTOM_DIR / "imagery.md").write_text(_generate_text(llm, imagery_prompt), encoding='utf-8')

    # --- setting.md ---
    logger.info("  📝 Generating setting.md...")
    setting_template = _load_template("setting.md", style_key)
    replacements = {
        "{{genre_description}}": ", ".join(novel_data.get('genre', [])),
        "{{setting_description}}": json.dumps(novel_data.get('setting', {}), ensure_ascii=False),
        "{{atmosphere_description}}": ", ".join(novel_data.get('tone', [])),
        "{{pov_character}}": novel_data.get('main_character', {}).get('name', 'Unknown'),
        "{{narrator_style}}": novel_data.get('pov', 'Third-person'),
        "{{visual_tone}}": ", ".join(novel_data.get('tone', [])),
        "{{special_visual_elements}}": "\n  - ".join(novel_data.get('special_elements', [])),
        "{{hero_visual_description}}": novel_data.get('main_character', {}).get('description', ''),
        "{{composition_preferences}}": preset['camera_style'],
        "{{world_specific_details}}": "\n  - ".join(novel_data.get('visual_atmosphere', []))
    }
    content = setting_template
    for key, value in replacements.items():
        content = content.replace(key, str(value))
    (CUSTOM_DIR / "setting.md").write_text(content, encoding='utf-8')

    # --- config.json ---
    # Copy base style config.json into custom_prompts/ as a deep-merge override
    # starting point. This preserves all fields (transitions, multi_pov, vertical, etc.)
    # that would otherwise be lost if we reconstruct from the preset dict alone.
    logger.info("  📝 Generating config.json...")
    base_config_path = _style_dir(style_key) / "config.json"
    if base_config_path.exists():
        config = json.loads(base_config_path.read_text(encoding='utf-8'))
    else:
        config = {
            "format": {
                "type": preset['format'],
                "panels_per_scene": preset['panels_per_scene']
            },
            "image_generation": {
                "aspect_ratio": preset['aspect_ratio'],
                "resolution": preset['resolution'],
                "image_size": preset['resolution']
            },
            "animation": {
                "enabled": preset['needs_start_end'],
                "keyframe_type": "start_end" if preset['needs_start_end'] else "static"
            },
            "slicing": {
                "enabled": True,
                "frame_types": ["start", "end"] if preset['needs_start_end'] else ["static"]
            },
            "dialogue": {
                "enabled": preset['needs_dialogue'],
                "placement": "captions" if preset['needs_captions'] else "metadata_only"
            },
            "captions": {
                "enabled": preset['needs_captions']
            },
            "reference_characters": {
                "enabled": True,
                "auto_cast": True
            }
        }
    (CUSTOM_DIR / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')

    logger.info(f"\n✅ Custom prompts created in {CUSTOM_DIR}/")


def _generate_text(llm: BaseLLM, prompt: str) -> str:
    """
    Generate plain text (not JSON) via the LLM.

    For OpenRouter: wraps in a text-schema call; extracts string result.
    Falls back to make_json with a wrapper schema.
    """
    schema = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"]
    }
    wrapped_prompt = prompt + "\n\nIMPORTANT: Return a JSON object with a single key 'content' containing the full markdown text."
    result = llm.make_json(wrapped_prompt, schema)
    if isinstance(result, dict):
        return result.get('content', '')
    return str(result)
