"""Multi-shot panels — several shots inside one generated clip.

The repo was written when a video model did simple I2V: one start frame, a
fixed ~6 s clip, one shot. Today's models hold SEVERAL shots in one
generation (Seedance 2.0's documented multi-shot mode takes "Shot 1...
Shot 2... Shot 3..." in one prompt; Grok's reference mode accepts up to a
10 s clip). A panel can therefore describe a short SEQUENCE instead of one
setup.

These tests cover the prompt-side implementation. The BLOCK-level checks
matter most: a multi-shot panel must not also claim "one continuous take",
which would contradict the shot list.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import (POSITIVE_PHOTO_LOCKS,
                                          POSITIVE_PHOTO_LOCKS_MULTISHOT,
                                          build_video_prompt)

SHOTS = [
    {"scale": "MS", "duration": 3,
     "description": "Lin pushes the door open and steps into the corridor",
     "camera": "locked off"},
    {"scale": "CU", "duration": 3,
     "description": "his face as he sees the figure at the far end",
     "camera": "slow push in"},
]

BASE = {
    "panel_index": 1,
    "visual_start": "[SCALE] MS 35mm eye-level cam@[west-sandbag-wall]",
    "lights_and_camera": "locked MS",
    "motion_prompt": "0s [Lin-Wei-ming]: shoulders hunched, both hands gripping the rifle.",
    "motion_intent": "he enters",
    "emotional_beat": "dread",
    "dialogue": "",
    "voiceover": "",
    "duration": 6,
    "state": {"actors": [{"name": "Lin-Wei-ming", "in_frame": True,
                          "pose": "standing", "position": "centre",
                          "gaze_target": "sea", "chest_direction": "sea",
                          "head_direction": "sea"}]},
}


def _prompt(**kw):
    panel = dict(BASE)
    panel.update(kw)
    return build_video_prompt(panel, [], [], panel.get("duration", 6))


class SingleShotTests(unittest.TestCase):
    def test_default_is_a_single_continuous_take(self):
        p = _prompt()
        self.assertIn("one continuous take", p)
        self.assertNotIn("MULTI-SHOT", p)
        self.assertNotIn("SHOT 1", p)

    def test_positive_locks_say_one_continuous_take(self):
        self.assertIn("one continuous take", POSITIVE_PHOTO_LOCKS)

    def test_action_timing_is_the_motion_prompt(self):
        p = _prompt()
        self.assertIn("Complete the full action within the 6-second clip.", p)


class MultiShotTests(unittest.TestCase):
    def test_format_mode_declares_the_shot_count(self):
        p = _prompt(shots=SHOTS)
        self.assertIn("MULTI-SHOT", p)
        self.assertIn("2 shots inside this one clip", p)

    def test_format_mode_does_not_claim_one_continuous_take(self):
        p = _prompt(shots=SHOTS)
        self.assertNotIn("one continuous take", p)

    def test_action_timing_lists_the_shots_with_time_windows(self):
        p = _prompt(shots=SHOTS)
        self.assertIn("SHOT 1 (MS) [0s-3s]", p)
        self.assertIn("SHOT 2 (CU) [3s-6s]", p)
        self.assertIn("Lin pushes the door open", p)
        self.assertIn("slow push in", p)

    def test_action_timing_keeps_the_motion_prompt(self):
        p = _prompt(shots=SHOTS)
        self.assertIn("shoulders hunched", p)

    def test_positive_locks_use_the_multishot_variant(self):
        p = _prompt(shots=SHOTS)
        self.assertIn("cuts between shots are clean and motivated", p)
        self.assertNotIn("one continuous take with a", p)

    def test_multishot_locks_differ_from_single_shot_locks(self):
        self.assertNotEqual(POSITIVE_PHOTO_LOCKS,
                            POSITIVE_PHOTO_LOCKS_MULTISHOT)

    def test_shot_list_warns_when_the_durations_mismatch(self):
        p = _prompt(shots=SHOTS, duration=8)
        self.assertIn("compress the final beat to fit", p)

    def test_shot_list_is_silent_for_a_single_shot_entry(self):
        p = _prompt(shots=[SHOTS[0]])
        self.assertNotIn("SHOT 1", p)
        self.assertIn("one continuous take", p)

    def test_camera_is_optional(self):
        shots = [{"scale": "MS", "duration": 3,
                  "description": "Lin stands still"},
                 {"scale": "CU", "duration": 3,
                  "description": "his face"}]
        p = _prompt(shots=shots)
        self.assertIn("SHOT 1 (MS) [0s-3s]", p)
        self.assertIn("SHOT 2 (CU) [3s-6s]", p)
        self.assertIn("Lin stands still", p)

    def test_motion_cadence_does_not_claim_one_continuous_take(self):
        p = _prompt(shots=SHOTS)
        self.assertNotIn("One continuous take.", p)
        self.assertIn("cuts between shots are clean and motivated", p)


class SchemaTests(unittest.TestCase):
    def test_panels_may_declare_shots(self):
        from lib.core.schemas import PASS2_SCHEMA
        props = PASS2_SCHEMA["properties"]["panels"]["items"]["properties"]
        self.assertIn("shots", props)
        self.assertIn("scale", props["shots"]["items"]["properties"])
        self.assertIn("duration", props["shots"]["items"]["properties"])
        self.assertIn("description", props["shots"]["items"]["properties"])

    def test_shots_is_optional(self):
        from lib.core.schemas import PASS2_SCHEMA
        required = PASS2_SCHEMA["properties"]["panels"]["items"]["required"]
        self.assertNotIn("shots", required)

    def test_pass2_owns_shots(self):
        """PASS2 fills in each shot's description and camera, so PASS2 owns
        the field. PASS3 must NOT emit it: the passes merge p1 -> p1a -> p2
        -> p3 with later wins, so a PASS3 `shots` would replace PASS2's
        descriptions with whatever PASS3 wrote."""
        from lib.core.schemas import PASS2_SCHEMA, PASS3_SCHEMA
        p2 = PASS2_SCHEMA["properties"]["panels"]["items"]["properties"]
        p3 = PASS3_SCHEMA["properties"]["panels"]["items"]["properties"]
        self.assertIn("shots", p2)
        self.assertNotIn("shots", p3)

    def test_pass1_cannot_emit_shots(self):
        """PASS1's schema is additionalProperties: False, so it cannot
        carry `shots` - the shot count lives in the panel's duration and
        scale, and PASS2 does the breakdown."""
        from lib.core.schemas import PASS1_SCHEMA
        props = PASS1_SCHEMA["properties"]["scenes"]["items"]["properties"][
            "panels"]["items"]["properties"]
        self.assertNotIn("shots", props)
        self.assertFalse(
            PASS1_SCHEMA["properties"]["scenes"]["items"]["properties"][
                "panels"]["items"].get("additionalProperties", True))


if __name__ == "__main__":
    unittest.main()
