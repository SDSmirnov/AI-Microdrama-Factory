"""The five video-prompt blocks added from Higgsfield's published prompt.

Higgsfield's clip prompt is 15 blocks / 10 897 chars for one ~10 s clip,
and it restates the same fact SEMANTICALLY across 3-5 blocks with
DIFFERENT wording (0 verbatim duplicates) - semantic reinforcement, which
is how a video model attends to a fact. Our bug was the opposite: the same
sentence copied N times.

Blocks we were missing, all pure prompt text ($0 to add):
  STYLE PREFIX   look/lighting/quality stated FIRST, as a prefix
  LOCATION MAP   the MOVEMENT PATH (where a subject moves TO) - we had
                 nowhere that said this
  FORMAT MODE    the clip's temporal shape, not just its duration
  PHYSICS RULES  named physical interactions with real weight
  MOTION CADENCE the anti-stutter/anti-jitter rule - enforceable ONLY here,
                 because the QA judge never sees the clip's motion
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import (build_video_prompt, RefBite)


def _bites():
    return [
        RefBite("<IMAGE_0>", None, "first_frame", "panel", "the panel"),
        RefBite("<IMAGE_1>", None, "character", "Lin-Wei-ming", "a man"),
    ]


PANEL = {
    "panel_index": 1,
    "visual_start": "[SCALE] MS 35mm eye-level cam@[west-sandbag-wall]",
    "lights_and_camera": "locked MS, eye-level",
    "motion_intent": "Lin steps forward",
    "emotional_beat": "cold dread",
    "motion_prompt": "Lin walks forward two steps and stops.",
    "motion_action": "Lin crosses to the embrasure.",
    "dialogue": "",
    "voiceover": "",
    "state": {"actors": [{"name": "Lin-Wei-ming", "in_frame": True,
                          "pose": "standing", "position": "centre",
                          "gaze_target": "sea", "chest_direction": "sea",
                          "head_direction": "sea"}]},
}


class NewBlockTests(unittest.TestCase):
    def _prompt(self, **kw):
        panel = dict(PANEL)
        panel.update(kw.pop("panel", {}))
        return build_video_prompt(panel, _bites(), [], kw.pop("duration", 4),
                                  **kw)

    def test_all_five_blocks_are_present(self):
        p = self._prompt()
        for name in ("FORMAT MODE", "PHYSICS RULES", "MOTION CADENCE"):
            self.assertIn(name, p, name)

    def test_style_prefix_comes_first(self):
        p = self._prompt(prompts={"style": "STYLE: photoreal cinematic\n"
                                           "LIGHTING: cold blue night"})
        self.assertTrue(p.startswith("STYLE PREFIX:"), p[:60])
        self.assertIn("cold blue night", p)

    def test_style_prefix_excludes_storyboard_only_fields(self):
        """FORMAT/RESOLUTION describe the IMAGE stage. A video prompt that
        says 'FORMAT: Single 2K portrait grid (9 panel-pairs)' tells the
        video model to render a nine-panel grid."""
        style = ("FORMAT: Single 2K portrait grid (9 panel-pairs)\n"
                 "RESOLUTION: 2K\n"
                 "ASPECT_RATIO: 9:16\n"
                 "STYLE: Photorealistic Cinematic\n"
                 "LIGHTING: cold blue night")
        p = self._prompt(prompts={"style": style})
        self.assertIn("STYLE PREFIX", p)
        self.assertNotIn("portrait grid", p)
        self.assertNotIn("RESOLUTION:", p)
        self.assertIn("Photorealistic Cinematic", p)
        self.assertIn("cold blue night", p)

    def test_no_style_prefix_without_a_style(self):
        p = self._prompt()
        self.assertNotIn("STYLE PREFIX", p)

    def test_location_map_carries_the_movement_path(self):
        p = self._prompt()
        self.assertIn("LOCATION MAP", p)
        self.assertIn("Movement path: Lin crosses to the embrasure.", p)

    def test_motion_prompt_appears_once(self):
        p = self._prompt()
        self.assertEqual(p.count("walks forward two steps"), 1)

    def test_no_location_map_without_motion_action(self):
        p = self._prompt(panel={"motion_action": ""})
        self.assertNotIn("LOCATION MAP", p)

    def test_location_map_drops_sentences_of_motion_prompt(self):
        p = self._prompt(panel={"motion_action": "Lin walks forward two steps and stops."})
        self.assertNotIn("LOCATION MAP", p)

    def test_location_map_does_not_repeat_the_spatial_map(self):
        smap = "Lin stands at [seaward-embrasure-lip] on [plywood-dirt-floor]."
        p = self._prompt(spatial_map=smap)
        # The map belongs to SPATIAL BLOCKING only.
        self.assertEqual(p.count(smap), 1)
        self.assertIn("SPATIAL BLOCKING", p)

    def test_format_mode_states_duration_and_shape(self):
        p = self._prompt(duration=6)
        self.assertIn("FORMAT MODE", p)
        self.assertIn("6s clip", p)
        self.assertIn("no cuts", p)

    def test_physics_rules_name_the_in_frame_actors(self):
        p = self._prompt()
        self.assertIn("PHYSICS RULES", p)
        self.assertIn("Lin-Wei-ming", p)
        self.assertIn("Real weight", p)

    def test_physics_rules_work_without_actors(self):
        p = self._prompt(panel={"state": {"actors": []}})
        self.assertIn("PHYSICS RULES", p)
        self.assertIn("Real weight", p)

    def test_motion_cadence_forbids_stutter(self):
        p = self._prompt(duration=4)
        self.assertIn("MOTION CADENCE", p)
        low = p.lower()
        self.assertIn("no frame-stutter", low)
        self.assertIn("no dropped frames", low)
        self.assertIn("4s", p)

    def test_block_order_is_stable(self):
        p = self._prompt(prompts={"style": "STYLE: x"})
        names = []
        for line in p.split("\n\n"):
            if ":" in line[:40]:
                names.append(line.split(":", 1)[0])
        # STYLE PREFIX first, then the scene/geometry blocks, then optics.
        self.assertEqual(names[0], "STYLE PREFIX")
        self.assertIn("SCENE CONTEXT", names)
        self.assertIn("OPTICS", names)
        self.assertLess(names.index("SCENE CONTEXT"), names.index("OPTICS"))
        self.assertLess(names.index("FORMAT MODE"), names.index("LIGHTING"))


if __name__ == "__main__":
    unittest.main()
