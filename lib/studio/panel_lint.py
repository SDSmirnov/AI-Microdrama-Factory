"""Deterministic checks of Pass 2 / Pass 3 output against rules the prompts mark as HARD FAILURE."""
import re

from lib.studio.ledger import Issue

VOICE_CHARS_PER_SEC = 24  # screenplay.md VOICE BUDGET

# a single tear is allowed (motion_dynamics.md)
_FLUIDS = re.compile(
    r"\b(?:tears\s+(?:well|stream|roll|run|fill|glint|brim|spill)\w*|tear[- ](?:tracks?|streaked)|teary"
    r"|eyes\s+(?:brim|glisten|well|moisten)\w*|sweat(?:s|ing|y|ed|-soaked|-slick)?|saliva|drool\w*|spittle"
    r"|visible\s+(?:breath|exhale)|breath\s+(?:cloud|vapou?r|dissipates)|(?:wisp|fog)\s+of\s+breath"
    r"|(?:vapou?r|steam|condensation)\s+from\s+(?:his|her|their|the)?\s*(?:nose|mouth|lips))\b", re.I)
_TO_CAMERA = re.compile(r"\b(?:toward|towards|away\s+from)\s+(?:the\s+)?(?:camera|lens|viewer)\b", re.I)
_SPEAKER = re.compile(r"^[^:\n]{1,40}:\s*", re.M)


def _found(pattern: re.Pattern, text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in pattern.finditer(text or '')})


def visual_issues(p2: dict | None, p1a: dict | None, scene_id) -> list[Issue]:
    """Pass 2: forbidden fluids in visual_start/visual_end; an ACTOR line for someone Pass 1A put out of frame."""
    out_of_frame = {p.get('panel_index'): {a['name'] for a in (p.get('state') or {}).get('actors', [])
                                           if a.get('name') and a.get('in_frame') is False}
                    for p in (p1a or {}).get('panels', [])}
    issues = []
    for p in (p2 or {}).get('panels', []):
        idx = p.get('panel_index')
        for field in ('visual_start', 'visual_end'):
            text = p.get(field) or ''
            if words := _found(_FLUIDS, text):
                issues.append(Issue(scene_id, idx, '', f"{field} shows unrenderable fluids {words}: use body mechanics"))
            for name in sorted(out_of_frame.get(idx, ())):
                if re.search(rf'^{re.escape(name)}\s*:', text, re.M):
                    issues.append(Issue(scene_id, idx, name, f"{field} has an ACTOR line but Pass 1A puts them out of frame"))
    return issues


def motion_issues(p3: dict | None, scene_id) -> list[Issue]:
    """Pass 3: forbidden fluids and camera-relative directions in motion_prompt; voice over the TTS budget."""
    issues = []
    for p in (p3 or {}).get('panels', []):
        idx, motion = p.get('panel_index'), p.get('motion_prompt') or ''
        if words := _found(_FLUIDS, motion):
            issues.append(Issue(scene_id, idx, '', f"motion_prompt animates unrenderable fluids {words}"))
        if words := _found(_TO_CAMERA, motion):
            issues.append(Issue(scene_id, idx, '', f"motion_prompt uses camera-relative direction {words}: name a world target"))
        duration = p.get('duration')
        if isinstance(duration, (int, float)) and duration > 0:
            chars = len(_SPEAKER.sub('', p.get('dialogue') or '').strip()) + len((p.get('voiceover') or '').strip())
            if chars > VOICE_CHARS_PER_SEC * duration:
                issues.append(Issue(scene_id, idx, '', f"dialogue + voiceover is {chars} chars, over the "
                                                       f"{VOICE_CHARS_PER_SEC * duration:g}-char budget of a {duration:g}s panel"))
    return issues


def issues_block(issues: list[Issue]) -> str:
    return ('RULE VIOLATIONS found by the checker in your previous answer — fix every one and change nothing else:\n'
            + '\n'.join(f'- {i}' for i in issues))
