"""Reference catalog: load ref JSONs, cast characters, enrich refs."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from lib.core.project import Project
from lib.core.prompts import DOOR_HANDEDNESS
from lib.core.schemas import CHARACTER_SCHEMA, ENRICHMENT_SCHEMA
from lib.core.utils import safe_name
from lib.llm.base import BaseLLM
from lib.studio.artist.view_catalog import _OUTDOOR_VIEWS, _ROOM_VIEWS, _VEHICLE_VIEWS

logger = logging.getLogger(__name__)


def load_character_refs(project: Project):
    """Populate project.character_images and project.character_info from ref_dir."""
    ref_dir = project.ref_dir
    for json_path in ref_dir.glob("*.json"):
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            name = char.get('name', '')
            if not name:
                continue
            project.character_info[name] = char
            png_path = json_path.with_suffix('.png')
            if png_path.exists():
                project.character_images[name] = str(png_path)
        except Exception as e:
            logger.warning(f"  ⚠️  Could not load {json_path}: {e}")

    have_png = len(project.character_images)
    total = len(project.character_info)
    logger.info(f"  📚 Character refs: {have_png} with PNG, {total - have_png} missing PNG")


def generate_single_reference(char: dict, setting_context: str, config: dict, project: Project):
    """Save character reference JSON. Image rendering is done separately by render_character_refs."""
    name = char['name']
    fname = safe_name(name)
    json_path = project.ref_dir / f"{fname}.json"
    json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
    project.character_info[name] = char
    logger.info(f"  ✅ Saved reference JSON: {name}")


def _existing_refs_context(project: Project) -> str:
    """
    Build a human-readable block describing existing refs for the casting prompt.

    Shows logline_subject_info (role) + video_visual_desc (canonical appearance)
    so the LLM can enforce appearance inheritance for character variants.
    Falls back gracefully for old JSONs missing these fields.
    """
    lines = []
    for name, info in project.character_info.items():
        role = info.get('logline_subject_info', '')
        appearance = info.get('video_visual_desc') or info.get('visual_desc', '')
        if role and appearance:
            context = f"{role} | appearance: {appearance}"
        else:
            context = role or appearance
        lines.append(f"  - {name}: {context}")
    return "\n".join(lines) if lines else "  (none yet)"


def _enrich_refs_pass(text: str, llm: BaseLLM, project: Project):
    """Pass 2: slow careful re-read for specific prop/set details not caught in pass 1.

    Appends textual findings (e.g. "coffee table has a small drawer",
    "iron safe is recessed into the left wall") to each ref's visual_desc.
    Only updates JSONs where non-empty additions are found.
    """
    if not project.character_info:
        return

    refs_block = "\n".join(
        f"  - {name}: {info.get('visual_desc', '')[:200]}"
        for name, info in project.character_info.items()
    )

    prompt = f"""You are a meticulous set designer re-reading a story text to extract specific visual details
that were missed in a first scan. Your ONLY task is to find concrete, visually actionable details
about the references listed below.

## EXISTING REFERENCES (name → current visual description excerpt):
{refs_block}

## INSTRUCTIONS
1. Re-read the text slowly, word by word.
2. For each reference, extract ONLY details explicitly stated in the text that are NOT already captured in the existing description.
   Focus on: specific props, materials, textures, colors, spatial arrangement, labels/inscriptions,
   relative positions ("clock is below the photo frame"), structural details ("drawer in the coffee table",
   "iron safe recessed into the wall"), wear/damage, lighting fixtures, brand names, etc.
3. Return ONLY references where you found new details (non-empty `visual_desc_additions`).
4. Do NOT invent details not in the text. Do NOT repeat what is already in the existing description.

Text:
<STORY>{text}</STORY>
"""

    enrichments = llm.make_json(prompt, ENRICHMENT_SCHEMA)
    if not enrichments:
        logger.info("  ℹ️  Enrichment pass: no new details found.")
        return

    updated = 0
    for item in enrichments:
        name = item.get('name', '')
        additions = item.get('visual_desc_additions', '').strip()
        if not additions or name not in project.character_info:
            if name and name not in project.character_info:
                logger.warning(f"  ⚠️  Enrichment: unknown ref '{name}' — skipping")
            continue

        sname = safe_name(name)
        json_path = project.ref_dir / f"{sname}.json"
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            char['visual_desc'] = f"{char['visual_desc'].rstrip('. ')}. {additions}"
            char['needs_regenerate'] = True
            json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
            project.character_info[name] = char
            logger.info(f"  ✏️  Enriched: {name} (+{len(additions)} chars)")
            updated += 1
        except Exception as e:
            logger.warning(f"  ⚠️  Failed to enrich {name}: {e}")

    logger.info(f"  ✅ Enrichment pass done: {updated}/{len(enrichments)} refs updated.")


def auto_cast_characters(
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    project: Project,
):
    """Identify characters/locations/objects from the text and save reference JSONs.

    The fallback when there is no story bible for the chapter: bible_casting.cast_from_bible
    plans refs from the bible instead.
    """
    load_character_refs(project)

    if not config.get('reference_characters', {}).get('enabled', True):
        logger.info("ℹ️  Casting disabled in config")
        return

    logger.info("\n🎭 CASTING: Identifying characters/locations/objects...")

    existing_context = _existing_refs_context(project)
    casting_prompt_template = prompts.get('casting', '')
    setting_context = prompts.get('setting', '')

    prompt = f"""
{casting_prompt_template}

