"""
Structured video prompt builder (Item 3, GROK-VIDEO-PLAN).

build_video_prompt() assembles the prompt from panel metadata + RefBite
(Item 2) + VoiceBite lists — nine fixed blocks in fixed order. Shared by every
animator (Grok via OpenRouter and x.ai direct, Veo); x.ai direct and Veo send
no reference bites. Transport details stay out of here.

Deleted relative to the old _build_prompt paths: raw-dict interpolation,
hardcoded genre line ("Filming Action Movie") and hardcoded lens line
("Arri Alexa Mini LF 50mm"). Veo/quickplay keep their own behavior; these
Grok animators use POSITIVE_PHOTO_LOCKS (positive phrasing) PLUS the hard
prohibition text restored verbatim as the HARD PROHIBITIONS block (real-
clip evidence 2026-11-11: positive phrasing alone doesn't stop the
exaggeration drift — tears, vapor, theatrical facial extremes).
"""
import logging
import os
import re
from dataclasses import dataclass

from lib.animation.refs import RefBite  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)

# Lens -> diagonal FOV degrees (full-frame ladder, cinematography standard).
_FOV_LADDER = ((8, 180), (12, 135), (16, 107), (24, 84), (35, 63),
               (50, 47), (85, 29), (135, 18), (200, 12), (300, 8))

# Observable outcome phrases per FOV degree (what the glass does, not adjectives).
_FOV_OUTCOME = {
    180: "edge-warping fisheye: straight lines bend, space balloons at the rim",
    135: "ultra-wide: edge stretching at the frame rim, very deep space",
    107: "very wide: expansive space, mild edge stretching",
    84: "wide: energetic framing, rooms read bigger than they are",
    63: "mildly wide: natural-ish depth with visible background",
    47: "standard: human-scale framing, perspective matches the eye",
    29: "short telephoto: gentle compression, flattering face volume",
    18: "telephoto: background pulled close, flattened depth",
    12: "long telephoto: heavy compression, image layers stacked",
    8: "extreme telephoto: planes stacked, distance shows only in sizes",
}

_SCALE_WORDS = {
    "ECU": "extreme close-up", "CU": "close-up", "MCU": "medium close-up",
    "MS": "medium shot", "MWS": "medium wide shot", "WS": "wide shot",
    "XWS": "extreme wide shot",
}

# Positive-phrasing photoreal guards (replaces the ANIMATION_PROHIBITIONS pile
# in these two animators only; Veo/quickplay keep their existing behavior).
POSITIVE_PHOTO_LOCKS = (
    "PHOTOGRAPHIC REALISM (positive locks): true photographic texture — visible "
    "skin pores and a natural micro-expression range; clean, dry skin; real hair "
    "movement; cloth with weight that wraps the body; one continuous take with a "
    "real operator's small corrective motion; light obeys the geometry — bodies "
    "and objects occlude it consistently; art-directed film-grade color."
)

# The single-shot variant keeps the "one continuous take" clause; a
# multi-shot panel must NOT say that, or it contradicts the shot list.
POSITIVE_PHOTO_LOCKS_MULTISHOT = (
    "PHOTOGRAPHIC REALISM (positive locks): true photographic texture — visible "
    "skin pores and a natural micro-expression range; clean, dry skin; real hair "
    "movement; cloth with weight that wraps the body; a real operator's small "
    "corrective motion; light obeys the geometry — bodies and objects occlude "
    "it consistently; art-directed film-grade color. Each shot is a separate "
    "take with a real operator's small corrective motion, and the cuts between "
    "shots are clean and motivated."
)

_HEADER_RE = re.compile(
    r"^(?:\[SCALE\]\s*)?(?P<scale>\S+)\s+(?P<lens>\d{1,3})\s*mm\s+"
    r"(?P<angle>\S+)\s+cam@\[?(?P<anchor>[^\]\s]+)\]?",
    re.IGNORECASE,
)
_LIGHTING_LINE_RE = re.compile(r"^(LIGHT|BGD):\s", re.MULTILINE)


@dataclass
class VoiceBite:
    """One resolved voice slot (Item 5b produces these; builder renders them)."""
    tag: str      # "<AUDIO_0>", "<AUDIO_1>", ... — empty on the OpenRouter route
    speaker: str  # ref-side character name for tag binding
    line: str     # spoken text
    kind: str     # "dialogue" | "voiceover"
    descriptor: str = ""  # prose voice steer (OpenRouter: bound to <IMAGE_N>)


