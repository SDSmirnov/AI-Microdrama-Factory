"""QA judge hardening: a malformed judge response must not crash the loop.

Found while measuring judge agreement (2026-11-12): gemini-3.6-flash returned
a JSON ARRAY instead of the object PANEL_QA_SCHEMA asks for, and
analyze_panel crashed on `result["scene_id"] = scene_id`
(TypeError: list indices must be integers or slices, not str) — taking the
whole panel loop down instead of failing that one panel.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from lib.studio import critic


class _StubLLM:
    """Returns whatever payload the test wants."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def analyze_image(self, image=None, prompt=None, schema=None):
        self.calls += 1
        return self.payload


def _img():
    return Image.new("RGB", (64, 64), (10, 10, 10))


PANEL = {"panel_index": 1, "references": [], "location_references": [],
         "visual_start": "[SCALE] MS 35mm eye-level cam@[wall]",
         "state": {"actors": []}}
SCENE = {"scene_id": 1, "location": "Room", "panels": [PANEL]}


class MalformedJudgeResponseTests(unittest.TestCase):
    def _run(self, payload):
        llm = _StubLLM(payload)
        return critic.analyze_panel(
            llm=llm, panel_img=_img(), panel_meta=PANEL, scene_meta=SCENE,
            ref_catalog={}, scene_id=1, panel_id=1, threshold=5)

    def test_list_response_is_unwrapped(self):
        r = self._run([{"fidelity": 7, "needs_refinement": False}])
        self.assertEqual(r["fidelity"], 7)
        self.assertFalse(r["needs_refinement"])
        self.assertEqual(r["scene_id"], 1)

    def test_empty_list_becomes_a_safe_failure(self):
        r = self._run([])
        self.assertEqual(r["fidelity"], 0)
        self.assertTrue(r["needs_refinement"])
        self.assertTrue(any("API_ERROR" in a for a in r["artifacts"]))

    def test_string_response_becomes_a_safe_failure(self):
        r = self._run("I could not do that")
        self.assertEqual(r["fidelity"], 0)
        self.assertTrue(r["needs_refinement"])

    def test_none_response_becomes_a_safe_failure(self):
        r = self._run(None)
        self.assertEqual(r["fidelity"], 0)
        self.assertTrue(r["needs_refinement"])

    def test_list_of_non_dicts_becomes_a_safe_failure(self):
        r = self._run(["nope", 42])
        self.assertEqual(r["fidelity"], 0)
        self.assertTrue(r["needs_refinement"])

    def test_normal_dict_response_is_untouched(self):
        r = self._run({"fidelity": 8, "character_consistency": 7,
                        "composition_match": 6, "dramatic_intensity": 5,
                        "artifacts": [], "needs_refinement": False,
                        "refinement_prompt": "", "suggest_mirror": False,
                        "mirror_reason": "", "shot_impossible": False,
                        "shot_impossible_reason": "", "reasoning": "fine"})
        self.assertEqual(r["fidelity"], 8)
        self.assertEqual(r["scene_id"], 1)
        self.assertEqual(r["panel_id"], 1)


if __name__ == "__main__":
    unittest.main()
