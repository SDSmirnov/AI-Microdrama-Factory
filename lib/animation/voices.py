"""Item 5b (OpenRouter route): per-speaker voice resolution.

OpenRouter refs-only has no <AUDIO_N> passthrough (probes 12-13 in
PROBES.md: the field is absent from the API surface,
allowed_passthrough_parameters=[] on every grok video model), so voices
resolve into PROSE descriptors rendered in the AUDIO block, bound to the
speaker's character <IMAGE_N> tag when one exists.

resolve_voice(panel, bites):
- parses dialogue speakers exactly like the prompt builder does (prefix
  before ':' per line);
- binds the speaker to a character bite via voiceover_settings.actor
  (authoritative when present) or transliterated nickname matching
  ('Линь' -> 'lin' -> Lin-Wei-ming) as fallback;
- caps descriptors at 3 speakers (model voice limit parity); extras are
  logged and left to the post VO pipeline.

VoiceBite.tag stays empty here — native <AUDIO_N> slots belong to the
untaken x.ai-direct route (needs a separate Grok subscription; user
decision 2026-11-10). The existing TTS/dub pipeline remains untouched.
"""
import logging
import re

from lib.animation.prompt_builder import VoiceBite, _split_dialogue
from lib.core.utils import CYR_TO_LAT as _CYR_TO_LAT

logger = logging.getLogger(__name__)

SPEAKER_LIMIT = 3

_GENDER_WORDS = {"male": "male", "мужской": "male", "female": "female",
                 "женский": "female", "муж": "male", "жен": "female"}


def _norm(name: str) -> str:
    """Latin lowercase letters only — the common denominator for matching."""
    return re.sub(r"[^a-z]", "", (name or "").lower().translate(_CYR_TO_LAT))


def _label(head: str) -> str:
    """Dialogue head minus the gender annotation: 'Ху (мужской)' -> 'Ху'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", head).strip()


def _gender_word(head: str, settings: dict) -> str:
    ann = re.search(r"\(([^)]*)\)", head or "")
    raw = (settings or {}).get("gender") or (ann.group(1) if ann else "")
    raw = (raw or "").lower().strip()
    for key, word in _GENDER_WORDS.items():
        if key in raw:
            return word
    return raw or "neutral"


def _match_bite(slug: str, bites: list):
    """First character bite whose name matches the actor slug."""
    target = _norm(slug)
    if not target:
        return None
    for b in bites or []:
        if b.role != "character":
            continue
        name = re.sub(r"[^a-z]", "", (b.name or "").lower())
        if not name:
            continue
        if target in name or name in target or _norm(slug) in name:
            return b
    return None


def _descriptor(head: str, settings: dict, bound, use_profile: bool) -> str:
    parts = []
    gender = _gender_word(head, settings)  # gender from the line annotation is trustworthy
    if gender != "neutral":
        parts.append(f"{gender} voice")
    if use_profile:
        age = (settings or {}).get("age")
        if age:
            parts.append(f"~{age} years old")
        tone = (settings or {}).get("tone")
        if tone:
            parts.append(f"{tone} delivery")
    bind = f", matching the character from {bound.tag} ({bound.name})" if bound is not None else ""
    if not parts:
        return f"natural {gender} delivery{bind}" if bind else ""
    return ", ".join(parts) + bind + "."


def resolve_voice(panel: dict, bites: list) -> list:
    """Per-speaker voice descriptors for the AUDIO block (3 max, logs extras).

    Speaker identity comes from the dialogue nick first (the dialogue prefix
    IS who speaks; CRAB data shows 9/13 panels carry a mismatched
    voiceover_settings.actor). The settings profile (age/tone) is trusted
    only when it names the same character as the nick binding.
    """
    heads = [h for h, _ in _split_dialogue(panel.get("dialogue", "")) if h]
    if not heads:
        return []
    if len(heads) > SPEAKER_LIMIT:
        logger.warning(
            "    %d dialogue speakers exceeds the %d-voice limit; speakers %s "
            "stay silent in-clip (post VO fallback).",
            len(heads), SPEAKER_LIMIT, heads[SPEAKER_LIMIT:])
        heads = heads[:SPEAKER_LIMIT]
    settings = panel.get("voiceover_settings") or {}
    actor_bite = _match_bite(settings.get("actor"), bites)
    voices = []
    for head in heads:
        bound = _match_bite(_label(head), bites)
        if bound is None:
            bound = actor_bite          # fallback: panel's assigned actor
            use_profile = bound is not None
        else:
            # profile applies only when it provably names the SAME speaker;
            # an actor who isn't even on this panel cannot be verified.
            use_profile = actor_bite is bound
        descriptor = _descriptor(head, settings, bound, use_profile)
        if descriptor:
            voices.append(VoiceBite(tag="", speaker=_label(head),
                                    line="", kind="dialogue",
                                    descriptor=descriptor))
    return voices
