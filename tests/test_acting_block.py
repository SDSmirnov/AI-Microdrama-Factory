"""Item 7b: ACTING block + EYE LIFE line in the video prompt.

One acting contribution per in-frame speaker, from ref JSONs (NOT panel
metadata): physical_vocabulary (<=35 words), behavioral_signature (<=25
words), current state from the actor entry. Hard cap 120 words per clip;
priority speaker > second in-frame actor > rest. Empty fields -> clause
omitted, EYE LIFE retained, one log line per run.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.prompt_builder import (RefBite, build_acting,
                                          build_video_prompt)

HU_PHYS = ("Constant micro-motion — thumb on lighter wheel, weight shifts heel "
           "to heel. Leans on sandbags casually until threat appears, then "
           "freezes mid-gesture, hand hovering over the rifle stock.")
HU_BEH = ("Under pressure: jokes and minimizes (it's just drills, antenna "
          "fell). Power move: fill silence with talk and lighter clicks. "
          "Deflection: blame wind, blame equipment. However, when the "
          "radio calls real contact — the jokes cut off mid-word and the "
          "lighter stops clicking.")


def _panel(dialogue="Ху (мужской): Опять учения."):
    return {
        "panel_index": 1,
        "motion_prompt": "He snaps the lighter.",
        "motion_intent": "The Groom waits.",
        "dialogue": dialogue,
        "voiceover": "",
        "sound_design": "radio static",
        "visual_start": "[SCALE] MS 35mm eye-level cam@[wall]\nLIGHT: dim",
        "state": {"actors": [
            {"name": "Private-Hu", "visual_ref": "Private-Hu",
             "in_frame": True, "pose": "standing",
             "position": "at [east-sandbag-stack]",
             "gaze_target": "[sea-horizon]"},
            {"name": "Lin-Wei-ming", "visual_ref": "Lin-Wei-ming",
             "in_frame": True, "pose": "standing",
             "position": "at [seaward-embrasure-lip]",
             "gaze_target": "[sea-horizon]"},
        ]},
    }


def _refs():
    return [
        RefBite("<IMAGE_0>", None, "first_frame", "001_01_static", ""),
        RefBite("<IMAGE_1>", None, "location", "Observation-Post", "a post"),
        RefBite("<IMAGE_2>", None, "character", "Lin-Wei-ming", "34yo man"),
        RefBite("<IMAGE_3>", None, "character", "Private-Hu", "20yo conscript"),
    ]


HU_INFO = {"name": "Private-Hu", "behavioral_signature": HU_BEH,
           "physical_vocabulary": HU_PHYS}
INFO = {
    "Private-Hu": HU_INFO,
    "Lin-Wei-ming": {"name": "Lin-Wei-ming",
                     "behavioral_signature": "Under pressure: goes silent and still; "
                                             "mask is dry procedure. However, when outranked by idiots — the jaw shifts.",
                     "physical_vocabulary": "Named gait: unhurried parade step, "
                                            "heel strikes audible. Softening target: flat heel-first walk at home."},
}


class BuildActingTests(unittest.TestCase):
    def test_extracts_fields_tags_and_state(self):
        acting = build_acting(_panel(), _refs(), INFO)
        self.assertEqual(len(acting), 2)
        hu = next(a for a in acting if a.name == "Private-Hu")
        self.assertEqual(hu.tag, "<IMAGE_3>")
        self.assertIn("lighter wheel", hu.physical)
        self.assertIn("lighter clicks", hu.behavioral)
        self.assertIn("gaze: [sea-horizon]", hu.state)

    def test_no_character_info_no_log_crash_and_empty_clauses(self):
        with self.assertLogs(level=logging.INFO) as logs:
            acting = build_acting(_panel(), _refs(), {})
        self.assertEqual(acting, [])
        self.assertTrue(any("acting" in o.lower() for o in logs.output))

    def test_speaker_gets_priority(self):
        acting = build_acting(_panel(), _refs(), INFO)
        self.assertEqual(acting[0].name, "Private-Hu")  # 'Ху' speaks

    def test_dialogue_without_actor_match_still_orders(self):
        p = _panel(dialogue="")
        acting = build_acting(p, _refs(), INFO)
        # no speaker: ref order preserved
        self.assertEqual([a.name for a in acting],
                         ["Lin-Wei-ming", "Private-Hu"])


class ActingBlockTests(unittest.TestCase):
    def test_block_renders_name_tag_state_and_eye_life(self):
        acting = build_acting(_panel(), _refs(), INFO)
        prompt = build_video_prompt(_panel(), _refs(), [], 4, acting=acting)
        block = prompt.split("ACTING:")[1].split("OPTICS:")[0]
        self.assertIn("Private-Hu (<IMAGE_3>)", block)
        self.assertIn("EYE LIFE", block)
        self.assertIn("gaze: [sea-horizon]", block)

    def test_word_caps_enforced(self):
        acting = build_acting(_panel(), _refs(), INFO)
        hu = next(a for a in acting if a.name == "Private-Hu")
        self.assertLessEqual(len(hu.physical.split()), 35)
        self.assertLessEqual(len(hu.behavioral.split()), 25)

    def test_total_budget_truncates_lowest_priority(self):
        # Hu's 35+25 words already near the 120 cap; a third actor with long
        # fields gets truncated away, logged once.
        info = dict(INFO)
        info["Lin-Wei-ming"] = {
            "name": "Lin-Wei-ming",
            "behavioral_signature": " ".join(["word"] * 60),
            "physical_vocabulary": " ".join(["move"] * 60),
        }
        with self.assertLogs(level=logging.INFO) as logs:
            acting = build_acting(_panel(), _refs(), info)
        lin = next(a for a in acting if a.name == "Lin-Wei-ming")
        self.assertLess(
            len(lin.physical.split()) + len(lin.behavioral.split()), 60)
        self.assertTrue(any("budget" in o.lower() for o in logs.output))

    def test_no_character_bites_no_acting_block(self):
        refs = [RefBite("<IMAGE_0>", None, "first_frame", "001_01_static", ""),
                RefBite("<IMAGE_1>", None, "location", "Hall", "a hall")]
        prompt = build_video_prompt(_panel(), refs, [], 4, acting=[])
        self.assertNotIn("ACTING:", prompt)

    def test_eye_life_retained_even_without_data(self):
        prompt = build_video_prompt(_panel(), _refs(), [], 4,
                                    acting=build_acting(_panel(), _refs(), {}))
        self.assertIn("EYE LIFE", prompt)


if __name__ == "__main__":
    unittest.main()
