"""Every style's panel judge is told how to tag hard failures [CRITICAL] — from one constant."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.prompts import resolve_style_file
from lib.studio import critic
from lib.studio.qa_gate import CRITICAL_TAGGING

STYLES = sorted(d.name for d in (Path(__file__).resolve().parents[1] / "lib" / "prompting").iterdir()
                if (d / "config.json").exists())


class _LLM:
    prompt = None

    def analyze_image(self, image=None, prompt=None, schema=None):
        _LLM.prompt = prompt
        return {"fidelity": 9, "character_consistency": 9, "composition_match": 9,
                "dramatic_intensity": 9, "artifacts": [], "needs_refinement": False}


def _judge_prompt(qa):
    panel = {"panel_index": 1, "visual_start": "MS", "references": [], "location_references": []}
    critic.analyze_panel(llm=_LLM(), panel_img=Image.new("RGB", (8, 8)), panel_meta=panel,
                         scene_meta={"scene_id": 1, "panels": [panel]}, ref_catalog={},
                         scene_id=1, panel_id=1, threshold=5, prompts={"qa": qa} if qa else None)
    return _LLM.prompt


class CriticalTaggingTests(unittest.TestCase):
    def test_every_style_judge_gets_the_rule_once(self):
        for style in STYLES:
            self.assertEqual(_judge_prompt(resolve_style_file(style, "qa")).count(CRITICAL_TAGGING), 1, style)

    def test_the_built_in_fallback_gets_it_too(self):
        self.assertIn(CRITICAL_TAGGING, _judge_prompt(None))


if __name__ == '__main__':
    unittest.main()
