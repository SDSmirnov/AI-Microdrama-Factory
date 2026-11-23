"""
Prompt loading utilities — single definition used across all pipeline stages.
"""
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "Russian")

DOOR_HANDEDNESS = (
    "Every door, hatch, gate and vehicle door has a fixed mechanism, handedness and state. "
    "Mechanism: hinged single or double leaf opening inward or outward, bi-fold, sliding along the wall, "
    "sliding into a wall pocket (lift doors), roll-up or up-and-over (garage), revolving, or no leaf at all "
    "(open doorway, arch, curtain); vehicle doors are front-hinged, rear-hinged, sliding or lift-up. "
    "Handedness: the hinge edge and handle side, or the side a sliding leaf moves to. "
    "State: closed, ajar, open, or folded back flat against the wall. "
    "State all three wherever a door is described, in room-relative terms (left-wall side, "
    "right-wall side, entrance side, far side) or vehicle terms (front/rear edge, driver side). "
    "Keep them identical in every view: a mirrored view swaps image sides, never the physical hinge."
)

NO_LABEL_TEXT = (
    "Kebab-case ids such as `guo-crate-seat` are reference labels, not lettering: never print them "
    "on anything. Show only text the description gives as real-world lettering (a crate stenciled "
    "\"FRAGILE\")."
)

# setting.md section written by `styles`: the real place and time a novel's world builds on. Every prompt that
# includes setting.md sees it; the story bible, which does not, gets it through world_anchor().
WORLD_ANCHOR_HEADING = '## Real-world anchor'


def world_anchor(setting: str) -> str:
    """The body of setting.md's real-world anchor section, '' when it has none."""
    m = re.search(rf'^{re.escape(WORLD_ANCHOR_HEADING)}[ \t]*$(.*?)(?=^## |\Z)', setting, re.M | re.S)
    return m[1].strip() if m else ''


def actor_line(actor: dict, name: str) -> str:
    """One in-frame actor as a prompt sentence; a missing field drops its clause."""
    return f"{name}: " + ', '.join(filter(None, [
        ' '.join(filter(None, [actor.get('pose'), actor.get('position')])),
        actor.get('gaze_target') and f"looking at {actor['gaze_target']}",
        # stored directions already read "toward X" / "away from X"
        actor.get('chest_direction') and f"body facing {actor['chest_direction']}",
        actor.get('head_direction') and f"head facing {actor['head_direction']}",
    ])) + '.'


_LIB_ROOT = Path(__file__).resolve().parent.parent.parent  # code repo root (stable even when lib/ is symlinked)

CUSTOM_PROMPTS_DIR = Path.cwd() / "custom_prompts"  # project-local overrides
PROMPTING_DIR = _LIB_ROOT / "lib" / "prompting"   # library presets (always from code repo)

PROMPT_FILES = ['style', 'casting', 'scenery', 'imagery', 'setting',
                'screenplay', 'screenplay_episodes', 'qa',
                'episode_type_pov', 'episode_type_transition',
                'episode_type_arc_open', 'episode_type_arc_mid', 'episode_type_arc_close',
                'episode_type_duel',
                'refinement_arc_rule',
                'motion_dynamics',
                'animation_prohibitions',
                'pass1_architecture', 'pass1a_state', 'pass1b_disposition', 'pass2_visual', 'pass3_motion_audio']


def _video_max_seconds() -> int:
    """The longest clip the video model accepts on our transport.

    Reference-to-video caps per model: grok-imagine-video-1.5 allows 15 s
    (vendor doc), the older grok-imagine-video 10 s (MEASURED 2026-11-12:
    an 11 s request with input_references returns HTTP 400 "Duration 11s
    exceeds the maximum allowed for reference-to-video, which is 10s").

    The prompt files must not carry their own copy of the limit - a number
    in prose and a number in code drift, and the symptom is an HTTP 400
    mid-batch rather than a clamp.
    """
    from lib.animation.capabilities import caps_for, default_video_model
    return caps_for(default_video_model()).ref_max_seconds


def _substitute(text: str) -> str:
    """Fill the runtime placeholders a prompt file may carry."""
    return (text
            .replace("{target_language}", TARGET_LANGUAGE)
            .replace("{{VIDEO_MAX_SECONDS}}", str(_video_max_seconds())))


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dicts — override wins on scalar values."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


_PATCH_OP = re.compile(r'^<!--\s*(replace:\s*(#+ .+?)|append)\s*-->[ \t]*\n', re.M)


def style_chain(style: str) -> list[Path]:
    """Style dirs from the root ancestor down to `style`, following config.json `extends`."""
    chain = []
    while style:
        style_dir = PROMPTING_DIR / style
        if style_dir in chain or not style_dir.is_dir():
            raise ValueError(f"Style '{style}': missing or cyclic `extends` ({' -> '.join(d.name for d in chain)})")
        chain.append(style_dir)
        style = _read_config(style_dir).get('extends')
    return chain[::-1]


