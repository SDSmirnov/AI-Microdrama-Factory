"""Transform animation_episodes.json into quickplay format for multi-ref video clips.

Designed for Seedance 2.0 / Kling 3.0 / Grok-video that support:
  - multiple character/location reference images per clip
  - I2V continuation from the previous clip's last frame

Each scene is passed whole to the LLM, which decides the 4 natural dramatic cut points
and returns 4 animation prompts. References are emitted as name/@ImageN pairs so the
user can upload the images to a web chatbot and the prompts reference them by placeholder.

Output:
{
  "scenes": [{
    "scene_id": "e001s1",
    "clips": [{
      "prompt": "Ruslan (@Image1) leans forward...",
      "references": [["Ruslan", "@Image1"], ["Living Room", "@Image2"]]
    }]
  }]
}
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lib.animation.base import ANIMATION_PROHIBITIONS
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_CLIPS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 4,
    "maxItems": 4,
}

# {target}s is substituted per call
_SYSTEM_PROMPT_TEMPLATE = (
    ANIMATION_PROHIBITIONS + "\n"
    "You are a cinematographer adapting a storyboard scene into 4 sequential {target}s "
    "video-generation prompts for Seedance / Kling / Grok video models.\n"
    "The 4 clips play back-to-back as one continuous scene.\n\n"

    "CAMERA LANGUAGE — use these exact phrases (all target models understand them):\n"
    "  Shot scale: 'extreme close-up', 'close-up', 'medium shot', 'wide shot', "
    "'over-the-shoulder shot'\n"
    "  Movement: 'static camera', 'slow dolly in', 'slow dolly out', 'push in', 'pull back', "
    "'handheld', 'pan left', 'pan right', 'tilt up', 'tilt down', "
    "'rack focus from [X] to [Y]'\n"
    "  Transitions: 'cut to close-up', 'camera pushes in to reveal', 'camera pulls back'\n"
    "Extract shot scale from each panel header [hook_type | SCALE | LOCATION] and "
    "express every camera transition explicitly with a timestamp.\n\n"

    "REFERENCE INJECTION — you will receive a reference table. Inject tags inline in prose:\n"
    "  - First mention of a character per clip: 'Ruslan (@Image1) stands...'\n"
    "  - Key action moments: 'Alisa (@Image2) reaches for the folder'\n"
    "  - Location: mention the location tag in the opening frame description of every clip\n\n"

    "STEP 1 — find 3 dramatic cut points: tension shifts, location moves, "
    "shot-scale jumps, dialogue pivots. Do NOT cut at fixed panel boundaries.\n\n"

    "STEP 2 — budget {target}s per clip before writing:\n"
    "  Speech: ~2 words/second — count words per dialogue line to get its duration.\n"
    "  Actions: glance=0.5s, pick up object=1s, cross room=3–4s, "
    "strike/shove=0.3s + 1s reaction.\n"
    "  Dialogue + major action must together fit within {target}s.\n\n"

    "STEP 3 — write one flowing prompt per clip (150–220 words):\n"
    "  - Open with the exact visual state + location ref tag.\n"
    "  - Explicit timestamps [0s], [Xs] for every beat: shot change, action start, "
    "dialogue onset.\n"
    "  - Dialogue: 'at 4s Ruslan (@Image1) says: \"...\"'\n"
    "  - World-space directions only (toward the window, backing to the door). "
    "NEVER 'toward camera'.\n"
    "  - Close with the frozen visual state the next clip will open on.\n\n"

    "Return a JSON array of exactly 4 strings — the 4 prompts in scene order. No other keys.\n"
)


def _build_ref_pairs(characters: list[str], location: str) -> list[tuple[str, str]]:
    """Assign @ImageN placeholders to each character + location, in order."""
    entries = list(characters) + ([location] if location else [])
    return [(name, f"@Image{i + 1}") for i, name in enumerate(entries)]


def _ref_table(ref_pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"  {name} → {tag}" for name, tag in ref_pairs)


def _synthesize_scene(llm: BaseLLM, instructions: str, narrative: str,
                      location: str, daytime: str, disposition: str,
                      background: dict, ref_pairs: list[tuple[str, str]],
                      target_seconds: int) -> list[str]:
    density = background.get('density') or 'none'
    crowd = background.get('crowd_type') or ''
    bg_line = f"{density} — {crowd}" if density != 'none' and crowd else 'private, no extras'

    system = _SYSTEM_PROMPT_TEMPLATE.format(target=target_seconds)

    prompt = (
        f"{system}\n\n"
        f"SCENE: {location} | {daytime} | background: {bg_line}\n"
        f"INITIAL DISPOSITION: {disposition or '—'}\n\n"
        f"REFERENCES (inject these tags inline in every prompt):\n{_ref_table(ref_pairs)}\n\n"
        f"NARRATIVE (context only):\n{narrative.strip()}\n\n"
        f"STORYBOARD PANELS:\n{instructions.strip()}\n\n"
        "Return a JSON array of exactly 4 animation prompt strings."
    )
    return llm.make_json(prompt, schema=_CLIPS_SCHEMA)


def build_quickplay(episodes_path: Path, output_path: Path,
                    llm: BaseLLM, workers: int = 5,
                    target_seconds: int = 10) -> None:
    if not episodes_path.exists():
        raise FileNotFoundError(f"Not found: {episodes_path}")

    data = json.loads(episodes_path.read_text(encoding='utf-8'))
    characters_global: list[str] = data.get('characters', [])

    tasks = []
    for ep in data.get('episodes', []):
        eid = int(ep['episode_id'])
        narrative = ep.get('rewritten_condensed_narrative', '')
        ep_chars = ep.get('characters') or characters_global
        for scene in ep.get('scenes', []):
            sid = int(scene['scene_local_id'])
            location = scene.get('location') or ep.get('location', '')
            ref_pairs = _build_ref_pairs(ep_chars, location)
            tasks.append({
                'eid': eid, 'sid': sid,
                'instructions': scene.get('scene_instructions', ''),
                'narrative': narrative,
                'location': location,
                'daytime': ep.get('daytime', ''),
                'disposition': scene.get('initial_disposition', ''),
                'background': scene.get('background_activity') or {},
                'ref_pairs': ref_pairs,
            })

    logger.info("Synthesizing %d scenes → 4 × %ds clips…", len(tasks), target_seconds)

    results: dict[tuple[int, int], list[str]] = {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _synthesize_scene, llm,
                t['instructions'], t['narrative'], t['location'],
                t['daytime'], t['disposition'], t['background'],
                t['ref_pairs'], target_seconds
            ): t
            for t in tasks
        }
        for fut in as_completed(futures):
            t = futures[fut]
            key = (t['eid'], t['sid'])
            try:
                results[key] = fut.result()
                logger.debug("  e%03d s%d done", t['eid'], t['sid'])
            except Exception as e:
                logger.error("Failed e%03d s%d: %s", t['eid'], t['sid'], e)
                results[key] = [f"[synthesis failed: {e}]"] * 4

    output_scenes = []
    for t in tasks:
        key = (t['eid'], t['sid'])
        prompts = results.get(key, [''] * 4)
        ref_pairs = t['ref_pairs']
        output_scenes.append({
            "scene_id": f"e{t['eid']:03d}s{t['sid']}",
            "clips": [
                {"prompt": p, "references": [[name, tag] for name, tag in ref_pairs]}
                for p in prompts
            ],
        })

    result = {"scenes": output_scenes}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info("✅ quickplay.json → %s  (%d scenes × 4 clips)", output_path, len(output_scenes))
