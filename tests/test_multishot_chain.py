"""End-to-end: a multishot panel reaches the video prompt intact.

The chain:
  PASS2 emits `shots` -> the passes merge (p1 -> p1a -> p2 -> p3, later
  wins) -> the panel lands in animation_metadata.json -> the animator
  builds the video prompt -> ACTION TIMING carries a numbered shot list
  and the blocks that would contradict it are switched.

A unit test on the prompt builder alone would not catch a break in the
merge or in the schema. This walks the whole path.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import build_video_prompt
from lib.core.schemas import PASS3_SCHEMA
from lib.studio.screenwriter.passes import _merge_scene_passes

SHOTS = [
    {"scale": "MS", "duration": 4,
     "description": "Lin pushes the door open and steps into the corridor",
     "camera": "locked off"},
    {"scale": "CU", "duration": 4,
     "description": "his face as he sees the figure at the far end",
     "camera": "slow push in"},
]


def _panel(idx=1, **kw):
    p = {
        "panel_index": idx,
        "hook_type": "escalation",
        "duration": 8,
        "scale": "MS",
        "motion_intent": "he enters",
        "dialogue_seed": "",
        "drama_requirements": {},
        "visual_start": "[SCALE] MS 35mm eye-level cam@[west-sandbag-wall]",
        "visual_end": "[SCALE] CU 85mm eye-level cam@[west-sandbag-wall]",
        "lights_and_camera": "locked MS",
        "motion_prompt": "0s [Lin-Wei-ming]: shoulders hunched.",
        "is_reversed": False,
        "motion_prompt_reversed": "",
        "dialogue": "",
        "voiceover": "",
        "voiceover_settings": {},
        "emotional_beat": "dread",
        "transition_to_next": "hard_cut",
        "sound_design": "room tone",
        "caption": "he's not alone",
    }
    p.update(kw)
    return p


class MergeTests(unittest.TestCase):
    def test_pass2_shots_survive_the_merge(self):
        p1 = {"scenes": [{"scene_id": 1, "panels": [_panel()]}]}
        p2 = {"panels": [_panel(shots=SHOTS)]}
        p3 = {"panels": [_panel()], "nitpicker_report": "", "shit_redo_report": ""}
        merged = _merge_scene_passes({}, p1["scenes"][0], None, p2, p3)
        panel = merged["panels"][0]
        self.assertEqual(len(panel["shots"]), 2)
        self.assertEqual(panel["shots"][0]["scale"], "MS")
        self.assertIn("steps into the corridor", panel["shots"][0]["description"])

    def test_pass3_does_not_clobber_pass2_shots(self):
        """The merge is p1 -> p1a -> p2 -> p3, later wins. PASS3's schema
        has no `shots`, so it cannot replace PASS2's descriptions - but
        only because it is not allowed to."""
        self.assertNotIn("shots", PASS3_SCHEMA["properties"]["panels"]["items"][
            "properties"])
        p1 = {"scenes": [{"scene_id": 1, "panels": [_panel()]}]}
        p2 = {"panels": [_panel(shots=SHOTS)]}
        p3 = {"panels": [_panel()], "nitpicker_report": "", "shit_redo_report": ""}
        merged = _merge_scene_passes({}, p1["scenes"][0], None, p2, p3)
        self.assertIn("steps into the corridor",
                      merged["panels"][0]["shots"][0]["description"])

    def test_a_panel_without_shots_merges_cleanly(self):
        p1 = {"scenes": [{"scene_id": 1, "panels": [_panel()]}]}
        p2 = {"panels": [_panel()]}
        p3 = {"panels": [_panel()], "nitpicker_report": "", "shit_redo_report": ""}
        merged = _merge_scene_passes({}, p1["scenes"][0], None, p2, p3)
        self.assertNotIn("shots", merged["panels"][0])


class PromptTests(unittest.TestCase):
    def test_merged_multishot_panel_reaches_the_video_prompt(self):
        p1 = {"scenes": [{"scene_id": 1, "panels": [_panel()]}]}
        p2 = {"panels": [_panel(shots=SHOTS)]}
        p3 = {"panels": [_panel()], "nitpicker_report": "", "shit_redo_report": ""}
        panel = _merge_scene_passes({}, p1["scenes"][0], None, p2, p3)["panels"][0]
        prompt = build_video_prompt(panel, [], [], panel["duration"])
        self.assertIn("SHOT 1 (MS) [0s-4s]", prompt)
        self.assertIn("SHOT 2 (CU) [4s-8s]", prompt)
        self.assertIn("MULTI-SHOT", prompt)
        self.assertNotIn("one continuous take", prompt)

    def test_single_shot_panel_is_unchanged(self):
        p1 = {"scenes": [{"scene_id": 1, "panels": [_panel()]}]}
        p2 = {"panels": [_panel()]}
        p3 = {"panels": [_panel()], "nitpicker_report": "", "shit_redo_report": ""}
        panel = _merge_scene_passes({}, p1["scenes"][0], None, p2, p3)["panels"][0]
        prompt = build_video_prompt(panel, [], [], panel["duration"])
        self.assertIn("one continuous take", prompt)
        self.assertNotIn("SHOT 1", prompt)


if __name__ == "__main__":
    unittest.main()
