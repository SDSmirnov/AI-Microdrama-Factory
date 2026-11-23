"""
Reference assembler: panel metadata -> ordered <IMAGE_N> reference bites.

Item 2 of GROK-VIDEO-PLAN. One decision lives here: which refs enter a video
call, in what order, with what descriptor, and what gets dropped from the
budget. Consumers (prompt builder Item 3, animators Item 4) read the returned
RefBite list and never re-derive refs from metadata themselves.

Tag order: <IMAGE_0> = first frame (a frame_images entry, not an
input_reference), <IMAGE_1..N> = refs in this list's order. The prompt builder
consumes the same list, so descriptor text stays bound to the right slot by
construction. (OpenRouter's numbering of a combined frame_images +
input_references payload is unverified — probe 3 falsifies; a change to the
numbering is a one-line edit here.)
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from lib.core.utils import canonical_ref_name
from lib.llm.openrouter import VIDEO_MAX_REFS

logger = logging.getLogger(__name__)

# VIDEO_MAX_REFS counts every input image; the first frame takes one of them.
MAX_REFS_CAP = VIDEO_MAX_REFS - 1

# Ref types that mark a slug as a location view (character names never carry them).
_LOCATION_TYPES = {'room', 'vehicle', 'outdoor'}


@dataclass
class RefBite:
    tag: str          # "<IMAGE_0>", "<IMAGE_1>", ...
    png: Path | None  # None = ref exists in catalog but has no PNG yet
    role: str         # "first_frame" | "location" | "character" | "prop"
    name: str         # ref slug as referenced (may be a variant slug)
    descriptor: str   # one-line anchors for the ACTIVE REFERENCES block

    @property
    def is_location(self) -> bool:
        return self.role == "location"


def default_max_refs() -> int:
    """AI_VIDEO_MAX_REFS decides the per-clip reference budget (default 8)."""
    try:
        return max(1, min(int(os.getenv('AI_VIDEO_MAX_REFS', '8')), MAX_REFS_CAP))
    except ValueError:
        return 8


def _norm(slug: str) -> str:
    """Tolerant lookup key: case- and underscore-insensitive (veo.py's
    stem.replace('_',' ').title() generates slugs that drift both ways)."""
    return slug.strip().lower().replace('_', '-')


class _RefCatalog:
    """Slug -> (ref JSON, png path) resolution over project caches + ref_dir."""

    def __init__(self, project):
        self.info = {  # normalized slug -> ref JSON
            _norm(name): info for name, info in (project.character_info or {}).items()
        }
        self.images = {  # normalized slug -> png path (preloaded by load_character_refs)
            _norm(name): Path(v) for name, v in (project.character_images or {}).items()
        }
        # PNGs present in ref_dir but not (yet) in character_images.
        for p in (project.ref_dir or Path()).glob("*.png"):
            self.images.setdefault(_norm(p.stem), p)

    def lookup(self, slug: str):
        """Return (ref_json | None, png_path | None). Tries the slug, then its
        canonical derivation (View-To-Entrance -> View-From-Entrance). A pair is
        preferred complete; when the exact entry lacks a PNG, the canonical
        entry's PNG (and its descriptor source) is used instead."""
        candidates = [(self.info.get(k := _norm(name)), self.images.get(k))
                      for name in (slug, canonical_ref_name(slug))]
        for info, png in candidates:  # complete entry wins outright
            if info is not None and png is not None:
                return info, png
        for info, png in candidates:  # PNG-bearing entry defines what is sent
            if png is not None:
                return info, png
        for info, png in candidates:  # catalog-known but PNG-less
            if info is not None:
                return info, None
        return None, None


def _png_only(catalog: _RefCatalog, slug: str) -> Path | None:
    _, png = catalog.lookup(slug)
    return png


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def _descriptor_for(info: dict | None, slug: str) -> str:
    """One-line minimal anchors: characters/props -> video_visual_desc;
    rooms -> first line of visual_desc (plan-specified sources)."""
    if not info:
        return ""
    if (info.get('type', '') or '').lower() in _LOCATION_TYPES:
        return _first_line(info.get('visual_desc', '')) or info.get('video_visual_desc', '')
    return info.get('video_visual_desc', '')


def _location_bites(catalog: _RefCatalog, panel: dict, next_tag) -> tuple[list, int]:
    """location_references in panel order; carried-state pose lines excluded.
    Returns (bites, number_allocated)."""
    bites = []
    for slug in panel.get('location_references') or []:
        info, png = catalog.lookup(slug)
        if not info and not png:
            logger.warning("    📍 Location ref not found in catalog, dropped: %s", slug)
            continue
        if png is None:
            logger.warning("    📍 Location ref has JSON but no PNG, dropped: %s", slug)
            continue
        bites.append(RefBite(tag=next_tag(), png=png, role="location",
                             name=slug, descriptor=_descriptor_for(info, slug)))
    return bites


