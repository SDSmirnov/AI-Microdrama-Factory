"""Hard-artifact gate: geometry defects must FAIL the panel, not just be noted.

THE GAP (measured 2026-11-11, 36-panel storyboard QA):
  scale 22/27 fail, gaze 19/42 fail, pose 27/42 fail
  ... and the panels still PASSED, because the QA rule is
      needs_refinement = fidelity < threshold OR character_consistency < ...
                           OR dramatic_intensity < ... OR critical artifacts
  A perspective/scale/duplicate-character defect leaves the NUMBERS high
  (the face is perfect, the lighting is perfect) so the panel passes with
  broken geometry. The artifact is RECORDED but never GATES.

WHY IT MATTERS MORE NOW: with the video model taking the panel as its
first frame, a panel with a duplicated character or an impossible scale
does not fail loudly - it propagates into the clip, where the video model
faithfully animates the broken geometry.

The fix: tag artifacts with a machine-readable severity, and treat the
critical classes as hard `needs_refinement` triggers regardless of the
numeric scores. This lives in code (not only in the prompt) so it cannot
be forgotten by a weaker judge: the judge is asked to prefix a critical
artifact with "[CRITICAL]", and the gate promotes any such artifact, plus
any artifact whose text matches a known critical class.
"""
import re
from typing import Iterable

# Artifact classes that are ALWAYS a hard failure. Matched case-insensitively
# against the artifact text (the judge writes free-form strings, so this is
# a safety net under the [CRITICAL] prefix, not a replacement for it).
CRITICAL_ARTIFACT_PATTERNS: tuple[str, ...] = (
    # perspective / geometry / scale - the defect classes that passed QA
    "wrong shot scale",
    "instead of the requested",
    "scale error",
    "size/scale",
    "relative size error",
    "perspective error",
    "impossible geometry",
    "broken geometry",
    "geometry error",
    # character presence
    "missing character",
    "character is completely absent",
    "character is absent",
    "completely absent from",
    "duplicated character",
    "duplicate character",
    "extra character",
    "wrong number of people",
    "wrong number of characters",
    # props
    "duplicated prop",
    "duplicate prop",
    "duplicated object",
    "duplicate object",
    "extra limb",
    "duplicate rifle",
    "extra arm",
    "missing prop",
    "missing object",
    "missing character",
)

CRITICAL_MARKER = "[CRITICAL]"

CRITICAL_TAGGING = f"""## CRITICAL TAGGING
Prefix an artifact with "{CRITICAL_MARKER} " when it is one of these HARD-FAIL classes,
because they leave the numeric scores high and would otherwise pass the panel with broken geometry:
  - PERSPECTIVE / SCALE: the shot scale is not what was requested (WS instead of MS, CU instead
    of MS); a character or object is at the wrong relative size or distance; the camera position
    implies an impossible geometry
  - CHARACTER PRESENCE: a character who should be in frame is completely absent; a character
    appears twice; the wrong number of people are present
  - PROP PRESENCE: a required prop is missing; a prop is duplicated; an extra limb, duplicate
    weapon or duplicated object appears
Write the artifact text so the class is obvious, e.g.
  "{CRITICAL_MARKER} wrong shot scale: rendered as a full-body Wide Shot (WS) instead of the requested Medium Shot (MS)"
  "{CRITICAL_MARKER} missing character: Character B is completely absent from the right foreground."
When you tag an artifact {CRITICAL_MARKER}, set needs_refinement=true and write a
refinement_prompt that says exactly what to change.
"""

# A negated class ("no missing object") is a pass note, not a defect.
_CRITICAL_RE = re.compile(
    r"(?<!\bno )(?<!\bnot )(?<!\bnot a )(?:" + "|".join(map(re.escape, CRITICAL_ARTIFACT_PATTERNS)) + ")")


def is_critical_artifact(text: str) -> bool:
    """True if this artifact string is a hard failure."""
    if not text:
        return False
    low = text.lower()
    if CRITICAL_MARKER.lower() in low:
        return True
    return bool(_CRITICAL_RE.search(low))


def critical_artifacts(artifacts: Iterable[str] | None) -> list[str]:
    """Filter a judge's artifact list down to the hard-failure ones."""
    return [a for a in (artifacts or []) if is_critical_artifact(a)]


def apply_critical_artifact_gate(result: dict) -> dict:
    """Promote critical artifacts to a hard needs_refinement=True.

    Mutates and returns `result`. If the panel was already flagged, nothing
    changes. If the panel passed but carries a critical artifact, it is
    failed and a refinement prompt is synthesised from the artifact text
    (the judge's own refinement_prompt is kept when it exists, because it
    is more specific).
    """
    if not isinstance(result, dict):
        return result
    # A description-level impossibility is not a rendering defect; the judge
    # already handles it (shot_impossible -> needs_refinement=False).
    if result.get("shot_impossible"):
        return result

    crit = critical_artifacts(result.get("artifacts"))
    if not crit:
        return result

    if not result.get("needs_refinement"):
        result["needs_refinement"] = True
        result["critical_artifacts"] = crit
        prompt = (result.get("refinement_prompt") or "").strip()
        if not prompt:
            result["refinement_prompt"] = (
                "Fix these defects: " + "; ".join(crit))
        else:
            result["refinement_prompt"] = prompt
        result.setdefault("reasoning", "")
        if result["reasoning"]:
            result["reasoning"] += (
                " | Critical geometry/presence defects forced a fail: "
                + "; ".join(crit))
        else:
            result["reasoning"] = (
                "Critical geometry/presence defects forced a fail: "
                + "; ".join(crit))
    else:
        result["critical_artifacts"] = crit
    return result