{setting_context}

Analyze the text for KEY reference characters/locations/objects/rooms/vehicles/interfaces that will be visible on screen.

## EXISTING REFERENCES (do NOT recreate these):
{existing_context}

DEDUPLICATION RULES — read carefully:
- Match by IDENTITY, not by name. If a character/place in the text is the same entity as an existing reference (same role, same location, same object) — SKIP IT, even if the name differs slightly.
- Only add a NEW entry if it is genuinely a different entity not yet covered above.
- If unsure, prefer reusing an existing reference over creating a new one.

APPEARANCE INHERITANCE — mandatory for character variants:
- If a new ref is the same person as an existing character (same individual, different outfit/state/context), you MUST copy their physical attributes verbatim from the existing ref's appearance field above: hair color, hair style, face, skin tone, eye color, body type, age. Only describe what actually changes (clothing, accessories, emotional state). Never invent new physical traits that contradict an existing ref.

For each NEW reference, provide:
  - name: short canonical label (letters, digits, hyphens only — no quotes or parentheses)
  - logline_subject_info: one sentence — who/what this is in the story (role, relationship, function)
  - visual_desc: detailed visual description for image generation
  - video_visual_desc: short visual summary for video/animation
  - type: Character | Location | Object | Room | Vehicle | Interface | Outdoor
  - style_reference: name of an existing or new reference to use as style base
  - variations: (PRIMARY character refs only) list of variation ref slugs — e.g. ["Alisa-Jeans", "Alisa-Gown"].
    Generate ONE variation per distinct costume/context (see casting instructions). Leave empty if character has only one look.
  - character_ref: (VARIATION refs only) parent character name — e.g. "Alisa" for "Alisa-Gown". Empty for primary refs.
  - context: (VARIATION refs only) when this variation applies — e.g. "Evening formal event, theater". Empty for primary refs.

CRITICAL — Rooms, Vehicles, and Outdoor locations MUST be split into separate per-view entries (see casting instructions above).
NEVER create a single monolithic entry with type=Room, type=Vehicle, or type=Outdoor.
A bare "Room-Name" entry with type=Room is WRONG — always use ALL SIX room views:
  "{{Room-Name}}-View-From-Entrance", "{{Room-Name}}-View-To-Entrance",
  "{{Room-Name}}-View-From-Left-Wall", "{{Room-Name}}-View-From-Right-Wall",
  "{{Room-Name}}-View-Center-To-Far", "{{Room-Name}}-View-Center-To-Entrance".
A bare "Vehicle-Name" entry with type=Vehicle is WRONG — always use "{{Vehicle-Name}}-Exterior", "{{Vehicle-Name}}-Interior-From-Entrance", "{{Vehicle-Name}}-Interior-To-Entrance".
A bare "Outdoor-Name" entry with type=Outdoor is WRONG — always use the four station views "{{Outdoor-Name}}-View-Primary", "-View-Opposite", "-View-Ortho-Primary", "-View-Ortho-Opposite".
visual_desc for each view entry must describe ONE camera angle only — no TOP/BOTTOM panels, no multi-panel layouts.
DOORS (Room, Vehicle, Outdoor): {DOOR_HANDEDNESS}

Text:

<STORY>{text}</STORY>
"""

    new_chars = llm.make_json(prompt, CHARACTER_SCHEMA)

    # Reject any monolithic Room/Vehicle entries without a view suffix — the LLM
    # was explicitly told to split these; a bare entry means it ignored the rule.
    _view_suffixes = {s for s, _ in _ROOM_VIEWS + _VEHICLE_VIEWS + _OUTDOOR_VIEWS}
    bad = [c for c in (new_chars or [])
           if c.get('type') in ('Room', 'Vehicle', 'Outdoor')
           and not any(c.get('name', '').endswith(f'-{s}') for s in _view_suffixes)]
    if bad:
        bad_names = [c['name'] for c in bad]
        logger.warning(
            "  ⚠️  LLM returned monolithic Room/Vehicle/Outdoor entries (not split into views): %s. "
            "Run 'make remake-room-refs' to split them, or delete and re-cast.",
            bad_names,
        )

    if new_chars:
        ctx = f"{casting_prompt_template} {setting_context}"
        max_workers = project.max_workers
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(
                lambda char: generate_single_reference(char, ctx, config, project),
                new_chars
            ))
    else:
        logger.info("  ℹ️  Pass 1: no new references identified.")

    logger.info("\n🔍 CASTING PASS 2: Enriching refs with specific prop/set details...")
    try:
        _enrich_refs_pass(text, llm, project)
    except Exception as e:
        logger.warning(f"  ⚠️  Enrichment pass failed (non-fatal): {e}")