def _character_region_slugs(state: dict | None, panel: dict,
                            known_locations: set) -> list:
    """Ordered (slug, actor_entry | None, role) candidates for the character
    region. With state: state.actors in_frame only (an actor listed but
    off-frame must not enter the call), respecting visual_ref variants.
    Without state: panel.references (chars + props, minus location slugs)."""
    if state and state.get('actors') is not None:
        return [
            (a.get('visual_ref') or a.get('name', ''), a, "character")
            for a in state['actors']
            if a.get('in_frame') and (a.get('visual_ref') or a.get('name'))
        ]
    out = []
    for slug in panel.get('references') or []:
        if slug in known_locations:
            continue
        out.append((slug, None, None))  # role decided after catalog type lookup
    return out


def _region_bites(catalog: _RefCatalog, candidates: list, next_tag,
                  budget_left: list) -> list:
    """Character/prop bites with variant PNG fallback to the primary ref.
    budget_left is a one-element list so exhaustion propagates to the caller."""
    bites = []
    for slug, actor, forced_role in candidates:
        if budget_left[0] <= 0:
            logger.warning("    🎒 Ref budget exhausted, dropped '%s': "
                           "over AI_VIDEO_MAX_REFS budget.", slug)
            continue
        info, png = catalog.lookup(slug)
        display_name = slug
        # Variant without its own PNG: fall back to the primary ref PNG
        # (same character, base costume) with a log line — plan-specified
        # fail mode until visual_ref->PNG mapping is pilot-verified.
        if png is None and actor and actor.get('name') and actor['name'] != slug:
            px = _png_only(catalog, actor['name'])
            if px is not None:
                logger.warning("    🎭 Variant PNG missing for '%s' — "
                               "falling back to primary ref '%s'.", slug, actor['name'])
                png = px
                info = info or catalog.lookup(actor['name'])[0]
        if png is None:
            logger.warning("    🎭 Ref has no resolvable PNG, dropped: %s", slug)
            continue
        budget_left[0] -= 1
        role = forced_role
        if role is None:
            t = (info or {}).get('type', '')
            role = "location" if str(t).lower() in _LOCATION_TYPES else (
                "character" if str(t).lower() in {'character', 'person'} or not t else "prop")
            if role == "location":
                # A room view inside references: not a character slot, but a
                # location bite; it still came from a slug someone listed.
                role = "location"
            elif not t:
                role = "prop"
        descriptor = _descriptor_for(info, slug)
        if actor:  # current state anchors: pose / position / gaze
            pose = actor.get('pose', '')
            pos = actor.get('position', '')
            gaze = actor.get('gaze_target') or ''
            state_line = " | ".join(
                p for p in (f"pose: {pose}" if pose else "",
                            f"position: {pos}" if pos else "",
                            f"gaze: {gaze}" if gaze else "") if p)
            if state_line:
                descriptor = f"{descriptor} — {state_line}" if descriptor else state_line
        bites.append(RefBite(tag=next_tag(), png=png, role=role,
                             name=display_name, descriptor=descriptor))
    return bites


def assemble_refs(panel: dict, scene: dict, panels_dir: Path, project,
                  max_refs: int = None) -> list[RefBite]:
    """Ordered <IMAGE_N> ref bites for one panel (plan Item 2).

    Resolution order: first frame (uncapped) -> location refs -> in-frame
    characters (state) or panel.references (no state). Budget `max_refs`
    counts refs only — never the first frame; drops are logged with reasons.
    """
    if max_refs is None:
        max_refs = default_max_refs()
    catalog = _RefCatalog(project)
    bites: list[RefBite] = []
    counter = [0]

    def next_tag() -> str:
        counter[0] += 1
        return f"<IMAGE_{counter[0]}>"

    # 1. First frame: {scene:03d}_{panel:02d}_static.png (uncapped, = <IMAGE_0>).
    scene_id = int(scene.get('scene_id', 0) or 0)
    panel_index = int(panel.get('panel_index', 0) or 0)
    static = panels_dir / f"{scene_id:03d}_{panel_index:02d}_static.png"
    if static.exists():
        bites.append(RefBite(tag="<IMAGE_0>", png=static, role="first_frame",
                             name=static.stem, descriptor=""))
    else:
        logger.warning("    🖼️  First frame missing: %s", static)

    # 2. Locations (carried-state pose lines excluded).
    budget_left = [max_refs]
    loc_bites = _location_bites(catalog, panel, next_tag)
    for b in loc_bites:
        if budget_left[0] <= 0:
            logger.warning("    🎒 Ref budget exhausted, dropped location '%s': "
                           "over AI_VIDEO_MAX_REFS budget.", b.name)
            break
        budget_left[0] -= 1
        bites.append(b)
    known_locations = {b.name for b in bites}

    # 3. Character/prop region.
    candidates = _character_region_slugs(panel.get('state'), panel, known_locations)
    bites.extend(_region_bites(catalog, candidates, next_tag, budget_left))
    return bites
