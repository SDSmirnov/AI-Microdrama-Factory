"""The still-QA gate and the scale-refinement path.

TWO GAPS, both found in the 2026-11-11 production probes:

GAP 1 (the still-QA gap). 36-panel storyboard QA: scale 22/27 fail,
gaze 19/42 fail, pose 27/42 fail - and the panels PASSED. The rule was
    needs_refinement = fidelity < threshold OR character_consistency < ...
                         OR dramatic_intensity < ... OR critical artifacts
A perspective/scale/duplicate-character defect leaves the NUMBERS high
(the face is perfect, the lighting is perfect), so the artifact was
recorded but never GATED.

GAP 2 (scale is unfixable by an I2I edit). Told "Reframe to a low-angle
Medium Shot (MS) from the waist up", every image model kept the source
full-body crop and the scale error survived every attempt. An I2I edit
inherits the source crop. Worse, the refine prompt appended "Preserve
composition, framing, camera angle... exactly" UNCONDITIONALLY, which
directly contradicts a reframe request, and the T2I re-render path
DISCARDED the QA's correction entirely - so a re-render rendered the same
wrong spec with no mention of what to change.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.editor import _is_scale_defect, _wants_reframe
from lib.studio.qa_gate import (apply_critical_artifact_gate,
                                 critical_artifacts, is_critical_artifact)


class CriticalArtifactDetectionTests(unittest.TestCase):
    def test_scale_defect_is_critical(self):
        for text in (
            "wrong shot scale: rendered as a full-body Wide Shot (WS) "
            "instead of the requested Medium Shot (MS)",
            "[CRITICAL] perspective error: the crab appears at giant scale",
            "relative size error: Lin is 3x too large",
        ):
            self.assertTrue(is_critical_artifact(text), text)

    def test_missing_character_is_critical(self):
        self.assertTrue(is_critical_artifact(
            "missing character: Private-Hu is completely absent from the "
            "right foreground."))
        self.assertTrue(is_critical_artifact(
            "[CRITICAL] wrong number of people: two people are present, "
            "one was requested"))

    def test_duplicate_prop_is_critical(self):
        self.assertTrue(is_critical_artifact(
            "duplicate rifle: the character is aiming one rifle while "
            "holding a second"))
        self.assertTrue(is_critical_artifact("extra arm on the left side"))

    def test_pass_notes_are_not_critical(self):
        for text in ("perspective matches the reference",
                     "shot scale is correct (MS)",
                     "no missing object detected",
                     "not a duplicate character - twins by script"):
            self.assertFalse(is_critical_artifact(text), text)
        self.assertTrue(is_critical_artifact("piano missing prop: lid"))

    def test_minor_artifact_is_not_critical(self):
        for text in (
            "radio LED still green instead of off",
            "hissed fist is raised rather than lowered",
            "",
            None,
        ):
            self.assertFalse(is_critical_artifact(text), repr(text))

    def test_critical_artifacts_filter(self):
        arts = ["radio LED green", "missing character: Hu is absent",
                "extra arm", "slight halo on the shoulder"]
        self.assertEqual(len(critical_artifacts(arts)), 2)


class ArtifactGateTests(unittest.TestCase):
    def test_passing_panel_with_scale_defect_is_failed(self):
        r = {"fidelity": 8, "character_consistency": 8, "composition_match": 7,
             "dramatic_intensity": 7, "artifacts": [
                 "wrong shot scale: WS instead of MS"],
             "needs_refinement": False, "refinement_prompt": ""}
        out = apply_critical_artifact_gate(r)
        self.assertTrue(out["needs_refinement"])
        self.assertIn("wrong shot scale", out["refinement_prompt"])
        self.assertEqual(len(out["critical_artifacts"]), 1)

    def test_failing_panel_is_untouched_except_tagging(self):
        r = {"fidelity": 4, "artifacts": ["missing character: Hu absent"],
             "needs_refinement": True, "refinement_prompt": "add Hu"}
        out = apply_critical_artifact_gate(r)
        self.assertTrue(out["needs_refinement"])
        self.assertEqual(out["refinement_prompt"], "add Hu")
        self.assertEqual(len(out["critical_artifacts"]), 1)

    def test_clean_panel_passes(self):
        r = {"fidelity": 9, "artifacts": ["radio LED green"],
             "needs_refinement": False, "refinement_prompt": ""}
        out = apply_critical_artifact_gate(r)
        self.assertFalse(out["needs_refinement"])
        self.assertNotIn("critical_artifacts", out)

    def test_shot_impossible_is_not_gated(self):
        # A description-level impossibility must not be forced to a fail:
        # the judge already set needs_refinement=False for it.
        r = {"fidelity": 6, "artifacts": ["scale conflict: CU + full body"],
             "needs_refinement": False, "shot_impossible": True,
             "refinement_prompt": ""}
        out = apply_critical_artifact_gate(r)
        self.assertFalse(out["needs_refinement"])

    def test_non_dict_is_safe(self):
        self.assertEqual(apply_critical_artifact_gate(None), None)
        self.assertEqual(apply_critical_artifact_gate([]), [])


class ReframeDetectionTests(unittest.TestCase):
    def test_reframe_request_is_detected(self):
        for text in (
            "Reframe to a low-angle Medium Shot (MS) from the waist up.",
            "Change the framing to a close-up of the face.",
            "Pull back to show the whole room.",
            "The shot scale is wrong - it should be a Wide Shot.",
        ):
            self.assertTrue(_wants_reframe(text), text)

    def test_ordinary_refinement_is_not_a_reframe(self):
        for text in (
            "Eckels' face does not match reference - wrong jaw shape.",
            "Add character A's hand resting on B's shoulder.",
            "",
        ):
            self.assertFalse(_wants_reframe(text), text)

    def test_scale_defect_is_a_scale_defect(self):
        self.assertTrue(_is_scale_defect(
            "wrong shot scale: rendered as a full-body Wide Shot (WS)"))
        self.assertTrue(_is_scale_defect(
            "Reframe to a Medium Shot (MS) from the waist up."))

    def test_face_defect_is_not_a_scale_defect(self):
        self.assertFalse(_is_scale_defect(
            "Eckels' face does not match reference - wrong jaw shape."))


if __name__ == "__main__":
    unittest.main()
