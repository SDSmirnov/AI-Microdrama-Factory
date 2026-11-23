"""QA prompt trims — and the one that was MEASURED not to work.

MEASURED 2026-11-12 (scene 1 panel 6, gemini-3.8-flash, one judge call each):

  prev_panels = all 5 previous     prompt 15 121   cost $0.01673
  prev_panels = last 2 previous    prompt 13 452   cost $0.00675
  -> 1 669 prompt tokens saved (11 %)

  refs at full size (896x1200)     prompt 13 452
  refs downscaled to 512 max side  prompt 13 452   <-- ZERO saving
  -> Gemini already resizes an image into a single 768x768 tile before
     billing it, so a local downscale buys NOTHING and only loses
     detail. The earlier note ("images are 10 836 tokens, downscale to
     save 71 %") was WRONG.

These tests lock in the trim that works and document the one that does not,
so nobody re-adds a downscale.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from lib.studio import critic
from lib.studio.critic import PREV_PANELS_FOR_QA


class PrevPanelsTrimTests(unittest.TestCase):
    def test_default_is_two(self):
        self.assertEqual(PREV_PANELS_FOR_QA, 2)

    def test_no_downscale_helper_exists(self):
        """The downscale was measured to save zero tokens - it must not
        come back."""
        self.assertFalse(hasattr(critic, "_downscale_ref"))
        self.assertFalse(hasattr(critic, "REF_IMAGE_MAX_SIDE"))


class TrimBehaviourTests(unittest.TestCase):
    """Exercise the trim through analyze_panel with a stub LLM."""

    def _scene(self, n_panels=6):
        panels = []
        for i in range(1, n_panels + 1):
            panels.append({
                "panel_index": i,
                "visual_start": "[SCALE] MS 35mm eye-level cam@[wall]",
                "visual_end": f"end of panel {i}",
                "lights_and_camera": "locked",
                "references": [],
                "location_references": [],
            })
        return {"scene_id": 1, "location": "Room", "panels": panels}

    def test_prompt_keeps_only_the_last_two_prev_panels(self):
        captured = {}

        class _LLM:
            def analyze_image(self, image=None, prompt=None, schema=None):
                captured["prompt"] = prompt
                return {"fidelity": 5, "character_consistency": 5,
                        "composition_match": 5, "dramatic_intensity": 5,
                        "artifacts": [], "needs_refinement": False,
                        "refinement_prompt": "", "reasoning": "",
                        "suggest_mirror": False, "mirror_reason": "",
                        "shot_impossible": False,
                        "shot_impossible_reason": ""}

        scene = self._scene(6)
        panel = scene["panels"][-1]
        critic.analyze_panel(llm=_LLM(), panel_img=Image.new("RGB", (32, 32)),
                             panel_meta=panel, scene_meta=scene,
                             ref_catalog={}, scene_id=1, panel_id=6,
                             threshold=5)
        prompt = captured["prompt"]
        # panels 1-4 are dropped, 4 and 5 survive (the last 2 before 6)
        self.assertNotIn("end of panel 1", prompt)
        self.assertNotIn("end of panel 2", prompt)
        self.assertNotIn("end of panel 3", prompt)
        self.assertIn("end of panel 4", prompt)
        self.assertIn("end of panel 5", prompt)

    def test_first_panel_has_no_prev_panels(self):
        captured = {}

        class _LLM:
            def analyze_image(self, image=None, prompt=None, schema=None):
                captured["prompt"] = prompt
                return {"fidelity": 5, "character_consistency": 5,
                        "composition_match": 5, "dramatic_intensity": 5,
                        "artifacts": [], "needs_refinement": False,
                        "refinement_prompt": "", "reasoning": "",
                        "suggest_mirror": False, "mirror_reason": "",
                        "shot_impossible": False,
                        "shot_impossible_reason": ""}

        scene = self._scene(6)
        panel = scene["panels"][0]
        critic.analyze_panel(llm=_LLM(), panel_img=Image.new("RGB", (32, 32)),
                             panel_meta=panel, scene_meta=scene,
                             ref_catalog={}, scene_id=1, panel_id=1,
                             threshold=5)
        # The PREVIOUS PANELS block is empty (the panel's OWN visual_end
        # still appears in its own description - that is expected).
        self.assertIn("<PREV_PANELS>[]</PREV_PANELS>", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