@dataclass
class ActingBite:
    """One in-frame character's acting contribution (Item 7b)."""
    name: str       # ref-side character name
    tag: str        # "<IMAGE_N>" the character's reference binds to
    physical: str   # physical_vocabulary, word-capped
    behavioral: str  # behavioral_signature, word-capped
    state: str      # "pose: ... | position: ... | gaze: ..." from actor entry


# Item 7b caps (words). Constant here so the budget is auditable in dumps.
ACTING_PHYS_CAP = 35
ACTING_BEH_CAP = 25
ACTING_TOTAL_CAP = 120

# Item 8a bounds (chars): keep the map compact enough for every clip prompt.
_SPATIAL_COMPASS_CAP = 300
# One disposition line = one SENTENCE (a whole spatial fact binding several
# anchors), so this cap covers a full sentence, not a fragment of one.
_SPATIAL_DISPO_CAP = 420


def _words(text: str, cap: int) -> str:
    out = (text or "").strip().split()
    return " ".join(out[:cap])


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", (name or "").lower().replace("ё", "е"))


def build_acting(panel: dict, refs: list, character_info: dict) -> list:
    """Item 7b consumption: one ActingBite per in-frame character.

    Acting data flows from ref JSONs (character_info), never from panel
    metadata. Priority: the dialogue speaker first (nick matched to the
    character name, transliteration-aware via voices._norm), then ref order.
    Empty acting fields -> clause omitted, logged once per run.
    """
    from lib.animation.voices import _norm  # deferred: voices imports us

    ref_names = {b.name: b for b in (refs or []) if b.role == "character"}
    if not ref_names:
        return []
    state_by_name = {}
    for a in ((panel.get("state") or {}).get("actors") or []):
        slug = a.get("visual_ref") or a.get("name", "")
        if a.get("in_frame") and slug:
            state_by_name.setdefault(slug, a)

    dialogue = panel.get("dialogue", "") or ""
    speaker_nicks = [h.split("(")[0].strip()
                     for h, _ in _split_dialogue(dialogue) if h]

    acting, missing = [], []
    # speaker-first order: any ref whose name matches a dialogue nick
    # (transliteration-aware: 'Ху' -> 'hu' matches Private-Hu)
    def _order(name):
        lat = _norm(name)
        for i, nick in enumerate(speaker_nicks):
            n = _norm(nick)
            if n and (n in lat or lat in n):
                return (0, i)
        return (1, list(ref_names).index(name))
    ordered = sorted(ref_names, key=_order)

    total = 0
    for name in ordered:
        bite = ref_names[name]
        info = (character_info or {}).get(name) or {}
        phys = _words(info.get("physical_vocabulary"), ACTING_PHYS_CAP)
        beh = _words(info.get("behavioral_signature"), ACTING_BEH_CAP)
        if not phys and not beh:
            missing.append(name)
            continue
        a = state_by_name.get(name) or {}
        state = " | ".join(p for p in (
            f"pose: {a.get('pose')}" if a.get('pose') else "",
            f"position: {a.get('position')}" if a.get('position') else "",
            f"gaze: {a.get('gaze_target')}" if a.get('gaze_target') else "",
        ) if p)
        w = len(phys.split()) + len(beh.split()) + len(state.split())
        if total + w > ACTING_TOTAL_CAP:
            logger.info("    ACTING word budget (%d) exhausted; later "
                        "in-frame actor '%s' truncated.", ACTING_TOTAL_CAP, name)
            left = ACTING_TOTAL_CAP - total
            if left <= 0:
                break
            phys = _words(phys, max(0, left - len(state.split()) // 2))
            w = len(phys.split()) + len(beh.split()) + len(state.split())
            if w > ACTING_TOTAL_CAP - total:
                beh = ""
            w = len(phys.split()) + len(beh.split()) + len(state.split())
            if w > ACTING_TOTAL_CAP - total:
                state = ""
            total += len(phys.split()) + len(beh.split()) + len(state.split())
        else:
            total += w
        acting.append(ActingBite(name=name, tag=bite.tag,
                                 physical=phys, behavioral=beh, state=state))
    if missing:
        logger.info("    Acting fields empty for %s — ACTING clause omitted "
                    "(EYE LIFE default retained).", ", ".join(missing))
    return acting


def _acting_block(acting: list) -> str:
    """ACTING text: per-character clause + fixed EYE LIFE default line."""
    lines = []
    for a in acting or []:
        parts = []
        if a.physical:
            parts.append(a.physical)
        if a.behavioral:
            parts.append(a.behavioral)
        if not parts:
            continue
        clause = "; ".join(parts)
        if a.state:
            clause = f"{clause}; current state — {a.state}"
        lines.append(f"{a.name} ({a.tag}): {clause}")
    eye = ("EYE LIFE (default for everyone): saccades every 1–2 s; blink "
           "rate follows the emotional state of the shot; gaze holds the "
           "stated subject with micro-refocus; catchlights stay alive even "
           "in shadow. Character-specific eye behavior only via their "
           "behavioral_signature above.")
    return "\n".join(lines + [eye])


def _variant_of(slug: str) -> str:
    """View-variant token from a location ref slug: 'X-View-To-Entrance'
    -> 'To-Entrance'; no '-view-' -> 'Primary'."""
    m = re.search(r"-view-([a-z-]+)$", (slug or "").lower())
    return (m.group(1) if m else "primary").title().replace("-", "-")


def _compass_sentence(axes: str, variant: str) -> str:
    """The axes sentence(s) that describe this camera view variant."""
    axes = (axes or "").strip()
    if not axes:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", axes)
    if variant.lower() == "primary":
        head = []
        for s in sentences:  # base mapping until the first View- note
            if re.search(r"View[-/ ]", s):
                break
            head.append(s)
        if head:
            return " ".join(head)
    wanted = variant.lower().split("-")
    hits = [s for s in sentences
            if re.search(r"view[-/ \w]*" + r"[-/ ]".join(
                map(re.escape, wanted)), s, re.I)]
    if hits:
        return " ".join(hits)
    # Variant not spelled out in the axes prose: give the base mapping.
    head = [s for s in sentences if not re.search(r"View[-/ ]", s)]
    return " ".join(head) if head else axes[:_SPATIAL_COMPASS_CAP]


def build_spatial_map(scene: dict, catalog) -> str:
    """Item 8a: fixed geography block for every clip prompt of a scene.

    From already-stored anchor JSONs only: compass line derived from the
    view slug (camera side = the 180-degree boundary, per the anchor
    JSON's axes), landmark list from anchor_points objects, one
    disposition line per disposition SENTENCE (the sentence carries the
    anchor), deduplicated by anchor name (first mention wins). Returns ""
    (and logs once) when no anchor JSON is available — the block is then
    omitted. Computed in memory; no metadata writes.

    catalog: duck-typed lib.animation.refs._RefCatalog (.info slug->ref
    JSON dict, .lookup(slug)).
    """
    panels = sorted((scene or {}).get("panels", []),
                    key=lambda p: p.get("panel_index", 0))
    locations = [p.get("location_references") or [] for p in panels]
    flat = [loc for locs in locations for loc in locs if loc]
    if not flat:
        return ""
    # Dominant location ref of the scene (scenes are single-location).
    loc = max(set(flat), key=flat.count)

    info, _ = (catalog.lookup(loc) if catalog else (None, None))
    anchor = None
    if info and (info.get("anchor_points") or {}).get("objects"):
        anchor = info
    else:
        # Populated sibling of the same location: '<loc>-view-<variant>'
        # variant JSONs are often empty; the location's primary (or any
        # populated sibling) carries the shared anchor_points geometry.
        base = re.sub(r"-view-[a-z-]+$", "", (loc or "").lower())
        for slug, candidate in sorted((catalog.info or {}).items()):
            if (slug.startswith(base) and candidate is not info
                    and (candidate.get("anchor_points") or {}).get("objects")):
                anchor = candidate
                break
    if not anchor:
        logger.info("    Spatial map omitted for scene %s: no anchor JSON "
                    "for location ref '%s'.", (scene or {}).get("scene_id"),
                    loc)
        return ""

    ap = anchor["anchor_points"]
    variant = _variant_of(loc)
    compass = _compass_sentence(ap.get("axes"), variant)
    compass = compass[:_SPATIAL_COMPASS_CAP].rstrip()
    lines = [f"GEOMETRY — camera side (view {loc}) fixes the 180-degree "
             f"line: {compass}"]

    landmarks = ", ".join(f"[{o.get('id')}]" for o in ap.get("objects", [])
                          if o.get("id"))
    if landmarks:
        lines.append(f"Landmarks (stable across every shot in this "
                     f"location): {landmarks}.")

    # One line per disposition SENTENCE, never one per anchor.
    #
    # The disposition prose is one sentence per actor and each sentence binds
    # SEVERAL anchors in one coherent spatial fact ("Lin-Wei-ming stands
    # braced at [seaward-embrasure-lip] above [bluff-silhouette-south] with
    # the T91 resting on [sandbag-crenellations-north]"). A paragraph with N
    # anchors is therefore ONE fact, not N facts. Emitting a line per anchor
    # forced the whole paragraph to be pasted N times (N identical copies of
    # the same prose) because no fragment of it describes a single anchor on
    # its own.
    #
    # The unit is the sentence; the anchors it introduces are listed as the
    # line key. Dedup by anchor name is preserved (first mention wins, the
    # baseline the scene is built from): a sentence that introduces no new
    # anchor is skipped, so the map grows only where the geography is new.
    seen, dispo_lines = set(), []
    for p in panels:
        text = (p.get("visual_disposition") or "").strip()
        if not text:
            continue
        for sentence in _split_sentences(text):
            names = re.findall(r"\[([^\[\]]+)\]", sentence)
            fresh = [n for n in names if n not in seen]
            if not fresh:
                continue
            seen.update(names)
            key = ", ".join(f"[{n}]" for n in fresh)
            dispo_lines.append(f"{key} — {_clip(sentence, _SPATIAL_DISPO_CAP)}")
    lines.extend(dispo_lines)
    return "\n".join(lines)


def _split_sentences(text: str) -> list:
    """Split prose into sentences. Only a period/question/exclamation
    followed by whitespace ends a sentence, so decimals ('0.8m') and
    hyphenated names ('Private-Hu') stay intact."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _clip(text: str, cap: int) -> str:
    """Truncate at a word boundary, marking the cut with an ellipsis."""
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return text[:cap].rsplit(" ", 1)[0].rstrip() + "…"


def _fov_for(lens_mm: int) -> int:
    """Nearest ladder entry (ties round to the longer focal = wider claim)."""
    return min(_FOV_LADDER, key=lambda p: (abs(p[0] - lens_mm), -p[0]))[1]


def _parse_header(visual_start: str):
    if not visual_start:
        return None
    return _HEADER_RE.match(visual_start.strip().splitlines()[0])


def _speaker_of(dialogue_line: str) -> str:
    """'Reporter (female): text' -> 'Reporter' (annotation stripped)."""
    head = dialogue_line.split(':', 1)[0]
    return re.sub(r"\([^)]*\)", "", head).strip()


def _split_dialogue(dialogue: str) -> list:
    """Return [(speaker_raw, line_text)] one per non-empty line."""
    out = []
    for raw in (dialogue or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if ':' in raw:
            head, text = raw.split(':', 1)
            out.append((head.strip(), text.strip().strip('"')))
        else:
            out.append(("", raw))
    return out


def _voice_tag_for(speaker: str, voices: list) -> str:
    for v in voices:
        if v.kind != "dialogue":
            continue
        a, b = _norm_name(speaker), _norm_name(v.speaker)
        if a == b or a in b or b in a:
            return v.tag
    return ""


def _active_references(refs: list) -> str:
    lines = []
    for b in refs:
        if b.role == "first_frame":
            lines.append(
                f"{b.tag}: reference of the shot to open on — approximate its "
                "framing, composition and content; it guides the opening like "
                "the other references (it is not a pinned frame).")
        elif b.role == "location":
            lines.append(
                f"{b.tag} ({b.name}): {b.descriptor} — 100% matches the reference. "
                "This controls geometry, materials, light and atmosphere ONLY, "
                "not framing.")
        else:
            lines.append(
                f"{b.tag} ({b.name}, character): {b.descriptor} — 100% matches "
                "the reference; identity must hold frame to frame.")
    return "\n".join(lines)


def _map_bodies(spatial_map: str) -> set:
    """The disposition sentences a spatial map already states (the part after
    the anchor key of each disposition line)."""
    out = set()
    for line in (spatial_map or "").splitlines():
        if line.startswith("[") and " — " in line:
            out.add(line.split(" — ", 1)[1])
    return out


def _drop_covered(disposition: str, spatial_map: str) -> str:
    """Drop the sentences the spatial map already states verbatim.

    The map is the scene-level baseline, built from the FIRST mention of
    each anchor — so for the panel that provides that first mention, the
    map already carries that panel's exact sentence. Pasting it again as the
    panel's 'Disposition:' line is pure duplication inside one prompt.
    """
    disposition = (disposition or "").strip()
    if not disposition or not spatial_map:
        return disposition
    covered = _map_bodies(spatial_map)
    if not covered:
        return disposition
    kept = [s for s in _split_sentences(disposition) if s not in covered]
    return " ".join(kept)


def _spatial_blocking(prompt_data) -> str:
    lines = []
    # Item 8a: the scene's spatial map is pasted verbatim as the first
    # line, before the panel's own blocking — shared geography first.
    spatial_map = prompt_data.get("spatial_map") or ""
    if spatial_map:
        lines.append(spatial_map)
    if prompt_data["header"]:
        lines.append(prompt_data["vs_clean"])
    else:
        lines.append(prompt_data["visual_start"])
    disposition = _drop_covered(
        prompt_data["panel"].get("visual_disposition"), spatial_map)
    if disposition:
        lines.append(f"Disposition: {disposition}")
    anchors = prompt_data.get("anchor_refs") or []
    if anchors:
        lines.append("Locked in place for the entire shot, do not shift: "
                     + ", ".join(anchors) + ".")
    return "\n".join(lines)


def _optics(prompt_data) -> str:
    if not prompt_data["header"]:
        return ("no lens data in visual_start — camera behavior follows the "
                "shot description alone")
    m = prompt_data["header"]
    lens = int(m.group("lens"))
    fov = _fov_for(lens)
    scale_word = _SCALE_WORDS.get(m.group("scale").upper(), m.group("scale"))
    return (
        f"lens {lens}mm — diagonal FOV ≈ {fov}° ({_FOV_OUTCOME[fov]}); "
        f"{scale_word}; camera {m.group('angle').lower()} at @{m.group('anchor')}. "
        "One lens for the entire shot."
    )


def _audio_block(panel: dict, voices: list) -> tuple:
    """(audio_text, speaker_names_in_order_or_None)"""
    sound = (panel.get("sound_design") or "").strip().rstrip('.')
    sound_line = (f"Background sounds: {sound}. SFX only. No music."
                  if sound else "Background sounds: ambient SFX only. No music.")
    lines = [sound_line]
    # Voice casting first (Item 5b OpenRouter route: prose descriptors, no
    # native <AUDIO_N> slots) — speaker lines below stay untouched.
    for v in voices:
        if v.kind == "dialogue" and v.descriptor:
            lines.append(f"Voice: {v.speaker}: {v.descriptor}")
    speakers = []
    for head, text in _split_dialogue(panel.get("dialogue", "")):
        tag = _voice_tag_for(head, voices)
        prefix = f"{tag} " if tag else ""
        lines.append(f"{prefix}{head}: {text}" if head else text)
        speakers.append(_speaker_of(head))
    vo = (panel.get("voiceover") or "").strip()
    vo_tags = [v for v in voices if v.kind == "voiceover"]
    if vo:
        vo_tag = vo_tags[0].tag if vo_tags else ""
        if vo_tags and vo_tags[0].speaker:
            lines.append(
                f"{vo_tag} OFF-SCREEN VOICE OVER ({vo_tags[0].speaker} speaks it, "
                "lips do not move): " + f"\"{vo}\"")
        else:
            lines.append(f"{vo_tag} OFF-SCREEN VOICE OVER (lips do not move): \"{vo}\"")
    rules = ("At least 1 second of silence after each spoken line; "
             "no ad-libs in any language.")
    return "\n".join(lines) + "\n" + rules, speakers


def _hard_prohibitions(prompts: dict = None) -> str:
    """User evidence (2026-11-11): positive locks alone don't stop Grok's
    exaggeration drift (tears, vapor, theatrical facial extremes). The
    prohibition text is restored verbatim — one source of truth with
    lib.animation.base.ANIMATION_PROHIBITIONS (Veo/quickplay keep using
    that constant directly) unless the style ships animation_prohibitions.md."""
    from lib.animation.base import ANIMATION_PROHIBITIONS
    return (prompts or {}).get('animation_prohibitions') or ANIMATION_PROHIBITIONS


def _action_timing(panel: dict, duration: int) -> str:
    """ACTION TIMING — the beat sheet, as a shot list when the panel has
    several shots.

    Single-shot panels keep the existing wording (motion_prompt + "complete
    the full action within the N-second clip").

    Multi-shot panels get an explicit numbered shot list with time windows,
    which is the format today's models are documented to follow for
    multi-shot generation (Seedance 2.0: "Shot 1... Shot 2... Shot 3...").
    The motion_prompt is still appended - it carries the per-actor body
    mechanics that the shot list does not.
    """
    motion = (panel.get('motion_prompt') or '').strip()
    shot_list = _shot_list(panel, duration)
    if shot_list:
        return (
            f"{shot_list}\n"
            f"{motion}\n"
            f"Complete every shot in order within the {duration}-second clip."
        ).strip()
    return (f"{motion} "
            f"Complete the full action within the {duration}-second clip.")


def _positive_locks(panel: dict, refs: list, voices: list, speakers: list) -> str:
    multi = len(panel.get("shots") or []) > 1
    locks = [POSITIVE_PHOTO_LOCKS_MULTISHOT if multi else POSITIVE_PHOTO_LOCKS]
    n_speakers = len(dict.fromkeys(speakers)) if speakers else 0
    if n_speakers:
        names = ", ".join(dict.fromkeys(speakers))
        locks.append(
            f"Speaker-count lock: Exactly {n_speakers} person"
            f"{'s' if n_speakers > 1 else ''} "
            f"{'speak' if n_speakers > 1 else 'speaks'} in this clip "
            f"({names}). "
            "Every other visible person stays silent; their lips do not move."
            + (" This holds in EVERY shot of the clip."
               if len(panel.get("shots") or []) > 1 else ""))
    for b in refs:
        if b.role == "location":
            locks.append(
                f"{b.name} ({b.tag}) is a geometry, material, light and atmosphere "
                "reference only — not framing; framing follows the shot "
                "description.")
    return "\n".join(locks)


# ---------------------------------------------------------------------------
# Blocks derived from Higgsfield's published clip prompt (2026-11-11).
#
# Their prompt is 15 blocks / 10 897 chars for one ~10 s clip and restates
# the same fact SEMANTICALLY across 3-5 blocks with different wording (0
# verbatim duplicates) — semantic reinforcement, which is how a video
# model attends to a fact. Our bug was the opposite (the SAME sentence
# copied N times).
#
# These five are the blocks we were missing. All are $0 (pure prompt text).
# ---------------------------------------------------------------------------

def _format_mode(panel: dict, duration: int) -> str:
    """FORMAT MODE — what kind of clip this is, structurally.

    Higgsfield: "~10s, INT office, STATIC TIGHT, square-on to the CRT glass
    (glass fills frame). 0-0.5s locator of the full screen; then 0.5-10s ONE
    static held FIXED CCTV frame (no zoom) while the action plays ON THE
    SCREEN."

    The key idea: state the clip's TEMPORAL SHAPE, not just its duration. A
    model that knows the shot is "one held frame" does not invent a push-in.

    MULTISHOT: when the panel declares more than one shot
    (`panel["shots"]`, each with its own scale/description), the clip holds
    SEVERAL shots in one generation. Today's models can do that - Seedance
    2.0's documented multi-shot mode takes "Shot 1... Shot 2... Shot 3..."
    in one prompt - and it is the cheapest way to cover a scene: one clip,
    one generation, N beats. Then the clip is NOT one continuous take, so
    the wording changes.
    """
    vs = (panel.get("visual_start") or "").strip()
    scale = ""
    m = re.search(r"\b(ECU|CU|MS|WS|FS)\b", vs)
    if m:
        scale = m.group(1)
    shots = panel.get("shots") or []
    bits = [f"{duration}s clip"]
    if scale:
        bits.append(f"opening shot scale {scale}")
    if len(shots) > 1:
        bits.append(f"{len(shots)} shots inside this one clip")
        return (
            f"{', '.join(bits)}. This is a MULTI-SHOT clip: the action is "
            "divided into the shots listed in ACTION TIMING, in order, with a "
            "clean cut between them. Keep each shot's framing EXACTLY as "
            "described for that shot. The character identity, wardrobe, "
            "location and lighting stay identical across every shot in the "
            "clip."
        )
    bits.append("one continuous take, no cuts, no dissolves, no time jumps")
    return f"{', '.join(bits)}. The action plays fully inside this single clip."


def _shot_list(panel: dict, duration: int) -> str:
    """ACTION TIMING for a MULTI-SHOT panel: an explicit shot list.

    The format is Seedance 2.0's documented multi-shot prompt style
    ("Shot 1... Shot 2..."), which is also how a film editor would write
    it. Each shot carries its own scale, its own beat, and its own time
    window, so the model knows where the cut falls.

    Returns "" when the panel is a single shot - the normal ACTION TIMING
    block handles that case.
    """
    shots = panel.get("shots") or []
    if len(shots) <= 1:
        return ""
    lines = []
    t = 0.0
    for i, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            continue
        dur = shot.get("duration") or shot.get("seconds") or 0
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = 0.0
        end = t + dur
        desc = (shot.get("description") or shot.get("action")
                or shot.get("motion") or "").strip()
        scale = (shot.get("scale") or "").strip()
        camera = (shot.get("camera") or "").strip()
        head = f"SHOT {i}"
        if scale:
            head += f" ({scale})"
        if dur:
            head += f" [{t:g}s-{end:g}s]"
        body = " — ".join(p for p in (desc, camera) if p)
        lines.append(f"{head}: {body}")
        t = end
    if not lines:
        return ""
    tail = ""
    if t and abs(t - duration) > 0.5:
        tail = (f" (the shot list totals {t:g}s; the clip is {duration}s — "
                f"compress the final beat to fit)")
    return "\n".join(lines) + tail


def _motion_cadence(duration: int, multi_shot: bool = False) -> str:
    """MOTION CADENCE — the anti-stutter / anti-jitter rule.

    Higgsfield: "A static held tight frame on the glass; the motion is all
    inside the screen, in SMOOTH REAL-TIME motion — NO frame-stutter, NO
    dropped frames, NO jitter/twitching."

    A negative rule aimed at a known video-model failure mode. The video
    prompt is the ONLY place it can be enforced — the QA judge never sees
    the clip's motion.
    """
    tail = ("Each shot is smooth real-time motion and the cuts between "
            "shots are clean and motivated."
            if multi_shot else "One continuous take.")
    return (
        f"Motion runs in smooth real time across the full {duration}s: "
        "NO frame-stutter, NO dropped frames, NO jitter, NO twitching, "
        "NO frame-blending. Movement is fluid and continuous, never sharp "
        f"or jerky. {tail}"
    )


def _physics_rules(panel: dict) -> str:
    """PHYSICS RULES — grounded weight and object interaction.

    Higgsfield: "Real weight: Cal's and Oli's loose drunken sway and
    over-balance as they gesture and point; the Morris rocks on its springs
    as Horace climbs out; his tense, fast, grounded walk through the gate."

    The idea: name the SPECIFIC physical interactions in this shot and say
    they have weight. Without it, characters slide and props float.
    """
    actors = panel.get("state", {}).get("actors", []) or []
    named = [a.get("name") for a in actors if a.get("in_frame") and a.get("name")]
    if named:
        who = ", ".join(named)
        return (
            f"Real weight and grounded physics throughout: {who} move with "
            "real inertia — weight shifts, footfall, over-balance and "
            "recoil are visible. Any prop that is touched, picked up, "
            "moved or leaned on responds with real mass: it shifts, "
            "settles, creaks or swings. Nothing floats, nothing slides "
            "weightlessly, no clipping through surfaces."
        )
    return (
        "Real weight and grounded physics throughout: anything that moves "
        "does so with real inertia and mass. Nothing floats, nothing "
        "slides weightlessly, no clipping through surfaces."
    )


def _location_map(panel: dict, spatial_map: str) -> str:
    """LOCATION MAP — the MOVEMENT PATH through the shot.

    Higgsfield: "On the screen (STATIC FIXED CCTV of the yard by the
    collapsed gate): the pale yellow RHD Morris stopped up by the gate at
    UPPER-LEFT with HORACE inside; CAL and OLI stand in the collapsed-gate
    gap (CAL LEFT, OLI RIGHT)... Movement path: HORACE gets out of the car
    and walks IN through the gate into the yard (toward the workshop); the
    lads follow him."

    The difference from SPATIAL BLOCKING: SPATIAL BLOCKING says WHERE things
    are; LOCATION MAP says the PATH — where a subject moves TO during the
    clip. We had no movement path anywhere.

    The path comes from motion_action: ACTION TIMING already carries
    motion_prompt, SPATIAL BLOCKING the geography.
    """
    path = _drop_covered((panel.get("motion_action") or "").strip(), spatial_map)
    motion = panel.get("motion_prompt") or ""
    path = " ".join(s for s in _split_sentences(path) if s not in motion)
    return f"Movement path: {path}" if path else ""


def _style_prefix(prompts: dict) -> str:
    """STYLE PREFIX — look, lighting and quality, stated once, up front.

    Higgsfield: "STYLE — Grounded photoreal British social-realist
    crime-comedy texture... LIGHTING — Cold and submerged... QUALITY —
    ARRI Alexa capture of the room; the ON-SCREEN footage is BADLY DEGRADED
    period lo-fi VHS CCTV..."

    Their style block is a PREFIX (before the shot description), which
    primes the model to render everything through that lens.

    The storyboard-only fields are EXCLUDED. The style file's
    "FORMAT: Single 2K portrait grid (9 panel-pairs)" describes the IMAGE
    stage - pasting it into a video prompt would tell the video model to
    render a nine-panel grid. "RESOLUTION" is meaningless to a video model
    (it has its own resolution parameter).
    """
    style = (prompts or {}).get("style", "") or ""
    if not style.strip():
        return ""
    skip = ("FORMAT", "RESOLUTION", "ASPECT_RATIO")
    lines = []
    for l in style.splitlines():
        s = l.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        head = s.split(":", 1)[0].strip().upper()
        if head in skip:
            continue
        lines.append(s)
    # Cap the length: Higgsfield's whole STYLE PREFIX is ~800 chars.
    out = " ".join(lines)
    if len(out) > 1400:
        out = out[:1400].rsplit(" ", 1)[0] + "."
    return out


def build_video_prompt(panel: dict, refs: list, voices: list,
                       duration: int, anchor_refs=None,
                       acting: list = None, spatial_map: str = None,
                       prompts: dict = None) -> str:
    """Build the structured Grok video prompt (plan Item 3, fixed block order).

    refs: RefBite list from lib.animation.refs.assemble_refs (tag order is
    consumed verbatim — the ACTIVE REFERENCES block binds <IMAGE_N> to the Nth
    entry). voices: VoiceBite list (Item 5b). duration: clip seconds.
    acting: ActingBite list (Item 7b); omitted from the block when no
    character bites exist. spatial_map: Item 8a per-scene geography block;
    pasted verbatim as SPATIAL BLOCKING's first line when non-empty.

    anchor_refs: optional override; when None the panel's own anchor_refs is
    used (kept for the Item 8a spatial-map wiring).
    prompts: optional prompt bundle; used for the STYLE PREFIX block.
    """
    panel = panel or {}
    vs = (panel.get("visual_start") or "").strip()
    header = _parse_header(vs)
    vs_clean = "\n".join(
        l for l in vs.splitlines() if not _LIGHTING_LINE_RE.match(l))
    if anchor_refs is None:
        anchor_refs = panel.get("anchor_refs")
    pd = {"panel": panel, "visual_start": vs, "header": header, "vs_clean": vs_clean,
          "anchor_refs": anchor_refs, "spatial_map": spatial_map}
    audio_text, speakers = _audio_block(panel, voices or [])

    dialogue_present = bool((panel.get("dialogue") or "").strip())
    lock_text = _positive_locks(panel, refs, voices or [],
                                speakers if dialogue_present else [])
    lighting_lines = re.findall(r"^(?:LIGHT|BGD):[^\n]*", vs, re.MULTILINE)
    lighting_text = "\n".join(lighting_lines) if lighting_lines \
        else "lighting follows the reference frame"

    era = os.getenv('AI_ERA_LOCK', '').strip()  # Item 10b: era-drift guard
    style_prefix = _style_prefix(prompts)
    location_map = _location_map(panel, spatial_map)
    blocks = []
    if style_prefix:
        # Higgsfield puts STYLE first, as a PREFIX: it primes the model to
        # render everything through that lens.
        blocks.append(("STYLE PREFIX", style_prefix))
    blocks += [
        ("SCENE CONTEXT",
         f"This shot: {(panel.get('motion_intent') or '').strip()} "
         f"({(panel.get('emotional_beat') or '').strip()})".rstrip()
         + (f" {era}" if era else "")),
        ("ACTIVE REFERENCES", _active_references(refs or [])),
    ]
    if location_map:
        # The MOVEMENT PATH, which SPATIAL BLOCKING does not carry.
        blocks.append(("LOCATION MAP", location_map))
    blocks.append(("SPATIAL BLOCKING", _spatial_blocking(pd)))
    if any(b.role == "character" for b in (refs or [])) and (
            acting or ((panel.get("state") or {}).get("actors") or [])):
        # Item 7b: present whenever in-frame characters exist; EYE LIFE is
        # part of the block and survives missing acting data. Character-less
        # panels (empty locations) skip the block entirely.
        blocks.append(("ACTING", _acting_block(acting or [])))
    blocks += [
        ("OPTICS", _optics(pd)),
        ("CAMERA", (panel.get("lights_and_camera") or "").strip()
                   or "follow the framing in the shot description"),
        ("FORMAT MODE", _format_mode(panel, duration)),
        ("ACTION TIMING", _action_timing(panel, duration)),
        ("PHYSICS RULES", _physics_rules(panel)),
        ("MOTION CADENCE",
         _motion_cadence(duration, multi_shot=len(panel.get("shots") or []) > 1)),
        ("LIGHTING", lighting_text),
        ("AUDIO", audio_text),
        ("POSITIVE LOCKS", lock_text),
        ("HARD PROHIBITIONS", _hard_prohibitions(prompts).rstrip()),
    ]
    prompt = "\n\n".join(f"{name}: {body}" for name, body in blocks)
    logger.debug("built video prompt (%d chars) for panel %s",
                 len(prompt), panel.get('panel_index'))
    return prompt
