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

PROMPT_FILES = ['style', 'casting', 'scenery', 'imagery', 'setting']


def load_prompts(use_custom: bool = False) -> tuple[dict, dict]:
    """
    Load prompts from prompts/ or custom_prompts/.

    Returns (prompts_dict, config_dict).
    Falls back to prompts/ if custom_prompts/ not found.
    """
    source_dir = CUSTOM_PROMPTS_DIR if use_custom else PROMPTS_DIR

    if use_custom and not CUSTOM_PROMPTS_DIR.exists():
        logger.warning(f"⚠️  {CUSTOM_PROMPTS_DIR} not found, falling back to standard prompts")
        source_dir = PROMPTS_DIR

    logger.info(f"📂 Loading prompts from {source_dir}/")

    prompts = {}
    for name in PROMPT_FILES:
        path = source_dir / f"{name}.md"
        if path.exists():
            prompts[name] = path.read_text(encoding='utf-8')
        else:
            logger.warning(f"  ⚠️  {name}.md not found")
            prompts[name] = ""

    config_path = source_dir / 'config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
    else:
        logger.warning("  ⚠️  config.json not found, using defaults")
        config = get_default_config()

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
