"""Item 7a: acting master-profile wording in casting packs + schemas.

The two existing text fields gain their missing acting components:
- behavioral_signature: tics WITH triggers + the mask/crack clause
  ("However, when X - the visible change").
- physical_vocabulary: a named gait + the softening target.
- Combined cap 60 words; observable body behavior only.
Constraint: no new fields, the required key set untouched (plan Item 7a).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.prompts import resolve_style_file
from lib.core.schemas import CHARACTER_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
STYLES = sorted(d.name for d in (ROOT / "lib" / "prompting").iterdir() if (d / "config.json").exists())

_SHORT_BLOCKS = [
    "behavioral_signature", "physical_vocabulary",
    "behavioral_signature_additions", "physical_vocabulary_additions",
]


def _blocks():
    return _props()


class CastingPackTests(unittest.TestCase):
    def test_every_style_casting_prompt_defines_the_acting_components(self):
        for style in STYLES:
            text = resolve_style_file(style, "casting").lower()
            for phrase in ("mask", "crack", "gait", "softening", "60 words"):
                self.assertIn(phrase, text, f"{style} casting missing '{phrase}'")


def _props():
    return CHARACTER_SCHEMA["items"]["properties"]


def _required():
    return CHARACTER_SCHEMA["items"]["required"]


class CharacterSchemaTests(unittest.TestCase):
    def test_no_new_fields_and_required_untouched(self):
        # 7a constraint: no field added, the six required keys unchanged
        self.assertEqual(_required(),
                         ["name", "logline_subject_info", "visual_desc", "type",
                          "style_reference", "video_visual_desc"])
        self.assertEqual(len(_props()), 11)
        self.assertNotIn("acting_profile", _props())

    def test_behavioral_signature_requires_triggers_mask_crack(self):
        desc = _blocks()["behavioral_signature"]["description"]
        for phrase in ("trigger", "However, when", "60 words"):
            self.assertIn(phrase, desc)

    def test_physical_vocabulary_requires_gait_and_softening(self):
        desc = _blocks()["physical_vocabulary"]["description"].lower()
        for phrase in ("named gait", "softening", "60 words"):
            self.assertIn(phrase, desc)


if __name__ == "__main__":
    unittest.main()
