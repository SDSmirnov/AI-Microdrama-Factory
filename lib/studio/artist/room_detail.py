"""Enrich room view descriptions with named positions (detail-rooms)."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from lib.core.project import Project
from lib.core.prompts import DOOR_HANDEDNESS
from lib.core.schemas import (
    ROOM_DETAIL_CRITIQUE_SCHEMA, ROOM_DETAIL_SCHEMA, ROOM_VOCABULARY_CRITIQUE_SCHEMA,
    ROOM_VOCABULARY_SCHEMA,
)
from lib.core.utils import CYR_TO_LAT, safe_name
from lib.llm.base import BaseLLM
from lib.studio.archivist import find_entity, load_bible, place_block
from lib.studio.artist.catalog import load_character_refs
from lib.studio.artist.view_catalog import _ROOM_VIEWS
from lib.studio.room_geometry import behind_camera_rule

logger = logging.getLogger(__name__)


def _section(block: str) -> str:
    return f"{block}\n\n" if block else ''


def _build_vocabulary_prompt(base: str, text: str, views: dict, bible: str = '') -> str:
    entrance_desc = views.get('View-From-Entrance', {}).get('visual_desc', '').strip()
    return (
        "You are a set decorator and spatial design specialist.\n\n"
        "Your task: derive the definitive named-position vocabulary for this location. "
        "This vocabulary will be used to write consistent descriptions for EVERY camera view "
        "of the room, so it must be view-neutral — no image-left/right references, "
        "only room-relative terms (entrance side, far side, left wall, right wall).\n\n"
        "## NOVEL EXCERPT (who uses this space, what roles/jobs they have, "
        "what actions happen here, which props are mentioned):\n"
        f"<STORY>{text}</STORY>\n\n"
        f"## LOCATION: {base}\n\n"
        "## CURRENT BASE DESCRIPTION (View-From-Entrance):\n"
        f"{entrance_desc}\n\n"
        f"{_section(bible)}"
        "## PROCESS:\n\n"
        "### STEP 1 — ENVIRONMENT TYPE REASONING\n"
        "Identify the space type (office, cafe, kitchen, garage, hospital ward, prison cell, "
        "living room, etc.). List what items are TYPICALLY present in such a space: "
        "furniture, equipment, surfaces, fixtures, materials, lighting. "
        "What would a visitor notice first? What is on every desk/counter/shelf/wall "
        "in this kind of place?\n\n"
        "### STEP 2 — STORY-REQUIRED SPECIFICS\n"
        "Re-read the novel excerpt. For each character who uses this space:\n"
        "- What is their ROLE/JOB? Role determines what is on their station:\n"
        "  a bank clerk gets a phone unit and a paper tray; a manager gets a leather chair, "
        "  a nameplate, a document inbox; a sous chef gets a mise en place rack and sharpening "
        "  steel; a mechanic apprentice gets basic hand tools, the senior gets the diagnostic "
        "  scanner and lift remote.\n"
        "- Which actions happen at their spot? What props must be physically present?\n"
        "- Which props are explicitly named in the text? Place them exactly.\n"
        "- Every STORY BIBLE feature is here from the start, even when this excerpt never uses it; "
        "give each one an entry with its bible id as the id.\n"
        "- Any recurring visits to the same spot? Give it a stable anchor label.\n\n"
        "### STEP 3 — BUILD NAMED POSITIONS\n"
        "For every named character position and every shared landmark, produce one entry:\n"
        "- id: kebab-case, character-prefixed for personal spots (amanda-desk, lena-workstation, "
        "  igors-office-chair) or object-prefixed for shared items (service-counter, repair-lift).\n"
        "- kind: object (furniture, fixture, opening, prop), zone (a standing spot or open floor, never on "
        "  furniture) or room-wide (the room as a whole, its size, light or atmosphere). A thing the text says "
        "  is absent is no entry: write the bare wall into the room-wide description.\n"
        "- description: furniture type + exact room location (entrance-side / far-side / "
        "  left-wall / right-wall + distance estimate) + orientation + full item list on/near it.\n"
        "  Example: 'amanda-desk: 3rd glossy white plastic desk from the entrance on the "
        "  left-wall row. Ergonomic swivel chair behind it facing the right wall. "
        "  DELL 24\" monitor at center, Logitech keyboard in front, paper tray upper-right "
        "  corner, Panasonic desk phone lower-left, name holder at front edge.'\n"
        "- No vague phrases — 'standard equipment', 'various tools', 'usual items' are forbidden.\n"
        f"- Doors: {DOOR_HANDEDNESS}"
    )


def _build_view_prompt(base: str, suffix: str, view_desc: str, vocabulary: list[dict]) -> str:
    vocab_block = "\n".join(
        f"  [{item['id']}] {item['description']}" for item in vocabulary
    )
    return (
        "You are a set decorator writing a production-ready room description for a single "
        "camera view of a cinematic location.\n\n"
        f"## LOCATION: {base}\n"
        f"## VIEW: {suffix}\n{behind_camera_rule(suffix)}\n\n"
        "## SHARED NAMED-POSITION VOCABULARY (use these labels and descriptions verbatim):\n"
        f"{vocab_block}\n\n"
        "## CURRENT VIEW DESCRIPTION:\n"
        f"{view_desc}\n\n"
        "## YOUR TASK\n"
        "Rewrite the current view description using the shared vocabulary above. Rules:\n"
        "1. Every named position from the vocabulary must appear with its label in backticks, "
        "placed correctly for THIS camera angle; one behind the camera is named once as "
        "behind the camera, never placed in frame.\n"
        "2. image-left / image-right / depth order must match this specific view's perspective.\n"
        "3. Add any equipment or props from the vocabulary that the current description omits.\n"
        "4. Preserve room dimensions, ceiling height, lighting, flooring, and architectural "
        "features from the current description.\n"
        f"   {DOOR_HANDEDNESS}\n"
        "5. End with: 'Empty room, no people, architectural photography.'\n"
        "6. Do NOT invent items not in the vocabulary or the current description."
    )


_ARCHITECTURE_RULE = (
    "Doors, hatches, windows, arches and other openings exist ONLY where the story or the "
    "current description puts them: their count, wall and position are fixed. A plausible "
    "extra opening is a defect, because every camera view is generated from this text."
)


def _build_vocabulary_critique_prompt(base: str, text: str, entrance_desc: str,
                                      vocabulary: list[dict], bible: str = '') -> str:
    vocab = json.dumps(vocabulary, indent=1, ensure_ascii=False)
    return (
        "You are a script supervisor auditing a set decorator's named-position vocabulary "
        "before it is used to describe every camera view of one room.\n\n"
        f"## LOCATION: {base}\n\n"
        f"## NOVEL EXCERPT\n<STORY>{text}</STORY>\n\n"
        f"## CURRENT BASE DESCRIPTION (View-From-Entrance)\n{entrance_desc}\n\n"
        f"{_section(bible)}"
        f"## DRAFT VOCABULARY\n{vocab}\n\n"
        "## CHECK EACH ENTRY\n"
        f"1. Openings: {_ARCHITECTURE_RULE}\n"
        "2. Contradictions: nothing may contradict the story or the base description "
        "(materials, which wall, who sits where, what is on a desk).\n"
        "3. Physics: entries must fit the room dimensions without overlapping, block no "
        "door, and face a direction the story allows.\n"
        "4. Duplicates: one id per physical object; no two ids for the same thing.\n"
        "5. Coverage: every prop or station the story uses in this room has an entry, and so does "
        "every STORY BIBLE feature (a later chapter uses it; it must exist from the first frame).\n"
        "6. View-neutral wording: no image-left/right; only entrance side, far side, left "
        "wall, right wall, with a distance estimate.\n"
        "7. Ids are kebab-case; keep existing ids unless the entry is removed.\n"
        f"8. Doors: {DOOR_HANDEDNESS} A door entry missing any of the three is a defect.\n"
        "9. Kind: an object has a footprint, a zone is free floor beside furniture, a room-wide entry is the "
        "room itself, its size, light or atmosphere. An entry for something absent is removed.\n\n"
        "Return every defect in issues and the corrected named_positions. Typical set "
        "dressing the story does not contradict may stay; invented openings may not."
    )


def _build_view_critique_prompt(base: str, suffix: str, camera: str, original_desc: str,
                                draft: str, vocabulary: list[dict], missing: list[str]) -> str:
    vocab_block = "\n".join(f"  [{item['id']}] {item['description']}" for item in vocabulary)
    missing_note = (
        f"\nDETERMINISTIC CHECK: these ids are missing from the draft: {', '.join(missing)}\n"
        if missing else ''
    )
    return (
        "You are a script supervisor auditing one camera view's room description.\n\n"
        f"## LOCATION: {base}\n## VIEW: {suffix}\n## CAMERA: {camera}\n{behind_camera_rule(suffix)}\n\n"
        f"## NAMED-POSITION VOCABULARY\n{vocab_block}\n\n"
        f"## ORIGINAL VIEW DESCRIPTION\n{original_desc}\n\n"
        f"## DRAFT TO AUDIT\n{draft}\n{missing_note}\n"
        "## CHECK\n"
        "1. Every vocabulary id appears in backticks. One behind the camera is stated as "
        "behind the camera; describing it in frame is a defect.\n"
        "2. image-left / image-right / depth order are correct for THIS camera; derive them "
        "from the room-relative wording, do not copy another view's sides.\n"
        f"3. {_ARCHITECTURE_RULE}\n"
        "4. No object outside the vocabulary or the original description.\n"
        "5. Dimensions, ceiling height, materials, flooring and lighting from the original "
        "description are preserved.\n"
        "6. It ends with 'Empty room, no people, architectural photography.'\n"
        f"7. Doors: {DOOR_HANDEDNESS} A door whose hinge, handle or swing differs from the "
        "vocabulary is a defect.\n\n"
        "List every defect in issues and return the corrected description."
    )


def _critique_vocabulary(llm: BaseLLM, base: str, text: str, entrance_desc: str,
                         vocabulary: list[dict], bible: str = '') -> list[dict]:
    """One self-critique round on the vocabulary; keeps the draft if the critic fails."""
    result = llm.make_json(
        _build_vocabulary_critique_prompt(base, text, entrance_desc, vocabulary, bible),
        ROOM_VOCABULARY_CRITIQUE_SCHEMA,
    ) or {}
    for issue in result.get('issues') or []:
        logger.info(f"  🔎 {base} vocabulary: {issue}")
    revised = [p for p in result.get('named_positions') or [] if p.get('id')]
    if not revised:
        logger.warning(f"  ⚠️  {base}: vocabulary critique returned nothing — keeping draft")
        return vocabulary
    return revised


def _ascii_ids(base: str, vocabulary: list[dict]) -> list[dict]:
    """Ids are matched verbatim downstream: a stray Cyrillic letter ("birbanте-spot") must not survive."""
    fixed = []
    for p in vocabulary:
        kebab = re.sub(r'[^a-z0-9]+', '-', p['id'].lower().translate(CYR_TO_LAT)).strip('-')
        if kebab != p['id']:
            logger.warning(f"  ⚠️  {base}: id {p['id']!r} → {kebab!r}")
        fixed.append({**p, 'id': kebab})
    return fixed


def _missing_ids(desc: str, vocabulary: list[dict]) -> list[str]:
    return [item['id'] for item in vocabulary if item['id'] not in desc]


def _critique_view(llm: BaseLLM, base: str, suffix: str, original_desc: str, draft: str,
                   vocabulary: list[dict]) -> str:
    """One self-critique round on a view description; keeps the draft if the critic fails."""
    camera = dict(_ROOM_VIEWS).get(suffix, '')
    result = llm.make_json(
        _build_view_critique_prompt(base, suffix, camera, original_desc, draft, vocabulary,
                                    _missing_ids(draft, vocabulary)),
        ROOM_DETAIL_CRITIQUE_SCHEMA,
    ) or {}
    for issue in result.get('issues') or []:
        logger.info(f"  🔎 {base}-{suffix}: {issue}")
    return (result.get('revised_visual_desc') or '').strip() or draft


def detail_room_refs(text: str, llm: BaseLLM, project: Project, force: bool = False):
    """Enrich Room ref visual_desc with named furniture, equipment, and per-character anchor labels.

    Two-phase per room, each phase followed by one self-critique round:
      Phase 1 — one LLM call derives a view-neutral named-position vocabulary (roles, equipment,
                 anchor labels). Short focused output, not view-specific.
      Phase 2 — one LLM call per view (parallel) writes the enriched visual_desc for that angle,
                 injecting the Phase 1 vocabulary verbatim.

    The vocabulary is saved as room_vocabulary: the VFE QA inventory.

    Runs AFTER casting, BEFORE refs. Sets needs_regenerate=True on views with existing PNGs.
    Idempotent: skips rooms where any view already carries details_applied=True unless force=True.
    """
    load_character_refs(project)

    all_suffixes = [s for s, _ in _ROOM_VIEWS]

    rooms: dict[str, dict[str, dict]] = {}
    for name, info in project.character_info.items():
        if info.get('type') != 'Room':
            continue
        for suffix in all_suffixes:
            if name.endswith(f'-{suffix}'):
                base = name[:-(len(suffix) + 1)]
                rooms.setdefault(base, {})[suffix] = info
                break

    if not rooms:
        logger.info("  ℹ️  No Room refs found.")
        return

    targets = [
        (base, views)
        for base, views in rooms.items()
        if force or not any(v.get('details_applied') for v in views.values())
    ]

    if not targets:
        logger.info("  ✅ All room refs already have details applied (use --force to redo).")
        return

    logger.info(f"  🏢 Detailing {len(targets)} room(s)...")
    story_bible = load_bible(project.bible_dir)

    for base, views in targets:
        logger.info(f"  📋 {base}: Phase 1 — building named-position vocabulary...")

        bible = place_block(story_bible, base)
        vocab_result = llm.make_json(_build_vocabulary_prompt(base, text, views, bible), ROOM_VOCABULARY_SCHEMA)
        if not vocab_result or not vocab_result.get('named_positions'):
            logger.warning(f"  ⚠️  {base}: vocabulary pass returned nothing — skipping")
            continue

        entrance_desc = views.get('View-From-Entrance', {}).get('visual_desc', '').strip()
        vocabulary = _ascii_ids(base, _critique_vocabulary(
            llm, base, text, entrance_desc, vocab_result['named_positions'], bible
        ))
        logger.info(f"  📐 {base}: {len(vocabulary)} named positions established")
        ids = {p['id'] for p in vocabulary}
        if lost := [ft['id'] for ft in (find_entity(story_bible, base) or {}).get('features') or []
                    if ft['id'] not in ids]:
            logger.warning(f"  ⚠️  {base}: story-bible features without a named position: {', '.join(lost)}")

        present_views = [(suffix, views[suffix]) for suffix in all_suffixes if suffix in views]

        logger.info(f"  📋 {base}: Phase 2 — enriching {len(present_views)} views in parallel...")

        def _enrich_view(args: tuple) -> tuple[str, str]:
            suffix, info = args
            full_name = f"{base}-{suffix}"
            view_desc = info.get('visual_desc', '').strip()
            result = llm.make_json(_build_view_prompt(base, suffix, view_desc, vocabulary), ROOM_DETAIL_SCHEMA)
            enriched = (result or {}).get('enriched_visual_desc', '').strip()
            if enriched:
                enriched = _critique_view(llm, base, suffix, view_desc, enriched, vocabulary)
                if missing := _missing_ids(enriched, vocabulary):
                    logger.warning(f"  ⚠️  {full_name}: ids still missing after critique: "
                                   f"{', '.join(missing)}")
            return full_name, enriched

        with ThreadPoolExecutor(max_workers=project.max_workers) as executor:
            view_results = list(executor.map(_enrich_view, present_views))

        updated = 0
        for name, enriched in view_results:
            if not enriched:
                logger.warning(f"  ⚠️  {name}: empty result — skipping")
                continue
            if name not in project.character_info:
                logger.warning(f"  ⚠️  Unknown ref '{name}' — skipping")
                continue

            sname = safe_name(name)
            json_path = project.ref_dir / f"{sname}.json"
            try:
                char = json.loads(json_path.read_text(encoding='utf-8'))
                char['visual_desc'] = enriched
                char['room_vocabulary'] = vocabulary
                char['details_applied'] = True
                if (project.ref_dir / f"{sname}.png").exists():
                    char['needs_regenerate'] = True
                json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
                project.character_info[name] = char
                logger.info(f"  ✏️  {name}: visual_desc enriched ({len(enriched)} chars)")
                updated += 1
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to save {name}: {e}")

        logger.info(f"  ✅ {base}: {updated} views updated")

    logger.info("  ✅ detail-rooms done.")