def _read_config(style_dir: Path) -> dict:
    path = style_dir / 'config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def apply_patch(base: str, patch: str, source: str = 'patch') -> str:
    """Apply `<!-- replace: ## Heading -->` / `<!-- append -->` blocks to an inherited prompt.

    A section runs to the next heading of the same or higher level; an empty body deletes it.
    """
    head, *ops = _PATCH_OP.split(patch)
    if head.strip() or not ops:
        raise ValueError(f"{source}: expected only replace/append blocks")
    for _, heading, body in zip(*[iter(ops)] * 3):
        body = body.strip('\n')
        if heading is None:
            base = f"{base.rstrip()}\n\n{body}\n"
            continue
        level = len(heading) - len(heading.lstrip('#'))
        section = re.compile(rf'^{re.escape(heading)}[ \t]*\n.*?(?=^#{{1,{level}}} |\Z)', re.M | re.S)
        base, hits = section.subn(lambda _: f"{body}\n\n" if body else "", base)
        if hits != 1:
            raise ValueError(f"{source}: heading {heading!r} matches {hits} sections, expected 1")
    return base


def resolve_style_file(style: str, name: str) -> str | None:
    """Raw `<name>.md` through the style chain: `<name>.md` replaces the inherited text, `<name>.patch.md` edits it."""
    text = None
    for style_dir in style_chain(style):
        full, patch = style_dir / f'{name}.md', style_dir / f'{name}.patch.md'
        if full.exists() and patch.exists() or patch.exists() and text is None:
            raise ValueError(f"{style_dir.name}/{patch.name}: needs an inherited {name}.md and no sibling {full.name}")
        if full.exists():
            text = full.read_text(encoding='utf-8')
        elif patch.exists():
            text = apply_patch(text, patch.read_text(encoding='utf-8'), f'{style_dir.name}/{patch.name}')
    return text


def resolve_style_config(style: str) -> dict:
    config = {}
    for style_dir in style_chain(style):
        config = _deep_merge(config, _read_config(style_dir))
    config.pop('extends', None)
    return config


def prompt_names(style: str) -> list[str]:
    """PROMPT_FILES plus the episode_type_* prompts shipped by the style chain or custom_prompts/."""
    dirs = style_chain(style) + [CUSTOM_PROMPTS_DIR]
    extra = {p.name.split('.')[0] for d in dirs for p in d.glob('episode_type_*.md')}
    return PROMPT_FILES + sorted(extra - set(PROMPT_FILES))


def load_prompts(style: str = 'vertical_9_16_microdrama') -> tuple[dict, dict]:
    """
    Load prompts from lib/prompting/<style>/, then overlay custom_prompts/ overrides.

    Returns (prompts_dict, config_dict). Raises ValueError for an unknown style.
    """
    style_dir = PROMPTING_DIR / style
    if not style_dir.is_dir():
        known = ', '.join(sorted(p.name for p in PROMPTING_DIR.iterdir() if p.is_dir()))
        raise ValueError(f"Unknown style {style!r}; known: {known}")

    logger.info(f"📂 Loading prompts from {style_dir}/")

    # Load base prompts through the style's `extends` chain
    names = prompt_names(style)
    prompts = {}
    for name in names:
        text = resolve_style_file(style, name)
        if text is None:
            logger.debug(f"  {name}.md not in {style_dir.name}/ (expected from custom_prompts/)")
        prompts[name] = _substitute(text or "")

    # Apply custom_prompts/ overrides (complete replacement per file)
    if CUSTOM_PROMPTS_DIR.exists():
        for name in names:
            override_path = CUSTOM_PROMPTS_DIR / f"{name}.md"
            if override_path.exists():
                logger.info(f"  📝 Override: {name}.md from custom_prompts/")
                prompts[name] = _substitute(override_path.read_text(encoding='utf-8'))

    config = resolve_style_config(style)
    if not config:
        logger.warning(f"  ⚠️  config.json not found in {style_dir}, using defaults")
        config = get_default_config()

    # Deep-merge custom_prompts/config.json on top (custom wins per key)
    custom_config_path = CUSTOM_PROMPTS_DIR / 'config.json'
    if custom_config_path.exists():
        custom_config = json.loads(custom_config_path.read_text(encoding='utf-8'))
        logger.info("  📝 Override: config.json from custom_prompts/")
        config = _deep_merge(config, custom_config)

    _apply_env_overrides(config)
    return prompts, config


def _apply_env_overrides(config: dict) -> None:
    """Apply env overrides in-place.

    Supported vars:
      AI_ASPECT_RATIO, AI_IMAGE_SIZE, AI_REF_ASPECT_RATIO — image generation
      AI_EPISODES_COUNT — arc length for long_arc style (2 or 3)
    """
    ig = config.setdefault("image_generation", {})
    if v := os.getenv("AI_ASPECT_RATIO"):
        ig["aspect_ratio"] = v
    if v := os.getenv("AI_IMAGE_SIZE"):
        ig["resolution"] = v
        ig["image_size"] = v
    rc = config.setdefault("reference_characters", {})
    if v := os.getenv("AI_REF_ASPECT_RATIO"):
        rc["ref_aspect_ratio"] = v
    if v := os.getenv("AI_EPISODES_COUNT"):
        config["episodes_count"] = int(v)


def get_default_config() -> dict:
    """Default configuration for vertical microdrama."""
    return {
        "format": {
            "type": "single_grid_animation",
            "panel_count_options": [4, 6, 9, 10, 12],
            "panel_aspect_ratio": "9:16",
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
