"""
Prompt loading utilities — single definition used across all pipeline stages.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

PROMPTS_DIR = _PROJECT_ROOT / "prompts"
CUSTOM_PROMPTS_DIR = _PROJECT_ROOT / "custom_prompts"
PROMPTING_DIR = _PROJECT_ROOT / "lib" / "prompting"

PROMPT_FILES = ['style', 'casting', 'scenery', 'imagery', 'setting',
                'screenplay', 'screenplay_scene', 'screenplay_episodes', 'qa']


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dicts — override wins on scalar values."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_prompts(style: str = 'vertical_9_16_microdrama') -> tuple[dict, dict]:
    """
    Load prompts from lib/prompting/<style>/, then overlay custom_prompts/ overrides.

    Returns (prompts_dict, config_dict).
    Falls back to prompts/ directory if style dir is missing (legacy behavior).
    """
    style_dir = PROMPTING_DIR / style

    if not style_dir.exists():
        logger.warning(f"⚠️  Style dir {style_dir} not found, falling back to legacy prompts/")
        source_dir = PROMPTS_DIR
        prompts = {}
        for name in PROMPT_FILES:
            path = source_dir / f"{name}.md"
            if path.exists():
                prompts[name] = path.read_text(encoding='utf-8')
            else:
                prompts[name] = ""
        config_path = source_dir / 'config.json'
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else get_default_config()
        return prompts, config

    logger.info(f"📂 Loading prompts from {style_dir}/")

    # Load base prompts from style dir
    prompts = {}
    for name in PROMPT_FILES:
        path = style_dir / f"{name}.md"
        if path.exists():
            prompts[name] = path.read_text(encoding='utf-8')
        else:
            logger.debug(f"  {name}.md not in {style_dir.name}/ (expected from custom_prompts/)")
            prompts[name] = ""

    # Apply custom_prompts/ overrides (complete replacement per file)
    if CUSTOM_PROMPTS_DIR.exists():
        for name in PROMPT_FILES:
            override_path = CUSTOM_PROMPTS_DIR / f"{name}.md"
            if override_path.exists():
                logger.info(f"  📝 Override: {name}.md from custom_prompts/")
                prompts[name] = override_path.read_text(encoding='utf-8')

    # Load base config from style dir
    config_path = style_dir / 'config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
    else:
        logger.warning(f"  ⚠️  config.json not found in {style_dir}, using defaults")
        config = get_default_config()

    # Deep-merge custom_prompts/config.json on top (custom wins per key)
    custom_config_path = CUSTOM_PROMPTS_DIR / 'config.json'
    if custom_config_path.exists():
        custom_config = json.loads(custom_config_path.read_text(encoding='utf-8'))
        logger.info("  📝 Override: config.json from custom_prompts/")
        config = _deep_merge(config, custom_config)

    return prompts, config


def get_default_config() -> dict:
    """Default configuration for vertical microdrama."""
    return {
        "format": {
            "type": "single_grid_animation",
            "panels_per_scene": 9,
            "panel_duration_s": 6
        },
        "image_generation": {
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "image_size": "2K"
        },
        "vertical": {
            "safe_zone_top_pct": 15,
            "safe_zone_bottom_pct": 20
        },
        "animation": {
            "enabled": True,
            "keyframe_type": "start_end"
        },
        "slicing": {
            "enabled": True,
            "frame_types": ["static"]
        },
        "dialogue": {
            "enabled": True,
            "voiceover": True,
            "max_words_per_line": 8
        },
        "captions": {
            "enabled": True
        },
        "reference_characters": {
            "enabled": True,
            "auto_cast": True,
            "ref_aspect_ratio": "9:16"
        }
    }
