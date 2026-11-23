"""Item 8b: experimental master shot — one 2s wide static reference clip
per scene, generated from the scene arrangement (first frame + location
ref + in-frame character refs via the Item 2 assembler, one spatial map
line). Skip-if-exists on re-run; DRY=1 dumps instead of submitting.
"""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation.grok_openrouter import GrokOpenRouterAnimator
from lib.llm import manual as manual_mod

from support import StubLLM, make_ref_project


class Harness(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("DRY",)}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_manual_dir = manual_mod._OUTPUT_DIR
        self.addCleanup(setattr, manual_mod, '_OUTPUT_DIR', self._orig_manual_dir)
        self.root = Path(self.tmp.name)
        self.ref_dir = self.root / "ref_thriller"
        self.panels_dir = self.root / "panels"
        self.out_dir = self.root / "clips"
        self.project = make_ref_project(
            self.root, (("Groom", "Character"), ("Reporter", "Character"),
                        ("Hall-View-From-Entrance", "Room")))

        self.scene = {
            "scene_id": 1,
            "panels": [
                {"panel_index": 1, "duration": 4,
                 "location_references": ["Hall-View-From-Entrance"],
                 "references": ["Groom"],
                 "state": {"actors": [
                     {"name": "Groom", "visual_ref": "Groom", "in_frame": True},
                     {"name": "Reporter", "visual_ref": "Reporter",
                      "in_frame": True}]},
                 "motion_intent": "The Groom waits.", "motion_prompt": "",
                 "visual_start": "MS 35mm eye-level cam@[doors]",
                 "visual_disposition": "Groom stands on [top-step]",
                 "dialogue": "Groom: You came.", "voiceover": "",
                 "is_reversed": False},
                {"panel_index": 2, "duration": 4,
                 "location_references": ["Hall-View-From-Entrance"],
                 "references": [], "state": {"actors": []},
                 "motion_intent": "The Reporter enters.", "motion_prompt": "",
                 "visual_start": "CU 50mm eye-level cam@[doors]",
                 "visual_disposition": "", "dialogue": "", "voiceover": "",
                 "is_reversed": False},
            ],
        }
        self.panels_dir.mkdir(parents=True)
        (self.panels_dir / "001_01_static.png").write_bytes(b"PNGs1")
        (self.panels_dir / "001_02_static.png").write_bytes(b"PNGs2")
        self.llm = StubLLM()

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def animator(self):
        return GrokOpenRouterAnimator(api_key="test", llm=self.llm,
                                      project=self.project)

    def _hall_with_anchors(self):
        hall = self.project.character_info["Hall-View-From-Entrance"]
        hall["anchor_points"] = {
            "axes": "X: 0=image-left (West), 1=image-right (East). "
                    "View-From-Entrance (camera faces North): depth=Y.",
            "objects": [{"id": "doors", "label": "double doors"}],
        }


class MasterShotTests(Harness):
    def test_submit_builds_two_second_static_ref_clip(self):
        self._hall_with_anchors()
        out = self.animator().master_shot(self.scene, self.panels_dir,
                                          self.out_dir)
        self.assertEqual(out, self.out_dir / "master_001.mp4")
        self.assertTrue(out.exists())
        self.assertEqual(len(self.llm.calls), 1)
        call = self.llm.calls[0]
        self.assertEqual(call["duration"], 2)
        # refs: first frame + location + both in-frame characters
        self.assertEqual(len(call["reference_images"]), 3)
        prompt = call["prompt"]
        self.assertIn("static", prompt.lower())
        self.assertIn("master", prompt.lower())  # declares its role
        self.assertNotIn("Voice:", prompt)       # no dialogue
        self.assertIn("GEOMETRY", prompt)        # one spatial map line

    def test_style_prohibitions_reach_the_prompt(self):
        animator = self.animator()
        animator.prompts = {"animation_prohibitions": "STYLE-OWN-PROHIBITIONS"}
        animator.master_shot(self.scene, self.panels_dir, self.out_dir)
        self.assertIn("STYLE-OWN-PROHIBITIONS", self.llm.calls[0]["prompt"])

    def test_skip_if_exists(self):
        self.out_dir.mkdir(parents=True)
        (self.out_dir / "master_001.mp4").write_bytes(b"old")
        with self.assertLogs(level=logging.INFO) as logs:
            out = self.animator().master_shot(self.scene, self.panels_dir,
                                              self.out_dir)
        self.assertIsNone(out)
        self.assertEqual(self.llm.calls, [])
        self.assertTrue(any("skip" in o.lower() for o in logs.output))

    def test_dry_dumps_instead_of_submitting(self):
        os.environ["DRY"] = "1"
        manual_mod._OUTPUT_DIR = self.root / "manual_llm"
        out = self.animator().master_shot(self.scene, self.panels_dir,
                                          self.out_dir)
        self.assertIsNone(out)
        self.assertEqual(self.llm.calls, [])
        dumps = list((self.root / "manual_llm").glob("master_s001*.md"))
        self.assertEqual(len(dumps), 1)
        text = dumps[0].read_text()
        self.assertIn("## PROMPT", text)
        self.assertIn('"duration": 2', text)

    def test_missing_first_frame_returns_none(self):
        (self.panels_dir / "001_01_static.png").unlink()
        with self.assertLogs(level=logging.WARNING):
            out = self.animator().master_shot(self.scene, self.panels_dir,
                                              self.out_dir)
        self.assertIsNone(out)
        self.assertEqual(self.llm.calls, [])


if __name__ == "__main__":
    unittest.main()
